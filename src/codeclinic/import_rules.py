"""
导入规则引擎 - 检查导入关系是否违反架构规则
"""

from __future__ import annotations
from typing import List, Set, Tuple, Dict, Optional
import fnmatch

from .node_types import NodeInfo, NodeType, ImportViolation, ProjectData
from .config_loader import ImportRulesConfig


class ImportRuleChecker:
    """导入规则检查器"""
    
    def __init__(self, rules: ImportRulesConfig):
        self.rules = rules
        # 当前项目节点表（在 check_violations 时注入）
        self._nodes: Dict[str, NodeInfo] | None = None
    
    def check_violations(self, project_data: ProjectData) -> List[ImportViolation]:
        """
        检查所有导入违规
        
        Args:
            project_data: 项目数据
            
        Returns:
            List[ImportViolation]: 违规列表
        """
        violations = []
        
        # 为 <ancestor> 语义提供节点上下文
        self._nodes = project_data.nodes

        for from_node, to_node in project_data.import_edges:
            from_info = project_data.nodes.get(from_node)
            to_info = project_data.nodes.get(to_node)
            
            if not from_info or not to_info:
                continue
            
            violation = self._check_single_import(from_info, to_info)
            if violation:
                violations.append(violation)
        
        return violations
    
    def _check_single_import(self, from_node: NodeInfo, to_node: NodeInfo) -> Optional[ImportViolation]:
        """
        检查单个导入关系
        
        Args:
            from_node: 导入方节点
            to_node: 被导入节点
            
        Returns:
            ImportViolation: 如果违规则返回违规信息，否则返回None
        """
        # 1) 可选：私有模块导入（路径段以下划线开头）
        if getattr(self.rules, 'forbid_private_modules', False):
            v = self._check_private_module_import(to_node)
            if v:
                return v

        # 2) 基于矩阵的显式允许/禁止规则（唯一决策来源）
        matrix_decision = self._check_matrix_rules(from_node.name, to_node.name)
        if matrix_decision == "deny":
            return ImportViolation(
                from_node=from_node.name,
                to_node=to_node.name,
                violation_type="pattern_matrix",
                message=f"导入不在允许矩阵内: {from_node.name} -> {to_node.name}",
                severity="error",
            )
        if matrix_decision == "allow":
            return None
        # 3) 未命中时按 matrix_default 决策
        if str(getattr(self.rules, 'matrix_default', 'deny')).lower() == 'allow':
            return None
        return ImportViolation(
            from_node=from_node.name,
            to_node=to_node.name,
            violation_type="pattern_matrix",
            message=f"导入未命中允许矩阵，默认拒绝: {from_node.name} -> {to_node.name}",
            severity="error",
        )

    # ---- 矩阵匹配 ----
    def _check_matrix_rules(self, src: str, dst: str) -> str:
        """返回 'allow' | 'deny' | 'none'
        逻辑：
          - 私有模块检查不在此处处理（已在上层处理）
          - 若存在 deny_patterns 且匹配 -> deny（优先级高）
          - 若存在 allow_patterns 且匹配 -> allow
          - 若 allow_patterns 非空但均未匹配 -> 按 matrix_default（默认 deny）
          - 若无任何矩阵规则 -> none

        <ancestor> 语义（修订）：表示“导入方 src 的任一严格祖先包（非自身）”。
        - 替换时生成所有候选祖先（如 apps.projects.api.views -> apps.projects.api, apps.projects, apps）
        - 仅保留存在于项目节点表的 PACKAGE 祖先
        - 逐一替换后进行匹配

        支持通配符 * 与 fnmatch 模式。
        """
        allow_patterns = getattr(self.rules, 'allow_patterns', []) or []
        deny_patterns = getattr(self.rules, 'deny_patterns', []) or []
        matrix_default = str(getattr(self.rules, 'matrix_default', 'deny') or 'deny').lower()
        schema = getattr(self.rules, 'schema', {}) or {}

        def _ancestors_of(name: str) -> List[str]:
            parts = name.split('.') if name else []
            # 严格祖先：排除自身
            cands = ['.'.join(parts[:i]) for i in range(1, len(parts))]
            # 仅保留存在的 PACKAGE 节点（如有上下文）
            nodes = self._nodes or {}
            out: List[str] = []
            for a in cands:
                n = nodes.get(a)
                if n and n.node_type == NodeType.PACKAGE:
                    out.append(a)
            return out

        def _expand(pattern: str) -> List[str]:
            # 多步展开：<self>、<ancestor>、<global>、<public>
            pats = [pattern]
            # 展开 <self>
            tmp: List[str] = []
            for p in pats:
                if '<self>' in p:
                    tmp.append(p.replace('<self>', src))
                else:
                    tmp.append(p)
            pats = tmp
            # 展开 <ancestor>
            tmp = []
            for p in pats:
                if '<ancestor>' in p:
                    for anc in _ancestors_of(src):
                        tmp.append(p.replace('<ancestor>', anc))
                else:
                    tmp.append(p)
            pats = tmp
            # 展开 <global>
            tmp = []
            gset = list(schema.get('global', [])) or []
            if not gset:
                gset = ['utils*', 'types*', 'common*']  # 默认全局集合
            for p in pats:
                if '<global>' in p:
                    for g in gset:
                        tmp.append(p.replace('<global>', g))
                else:
                    tmp.append(p)
            pats = tmp
            # 展开 <public>
            tmp = []
            pset = list(schema.get('public', [])) or ['*.public.*']
            for p in pats:
                if '<public>' in p:
                    for g in pset:
                        tmp.append(p.replace('<public>', g))
                else:
                    tmp.append(p)
            pats = tmp
            # 去重
            seen = set()
            out: List[str] = []
            for p in pats:
                if p not in seen:
                    seen.add(p)
                    out.append(p)
            return out

        def _name_match(name: str, pat: str) -> bool:
            """专用于矩阵规则的匹配器，支持：
            - module         -> 仅匹配该模块本身
            - module.*       -> 仅匹配该模块的直接子模块
            - module.**      -> 匹配该模块的任意后代（不含自身）
            - 其他含 * 或 ?  -> 退回到 fnmatch 行为
            - '*'            -> 任意
            注意：这里不启用“末级段等值”捷径，避免语义歧义。
            """
            if pat == '*':
                return True
            # module.** -> descendants only
            if pat.endswith('.**'):
                prefix = pat[:-3]
                return name.startswith(prefix + '.') and name != prefix
            # module.* -> direct children only
            if pat.endswith('.*') and not pat.endswith('.**'):
                prefix = pat[:-2]
                if not name.startswith(prefix + '.'):
                    return False
                rest = name[len(prefix) + 1:]
                return rest != '' and ('.' not in rest)
            # generic wildcard -> fnmatch
            if ('*' in pat) or ('?' in pat):
                return fnmatch.fnmatch(name, pat)
            # exact match only
            return name == pat

        # deny 优先
        for pair in deny_patterns:
            try:
                s_pat, d_pat = pair
            except Exception:
                continue
            s_list = _expand(str(s_pat))
            d_list = _expand(str(d_pat))
            for s_exp in s_list:
                for d_exp in d_list:
                    if _name_match(src, s_exp) and _name_match(dst, d_exp):
                        return 'deny'

        any_matrix = bool(allow_patterns or deny_patterns)

        for pair in allow_patterns:
            try:
                s_pat, d_pat = pair
            except Exception:
                continue
            s_list = _expand(str(s_pat))
            d_list = _expand(str(d_pat))
            for s_exp in s_list:
                for d_exp in d_list:
                    if _name_match(src, s_exp) and _name_match(dst, d_exp):
                        return 'allow'

        # 未命中 allow/deny：无论是否配置了矩阵条目，均按默认策略处理
        return 'allow' if matrix_default == 'allow' else 'deny'

    def _check_private_module_import(self, to_node: NodeInfo) -> Optional[ImportViolation]:
        """当 forbid_private_modules 启用时，禁止导入路径包含私有段（以下划线开头）。"""
        parts = to_node.name.split('.')
        if any(part.startswith('_') for part in parts):
            return ImportViolation(
                from_node="",
                to_node=to_node.name,
                violation_type="private_module_import",
                message=f"禁止导入私有模块路径段（以下划线开头）: {to_node.name}",
                severity="error",
            )
        return None
    
    # 旧的跨包/跳层/上行/聚合门面检查已移除，矩阵规则为唯一决策来源


