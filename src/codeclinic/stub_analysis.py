"""
Stub完整度分析模块 - 分析@stub装饰器的分布和完整度
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple

from .node_types import ProjectData, FunctionInfo, NodeInfo


def analyze_stub_completeness(project_data: ProjectData) -> Dict[str, Any]:
    """
    分析项目的Stub完整度
    
    Args:
        project_data: 项目数据
        
    Returns:
        Dict: Stub完整度分析结果
    """
    print("开始分析Stub完整度...")
    
    # 收集所有stub函数
    stub_functions = project_data.stub_functions
    
    # 按节点分组统计
    node_stats = _calculate_node_stub_stats(project_data.nodes)
    
    # 按深度分组统计  
    depth_stats = _calculate_depth_stub_stats(project_data.nodes)
    
    # 全局统计
    total_functions = sum(node.functions_public for node in project_data.nodes.values())
    total_stubs = sum(node.stubs for node in project_data.nodes.values())
    global_stub_ratio = total_stubs / max(1, total_functions)
    
    result = {
        "summary": {
            "total_nodes": len(project_data.nodes),
            "total_functions": total_functions,
            "total_public_functions": total_functions,  # 这里假设统计的就是public
            "total_stubs": total_stubs,
            "global_stub_ratio": global_stub_ratio,
            "nodes_with_stubs": len([n for n in project_data.nodes.values() if n.stubs > 0]),
            "fully_stubbed_nodes": len([n for n in project_data.nodes.values() if n.stub_ratio >= 1.0]),
            "fully_implemented_nodes": len([n for n in project_data.nodes.values() if n.stub_ratio == 0.0])
        },
        "node_stats": node_stats,
        "depth_stats": depth_stats,
        "stub_functions": stub_functions,
        "completion_distribution": _calculate_completion_distribution(project_data.nodes)
    }
    
    print(f"Stub分析完成: {total_stubs}/{total_functions} 函数为stub ({global_stub_ratio:.1%})")
    
    return result


def _calculate_node_stub_stats(nodes: Dict[str, NodeInfo]) -> List[Dict[str, Any]]:
    """计算每个节点的stub统计"""
    node_stats = []
    
    for node_name, node in nodes.items():
        stat = {
            "name": node_name,
            "node_type": node.node_type.value,
            "file_path": node.file_path,
            "package_depth": node.package_depth,
            "graph_depth": node.graph_depth,
            "functions_total": node.functions_total,
            "functions_public": node.functions_public,
            "stubs": node.stubs,
            "stub_ratio": node.stub_ratio,
            "completion_status": _get_completion_status(node.stub_ratio),
            "priority_score": _calculate_priority_score(node)
        }
        node_stats.append(stat)
    
    # 按优先级得分排序（分数高的优先实现）
    node_stats.sort(key=lambda x: x["priority_score"], reverse=True)
    
    return node_stats


def _calculate_depth_stub_stats(nodes: Dict[str, NodeInfo]) -> Dict[str, Any]:
    """计算按深度分组的stub统计"""
    package_depth_stats = {}
    graph_depth_stats = {}
    
    for node in nodes.values():
        # 按包深度统计
        pd = node.package_depth
        if pd not in package_depth_stats:
            package_depth_stats[pd] = {
                "depth": pd,
                "nodes": 0,
                "functions": 0,
                "stubs": 0,
                "stub_ratio": 0.0
            }
        package_depth_stats[pd]["nodes"] += 1
        package_depth_stats[pd]["functions"] += node.functions_public
        package_depth_stats[pd]["stubs"] += node.stubs
        
        # 按依赖图深度统计
        gd = node.graph_depth
        if gd not in graph_depth_stats:
            graph_depth_stats[gd] = {
                "depth": gd,
                "nodes": 0,
                "functions": 0,
                "stubs": 0,
                "stub_ratio": 0.0
            }
        graph_depth_stats[gd]["nodes"] += 1
        graph_depth_stats[gd]["functions"] += node.functions_public
        graph_depth_stats[gd]["stubs"] += node.stubs
    
    # 计算比率
    for stats in package_depth_stats.values():
        stats["stub_ratio"] = stats["stubs"] / max(1, stats["functions"])
    
    for stats in graph_depth_stats.values():
        stats["stub_ratio"] = stats["stubs"] / max(1, stats["functions"])
    
    return {
        "by_package_depth": list(package_depth_stats.values()),
        "by_graph_depth": list(graph_depth_stats.values())
    }


def _calculate_completion_distribution(nodes: Dict[str, NodeInfo]) -> Dict[str, Any]:
    """计算完整度分布"""
    distribution = {
        "0%": 0,        # 完全实现
        "1-25%": 0,     # 几乎完成
        "26-50%": 0,    # 部分完成
        "51-75%": 0,    # 大部分未完成
        "76-99%": 0,    # 几乎全是stub
        "100%": 0       # 完全未实现
    }
    
    for node in nodes.values():
        ratio = node.stub_ratio
        if ratio == 0.0:
            distribution["0%"] += 1
        elif ratio <= 0.25:
            distribution["1-25%"] += 1
        elif ratio <= 0.50:
            distribution["26-50%"] += 1
        elif ratio <= 0.75:
            distribution["51-75%"] += 1
        elif ratio < 1.0:
            distribution["76-99%"] += 1
        else:
            distribution["100%"] += 1
    
    return distribution


def _get_completion_status(stub_ratio: float) -> str:
    """获取完整度状态描述"""
    if stub_ratio == 0.0:
        return "完全实现"
    elif stub_ratio <= 0.25:
        return "几乎完成"
    elif stub_ratio <= 0.50:
        return "部分完成"
    elif stub_ratio <= 0.75:
        return "大部分未完成"
    elif stub_ratio < 1.0:
        return "几乎全是stub"
    else:
        return "完全未实现"


def _calculate_priority_score(node: NodeInfo) -> float:
    """
    计算节点的实现优先级得分
    
    优先级考虑因素：
    1. 依赖图深度低的优先（被更多模块依赖）
    2. stub比例高的优先（更需要实现）
    3. 公共函数多的优先（影响面大）
    """
    # 基础分数
    score = 0.0
    
    # 依赖深度因子 (深度越小，优先级越高)
    max_depth = 10  # 假设最大深度
    depth_factor = (max_depth - min(node.graph_depth, max_depth)) / max_depth
    score += depth_factor * 40
    
    # stub比例因子 (比例越高，优先级越高)
    stub_factor = node.stub_ratio
    score += stub_factor * 30
    
    # 函数数量因子 (函数越多，影响面越大)
    func_factor = min(node.functions_public / 10, 1.0)  # 归一化到0-1
    score += func_factor * 20
    
    # 包类型因子 (package比module优先级稍高)
    if node.node_type.value == "package":
        score += 10
    
    return score


def save_stub_report(
    stub_data: Dict[str, Any],
    project_data: ProjectData,
    output_dir: Path
) -> Path:
    """
    保存Stub完整度报告
    
    Args:
        stub_data: Stub分析数据
        project_data: 项目数据
        output_dir: 输出目录
        
    Returns:
        Path: stub_summary.json文件路径
    """
    # 创建输出目录
    stub_dir = output_dir / "stub_completeness"
    stub_dir.mkdir(parents=True, exist_ok=True)
    
    # 准备JSON数据
    json_data = _prepare_stub_json_data(stub_data, project_data)
    
    # 保存JSON文件
    json_path = stub_dir / "stub_summary.json"
    with json_path.open('w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    # 生成热力图
    svg_path = _generate_stub_heatmap(stub_data, project_data, stub_dir)
    
    print(f"✓ Stub报告保存到: {json_path}")
    if svg_path:
        print(f"✓ Stub热力图保存到: {svg_path}")
    
    return json_path


def _prepare_stub_json_data(stub_data: Dict[str, Any], project_data: ProjectData) -> Dict[str, Any]:
    """准备Stub分析的JSON输出数据"""
    
    # 转换stub函数为可序列化格式
    stub_functions_data = []
    for func in stub_data["stub_functions"]:
        func_data = {
            "module_name": func.module_name,
            "function_name": func.function_name,
            "full_name": func.full_name,
            "file_path": func.file_path,
            "line_number": func.line_number,
            "is_method": func.is_method,
            "class_name": func.class_name,
            "docstring": func.docstring
        }
        stub_functions_data.append(func_data)
    
    json_data = {
        "version": "1.0",
        "timestamp": project_data.timestamp,
        "project_root": project_data.project_root,
        "analysis_type": "stub_completeness",
        
        # 全局摘要
        "summary": stub_data["summary"],
        
        # 完整度分布
        "completion_distribution": stub_data["completion_distribution"],
        
        # 按节点统计
        "node_statistics": stub_data["node_stats"],
        
        # 按深度统计
        "depth_statistics": stub_data["depth_stats"],
        
        # 详细的stub函数列表
        "stub_functions": stub_functions_data,
        
        # 实现建议
        "recommendations": _generate_stub_recommendations(stub_data),
        
        # 趋势分析
        "trend_analysis": {
            "most_stubbed_nodes": [
                stat for stat in stub_data["node_stats"] 
                if stat["stub_ratio"] > 0.8
            ][:10],
            "high_priority_nodes": [
                stat for stat in stub_data["node_stats"] 
                if stat["priority_score"] > 50
            ][:10],
            "critical_dependencies": [
                stat for stat in stub_data["node_stats"] 
                if stat["graph_depth"] <= 1 and stat["stub_ratio"] > 0.5
            ]
        }
    }
    
    return json_data


def _generate_stub_recommendations(stub_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """生成Stub实现建议"""
    recommendations = []
    
    summary = stub_data["summary"]
    
    # 整体完整度建议
    if summary["global_stub_ratio"] > 0.7:
        recommendations.append({
            "type": "overall_completion",
            "priority": "critical",
            "title": "项目整体实现度较低",
            "description": f"项目有 {summary['global_stub_ratio']:.1%} 的函数尚未实现",
            "action": "建议优先实现核心功能和被依赖最多的模块"
        })
    elif summary["global_stub_ratio"] > 0.3:
        recommendations.append({
            "type": "overall_completion",
            "priority": "high", 
            "title": "项目进入实现阶段",
            "description": f"项目有 {summary['global_stub_ratio']:.1%} 的函数尚未实现",
            "action": "继续按优先级实现剩余功能"
        })
    
    # 高优先级节点建议
    high_priority = [node for node in stub_data["node_stats"] if node["priority_score"] > 60]
    if high_priority:
        recommendations.append({
            "type": "high_priority",
            "priority": "high",
            "title": "优先实现关键节点",
            "description": f"发现 {len(high_priority)} 个高优先级节点需要实现",
            "action": f"建议优先实现: {', '.join([n['name'] for n in high_priority[:3]])}"
        })
    
    # 深度0节点建议
    root_nodes = [node for node in stub_data["node_stats"] if node["graph_depth"] == 0]
    stubbed_roots = [node for node in root_nodes if node["stub_ratio"] > 0.5]
    if stubbed_roots:
        recommendations.append({
            "type": "root_dependencies",
            "priority": "critical",
            "title": "根节点实现度低",
            "description": f"有 {len(stubbed_roots)} 个根节点大部分功能未实现，这会影响整个项目",
            "action": f"立即实现根节点: {', '.join([n['name'] for n in stubbed_roots])}"
        })
    
    return recommendations


def _generate_stub_heatmap(
    stub_data: Dict[str, Any],
    project_data: ProjectData,
    output_dir: Path
) -> Path:
    """生成Stub热力图"""
    try:
        from .graphviz_render import render_stub_heatmap
        
        svg_path = output_dir / "stub_heatmap.svg"
        
        render_stub_heatmap(
            project_data.nodes,
            project_data.import_edges,
            project_data.child_edges,
            str(svg_path.with_suffix(''))  # 不带扩展名
        )
        
        return svg_path
    
    except ImportError as e:
        print(f"警告: 无法生成Stub热力图，缺少依赖: {e}")
        return None
    except Exception as e:
        print(f"警告: 生成Stub热力图时出错: {e}")
        return None