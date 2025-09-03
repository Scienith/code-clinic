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
    
    def check_violations(self, project_data: ProjectData) -> List[ImportViolation]:
        """
        检查所有导入违规
        
        Args:
            project_data: 项目数据
            
        Returns:
            List[ImportViolation]: 违规列表
        """
        violations = []
        
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
        # 1. 检查白名单
        if self._is_in_whitelist(to_node.name):
            return None
        
        # 2. 检查跨包导入
        if not self.rules.allow_cross_package:
            violation = self._check_cross_package_violation(from_node, to_node)
            if violation:
                return violation
        
        # 3. 检查向上导入
        if not self.rules.allow_upward_import:
            violation = self._check_upward_import_violation(from_node, to_node)
            if violation:
                return violation
        
        # 4. 检查跳级导入
        if not self.rules.allow_skip_levels:
            violation = self._check_skip_level_violation(from_node, to_node)
            if violation:
                return violation
        
        return None
    
    def _is_in_whitelist(self, module_name: str) -> bool:
        """检查模块是否在白名单中"""
        for pattern in self.rules.white_list:
            # 完整匹配
            if fnmatch.fnmatch(module_name, pattern) or module_name == pattern:
                return True
            
            # 支持简化名称匹配（只匹配最后一级）
            module_parts = module_name.split('.')
            if module_parts[-1] == pattern:
                return True
                
        return False
    
    def _check_cross_package_violation(self, from_node: NodeInfo, to_node: NodeInfo) -> Optional[ImportViolation]:
        """
        检查跨包导入违规
        
        跨包导入指：不在同一个父包下的包之间的导入
        例如：packageA.moduleX 导入 packageB.moduleY
        """
        from_parts = from_node.name.split('.')
        to_parts = to_node.name.split('.')
        
        # 如果两个节点都只有一层（顶级），允许导入
        if len(from_parts) <= 1 and len(to_parts) <= 1:
            return None
        
        # 检查是否有共同的父包
        # 如果没有共同的顶级包，这就是跨包导入
        if len(from_parts) > 0 and len(to_parts) > 0:
            if from_parts[0] != to_parts[0]:
                return ImportViolation(
                    from_node=from_node.name,
                    to_node=to_node.name,
                    violation_type="cross_package",
                    message=f"跨包导入违规: {from_node.name} 不应导入不同顶级包 {to_node.name}",
                    severity="error"
                )
        
        return None
    
    def _check_upward_import_violation(self, from_node: NodeInfo, to_node: NodeInfo) -> Optional[ImportViolation]:
        """
        检查向上导入违规
        
        向上导入指：子模块导入父模块或祖先模块
        例如：package.subpackage.module 导入 package
        """
        from_parts = from_node.name.split('.')
        to_parts = to_node.name.split('.')
        
        # 如果to_node的路径是from_node路径的前缀，这就是向上导入
        if len(to_parts) < len(from_parts):
            to_prefix = '.'.join(to_parts)
            from_prefix = '.'.join(from_parts[:len(to_parts)])
            
            if to_prefix == from_prefix:
                return ImportViolation(
                    from_node=from_node.name,
                    to_node=to_node.name,
                    violation_type="upward_import",
                    message=f"向上导入违规: 子模块 {from_node.name} 不应导入父模块 {to_node.name}",
                    severity="error"
                )
        
        return None
    
    def _check_skip_level_violation(self, from_node: NodeInfo, to_node: NodeInfo) -> Optional[ImportViolation]:
        """
        检查跳级导入违规
        
        跳级导入指：跳过中间层级的导入
        例如：a.b 导入 a.c.d.e，跳过了 a.c
        
        规则：只允许导入直接子级或同级模块
        """
        from_parts = from_node.name.split('.')
        to_parts = to_node.name.split('.')
        
        # 检查是否为同级模块（共同父级）
        if self._are_siblings(from_parts, to_parts):
            return None
        
        # 检查是否为直接子级
        if self._is_direct_child(from_parts, to_parts):
            return None
        
        # 检查是否为直接父级（如果允许向上导入）
        if self.rules.allow_upward_import and self._is_direct_parent(from_parts, to_parts):
            return None
        
        # 其他情况都是跳级导入
        return ImportViolation(
            from_node=from_node.name,
            to_node=to_node.name,
            violation_type="skip_levels",
            message=f"跳级导入违规: {from_node.name} 应该通过中间层级导入 {to_node.name}",
            severity="warning"
        )
    
    def _are_siblings(self, from_parts: List[str], to_parts: List[str]) -> bool:
        """检查两个模块是否为同级（有相同的直接父级）"""
        if len(from_parts) != len(to_parts):
            return False
        
        # 比较除了最后一部分的所有部分
        if len(from_parts) > 1:
            return from_parts[:-1] == to_parts[:-1]
        else:
            # 都是顶级模块
            return True
    
    def _is_direct_child(self, from_parts: List[str], to_parts: List[str]) -> bool:
        """检查to_node是否为from_node的直接子级"""
        if len(to_parts) != len(from_parts) + 1:
            return False
        
        return to_parts[:-1] == from_parts
    
    def _is_direct_parent(self, from_parts: List[str], to_parts: List[str]) -> bool:
        """检查to_node是否为from_node的直接父级"""
        if len(from_parts) != len(to_parts) + 1:
            return False
        
        return from_parts[:-1] == to_parts


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
        # 如果是字典，转换为ImportRulesConfig
        from .config_loader import ImportRulesConfig
        rules_obj = ImportRulesConfig()
        if 'white_list' in rules_config:
            rules_obj.white_list = rules_config['white_list']
        if 'allow_cross_package' in rules_config:
            rules_obj.allow_cross_package = rules_config['allow_cross_package']
        if 'allow_upward_import' in rules_config:
            rules_obj.allow_upward_import = rules_config['allow_upward_import']
        if 'allow_skip_levels' in rules_config:
            rules_obj.allow_skip_levels = rules_config['allow_skip_levels']
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