def check_import_violations(project_data: ProjectData) -> List[ImportViolation]:
    """
    检查项目的导入违规
    
    Args:
        project_data: 项目数据，应该包含import_rules配置
        
    Returns:
        List[ImportViolation]: 违规列表
    """
    # 从配置中获取导入规则
    rules_config = project_data.config.get('import_rules')
    if not rules_config:
        # 使用默认规则
        from .config_loader import ImportRulesConfig
        rules_config = ImportRulesConfig()
    elif isinstance(rules_config, dict):
        # 若传入 dict，则按新机制字段构建 ImportRulesConfig（不做旧机制兼容）
        from .config_loader import ImportRulesConfig
        rules_obj = ImportRulesConfig()
        ap = rules_config.get('allow_patterns') or rules_config.get('allowed_patterns')
        if isinstance(ap, list):
            tmp: List[tuple[str, str]] = []
            for it in ap:
                if isinstance(it, (list, tuple)) and len(it) == 2:
                    tmp.append((str(it[0]).strip(), str(it[1]).strip()))
            rules_obj.allow_patterns = tmp
        dp = rules_config.get('deny_patterns') or rules_config.get('denied_patterns')
        if isinstance(dp, list):
            tmpd: List[tuple[str, str]] = []
            for it in dp:
                if isinstance(it, (list, tuple)) and len(it) == 2:
                    tmpd.append((str(it[0]).strip(), str(it[1]).strip()))
            rules_obj.deny_patterns = tmpd
        md = rules_config.get('matrix_default')
        if isinstance(md, str) and md.strip().lower() in {'allow', 'deny'}:
            rules_obj.matrix_default = md.strip().lower()
        fpm = rules_config.get('forbid_private_modules')
        if isinstance(fpm, bool):
            rules_obj.forbid_private_modules = fpm
        # schema（命名集合）
        sc = rules_config.get('schema')
        if isinstance(sc, dict):
            parsed: Dict[str, List[str]] = {}
            for k, v in sc.items():
                if isinstance(v, list):
                    parsed[str(k)] = [str(x) for x in v]
            rules_obj.schema = parsed
        rules_config = rules_obj
    
    checker = ImportRuleChecker(rules_config)
    violations = checker.check_violations(project_data)
    
    return violations


