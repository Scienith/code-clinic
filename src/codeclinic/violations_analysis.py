"""
违规分析模块 - 分析导入违规并生成报告和可视化
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Any

from .node_types import ProjectData, ImportViolation
from .import_rules import check_import_violations, categorize_edges, generate_violation_summary


def analyze_violations(project_data: ProjectData) -> Dict[str, Any]:
    """
    分析项目的导入违规
    
    Args:
        project_data: 项目数据
        
    Returns:
        Dict: 违规分析结果 - 只包含violations
    """
    print("开始分析导入违规...")
    
    # 检查违规
    violations = check_import_violations(project_data)
    
    # 分析结果 - 只保留violations
    result = {
        "violations": violations
    }
    
    compliance_rate = 1 - (len(violations) / max(1, len(project_data.import_edges)))
    print(f"违规分析完成: 发现 {len(violations)} 个违规，合规率 {compliance_rate:.1%}")
    
    return result


def save_violations_report(
    violations_data: Dict[str, Any],
    project_data: ProjectData,
    output_dir: Path
) -> Path:
    """
    保存违规分析报告
    
    Args:
        violations_data: 违规分析数据
        project_data: 项目数据
        output_dir: 输出目录
        
    Returns:
        Path: violations.json文件路径
    """
    # 创建输出目录
    violations_dir = output_dir / "import_violations"
    violations_dir.mkdir(parents=True, exist_ok=True)
    
    # 准备JSON数据
    json_data = _prepare_json_data(violations_data, project_data)
    
    # 保存JSON文件
    json_path = violations_dir / "violations.json"
    with json_path.open('w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    # 生成可视化图
    svg_path = _generate_violations_graph(violations_data, project_data, violations_dir)
    
    print(f"✓ 违规报告保存到: {json_path}")
    if svg_path:
        print(f"✓ 违规可视化保存到: {svg_path}")
    
    return json_path


def _prepare_json_data(violations_data: Dict[str, Any], project_data: ProjectData) -> Dict[str, Any]:
    """准备JSON输出数据 - 只保留violations"""
    json_data = {
        "version": "1.0",
        "timestamp": project_data.timestamp,
        "project_root": project_data.project_root,
        "analysis_type": "import_violations",
        
        # 只保留违规详情
        "violations": [
            {
                "id": i + 1,
                "from_node": v.from_node,
                "to_node": v.to_node,
                "violation_type": v.violation_type,
                "severity": v.severity,
                "message": v.message,
                "from_node_type": project_data.nodes.get(v.from_node, {}).node_type.value if project_data.nodes.get(v.from_node) else "unknown",
                "to_node_type": project_data.nodes.get(v.to_node, {}).node_type.value if project_data.nodes.get(v.to_node) else "unknown"
            }
            for i, v in enumerate(violations_data["violations"])
        ]
    }
    
    return json_data


def _extract_rules_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """提取导入规则配置"""
    import_rules = config.get('import_rules', {})
    
    if hasattr(import_rules, '__dict__'):
        # 如果是ImportRulesConfig对象
        return {
            "white_list": import_rules.white_list,
            "allow_cross_package": import_rules.allow_cross_package,
            "allow_upward_import": import_rules.allow_upward_import,
            "allow_skip_levels": import_rules.allow_skip_levels
        }
    elif isinstance(import_rules, dict):
        return import_rules
    else:
        return {}


def _calculate_node_violation_stats(violations: List[ImportViolation]) -> Dict[str, Any]:
    """计算每个节点的违规统计"""
    from_violations = {}
    to_violations = {}
    
    for violation in violations:
        # 作为违规源的统计
        if violation.from_node not in from_violations:
            from_violations[violation.from_node] = {
                "total": 0,
                "by_type": {}
            }
        from_violations[violation.from_node]["total"] += 1
        vtype = violation.violation_type
        from_violations[violation.from_node]["by_type"][vtype] = \
            from_violations[violation.from_node]["by_type"].get(vtype, 0) + 1
        
        # 作为被违规导入目标的统计
        if violation.to_node not in to_violations:
            to_violations[violation.to_node] = {
                "total": 0,
                "by_type": {}
            }
        to_violations[violation.to_node]["total"] += 1
        to_violations[violation.to_node]["by_type"][vtype] = \
            to_violations[violation.to_node]["by_type"].get(vtype, 0) + 1
    
    return {
        "violating_importers": from_violations,  # 进行违规导入的节点
        "violated_targets": to_violations        # 被违规导入的节点
    }


def _generate_recommendations(violations: List[ImportViolation]) -> List[Dict[str, str]]:
    """生成修复建议"""
    recommendations = []
    
    # 按违规类型分组统计
    type_counts = {}
    for violation in violations:
        vtype = violation.violation_type
        type_counts[vtype] = type_counts.get(vtype, 0) + 1
    
    # 为每种违规类型生成建议
    if "cross_package" in type_counts:
        recommendations.append({
            "type": "cross_package",
            "count": str(type_counts["cross_package"]),
            "priority": "high",
            "suggestion": "考虑将共享代码提取到公共模块，或者将相关功能合并到同一个包中",
            "actions": "1. 识别可以共享的工具函数，移至utils模块; 2. 将相关业务逻辑合并到同一包; 3. 使用依赖注入减少直接依赖"
        })
    
    if "upward_import" in type_counts:
        recommendations.append({
            "type": "upward_import", 
            "count": str(type_counts["upward_import"]),
            "priority": "critical",
            "suggestion": "重构代码以消除循环依赖风险，使用依赖倒置原则",
            "actions": "1. 将被父模块需要的功能提取到独立模块; 2. 使用接口/抽象基类; 3. 考虑使用事件驱动架构"
        })
    
    if "skip_levels" in type_counts:
        recommendations.append({
            "type": "skip_levels",
            "count": str(type_counts["skip_levels"]),
            "priority": "medium", 
            "suggestion": "通过中间层级进行导入，或者重新组织模块结构",
            "actions": "1. 在中间层级的__init__.py中重新导出所需模块; 2. 重新评估模块层级是否合理"
        })
    
    return recommendations


def _generate_violations_graph(
    violations_data: Dict[str, Any],
    project_data: ProjectData, 
    output_dir: Path
) -> Path:
    """生成违规可视化图"""
    try:
        from .graphviz_render import render_violations_graph
        
        svg_path = output_dir / "violations_graph.svg"
        
        render_violations_graph(
            project_data.nodes,
            violations_data["legal_edges"],
            violations_data["violation_edges"],
            str(svg_path.with_suffix(''))  # 不带扩展名
        )
        
        return svg_path
    
    except ImportError as e:
        print(f"警告: 无法生成违规可视化图，缺少依赖: {e}")
        return None
    except Exception as e:
        print(f"警告: 生成违规可视化图时出错: {e}")
        return None