def categorize_edges(
    project_data: ProjectData, 
    violations: List[ImportViolation]
) -> Tuple[Set[Tuple[str, str]], Set[Tuple[str, str]]]:
    """
    将导入边分类为合法和违规
    
    Args:
        project_data: 项目数据
        violations: 违规列表
        
    Returns:
        Tuple[Set, Set]: (合法边集合, 违规边集合)
    """
    violation_edges = {(v.from_node, v.to_node) for v in violations}
    legal_edges = project_data.import_edges - violation_edges
    
    return legal_edges, violation_edges


def generate_violation_summary(violations: List[ImportViolation]) -> Dict:
    """
    生成违规摘要统计
    
    Args:
        violations: 违规列表
        
    Returns:
        Dict: 违规统计信息
    """
    summary = {
        "total_violations": len(violations),
        "by_type": {},
        "by_severity": {},
        "violation_details": []
    }
    
    for violation in violations:
        # 按类型统计
        vtype = violation.violation_type
        summary["by_type"][vtype] = summary["by_type"].get(vtype, 0) + 1
        
        # 按严重程度统计
        severity = violation.severity
        summary["by_severity"][severity] = summary["by_severity"].get(severity, 0) + 1
        
        # 添加详情
        summary["violation_details"].append({
            "from": violation.from_node,
            "to": violation.to_node,
            "type": violation.violation_type,
            "severity": violation.severity,
            "message": violation.message
        })
    
    return summary
