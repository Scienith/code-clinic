from __future__ import annotations
from graphviz import Digraph
from graphviz.backend import ExecutableNotFound
from typing import Dict, Iterable, Tuple, Set
from .types import Modules, GraphEdges, ChildEdges
from .node_types import NodeInfo, NodeType


def _color_for_ratio(r: float) -> str:
    # simple traffic light
    if r <= 0.05:
        return "#4CAF50"  # green
    if r <= 0.30:
        return "#FFC107"  # amber
    return "#F44336"      # red


def _get_short_name(module_name: str) -> str:
    """Get a shortened display name for a module."""
    parts = module_name.split('.')
    
    if len(parts) == 1:
        # Top level: "example_project" -> "example_project"
        return parts[0]
    elif len(parts) == 2:
        # Second level: "example_project.A" -> "A"
        return parts[1]
    else:
        # Deeper levels: "example_project.A.A1.A11" -> "A1.A11"
        # Show last two parts to maintain context
        return '.'.join(parts[-2:])
        # Alternative: show only the last part
        # return parts[-1]


def render_graph(modules: Modules, edges: GraphEdges, child_edges: ChildEdges, output_base: str, fmt: str = "svg") -> Tuple[str, str]:
    dot = Digraph(
        "codeclinic",
        graph_attr={"rankdir": "TB", "splines": "spline"},
        node_attr={"shape": "box", "style": "rounded,filled", "fontname": "Helvetica"},
        edge_attr={"arrowhead": "vee"},
    )

    for name, st in modules.items():
        ratio = st.stub_ratio
        pct = int(round(ratio * 100))
        # Use short name for display (last part of module path)
        display_name = _get_short_name(name)
        label = f"{display_name}\nstub {st.stubs}/{max(1, st.functions_public)} ({pct}%)"
        dot.node(name, label=label, fillcolor=_color_for_ratio(ratio))

    # Determine which edges have both import and child relationships
    both_relationships = set()
    import_only = set()
    child_only = set()
    
    # Find overlapping relationships
    for src, dst in edges:
        if (src, dst) in child_edges:
            both_relationships.add((src, dst))
        else:
            import_only.add((src, dst))
    
    for parent, child in child_edges:
        if (parent, child) not in edges:
            child_only.add((parent, child))
    
    # Add edges with appropriate styling
    # Both import and child: solid black line
    for src, dst in sorted(both_relationships):
        dot.edge(src, dst, color="black", style="solid")
    
    # Import only: dashed black line  
    for src, dst in sorted(import_only):
        dot.edge(src, dst, color="black", style="dashed")
    
    # Child only: dashed black line
    for parent, child in sorted(child_only):
        dot.edge(parent, child, color="black", style="dashed")

    dot_path = f"{output_base}.dot"
    svg_path = f"{output_base}.{fmt}"
    dot.save(dot_path)

    try:
        dot.render(output_base, format=fmt, cleanup=True)
    except ExecutableNotFound:
        # Only DOT written; caller should inform user
        svg_path = ""
    return dot_path, svg_path


def render_violations_graph(
    nodes: Dict[str, NodeInfo], 
    legal_edges: Set[Tuple[str, str]], 
    violation_edges: Set[Tuple[str, str]], 
    output_base: str, 
    fmt: str = "svg"
) -> Tuple[str, str]:
    """
    渲染违规检测图，用红色表示违规边，绿色表示合法边
    """
    dot = Digraph(
        "violations",
        graph_attr={"rankdir": "TB", "splines": "spline", "label": "Import Violations Graph", "labelloc": "t"},
        node_attr={"shape": "box", "style": "rounded,filled", "fontname": "Helvetica"},
        edge_attr={"arrowhead": "vee"},
    )

    # 添加节点，根据节点类型使用不同样式
    for name, node in nodes.items():
        display_name = _get_short_name(name)
        
        # 根据节点类型设置样式
        if node.node_type == NodeType.PACKAGE:
            node_color = "#E3F2FD"  # 浅蓝色
            shape = "box"
            style = "bold,filled"
        else:  # MODULE
            node_color = "#F3E5F5"  # 浅紫色
            shape = "box"
            style = "rounded,filled"
        
        label = f"{display_name}\n{node.node_type.value}"
        dot.node(name, label=label, fillcolor=node_color, shape=shape, style=style)

    # 添加合法边（绿色）
    for src, dst in sorted(legal_edges):
        if src in nodes and dst in nodes:
            dot.edge(src, dst, color="#4CAF50", style="solid", penwidth="2")

    # 添加违规边（红色）
    for src, dst in sorted(violation_edges):
        if src in nodes and dst in nodes:
            dot.edge(src, dst, color="#F44336", style="solid", penwidth="3")

    dot_path = f"{output_base}.dot"
    svg_path = f"{output_base}.{fmt}"
    dot.save(dot_path)

    try:
        dot.render(output_base, format=fmt, cleanup=True)
    except ExecutableNotFound:
        svg_path = ""
    
    return dot_path, svg_path


def render_stub_heatmap(
    nodes: Dict[str, NodeInfo], 
    edges: GraphEdges, 
    child_edges: ChildEdges, 
    output_base: str, 
    fmt: str = "svg"
) -> Tuple[str, str]:
    """
    渲染Stub热力图，节点颜色从白色（0% stub）到红色（100% stub）渐变
    """
    dot = Digraph(
        "stub_heatmap",
        graph_attr={"rankdir": "TB", "splines": "spline", "label": "Stub Completeness Heatmap", "labelloc": "t"},
        node_attr={"shape": "box", "style": "rounded,filled", "fontname": "Helvetica"},
        edge_attr={"arrowhead": "vee", "color": "#999999"},
    )

    # 添加节点，使用stub比例决定颜色
    for name, node in nodes.items():
        display_name = _get_short_name(name)
        ratio = node.stub_ratio
        pct = int(round(ratio * 100))
        
        # 计算从白色到红色的渐变
        # 白色 #FFFFFF (100% 实现) 到 红色 #FF0000 (100% stub)
        color = _stub_ratio_to_color(ratio)
        
        # 根据节点类型调整显示
        if node.node_type == NodeType.PACKAGE:
            shape = "box"
            style = "bold,filled"
            type_indicator = "📦"  # package emoji
        else:  # MODULE
            shape = "box"
            style = "rounded,filled"
            type_indicator = "📄"  # file emoji
        
        # 创建标签
        label = f"{type_indicator} {display_name}\n{node.stubs}/{node.functions_public} stub ({pct}%)"
        
        # 如果完全未实现，使用特殊标记
        if ratio >= 1.0:
            label += "\n⚠️ 未实现"
        elif ratio == 0.0:
            label += "\n✅ 已实现"
        
        dot.node(name, label=label, fillcolor=color, shape=shape, style=style)

    # 添加边（较淡的颜色，不干扰热力图）
    for src, dst in sorted(edges):
        if src in nodes and dst in nodes:
            dot.edge(src, dst, color="#CCCCCC", style="solid", penwidth="1")
    
    # 添加包含关系边（虚线）
    for parent, child in sorted(child_edges):
        if parent in nodes and child in nodes and (parent, child) not in edges:
            dot.edge(parent, child, color="#DDDDDD", style="dashed", penwidth="1")

    dot_path = f"{output_base}.dot"
    svg_path = f"{output_base}.{fmt}"
    dot.save(dot_path)

    try:
        dot.render(output_base, format=fmt, cleanup=True)
    except ExecutableNotFound:
        svg_path = ""
    
    return dot_path, svg_path


def _stub_ratio_to_color(ratio: float) -> str:
    """
    将stub比例转换为颜色，从白色（0%）到红色（100%）的渐变
    
    Args:
        ratio: stub比例 (0.0 到 1.0)
        
    Returns:
        str: 十六进制颜色值
    """
    # 确保ratio在0-1范围内
    ratio = max(0.0, min(1.0, ratio))
    
    # 从白色 RGB(255,255,255) 到红色 RGB(255,0,0)
    # 保持红色通道为255，绿色和蓝色通道根据ratio递减
    red = 255
    green = int(255 * (1 - ratio))
    blue = int(255 * (1 - ratio))
    
    # 转换为十六进制
    return f"#{red:02x}{green:02x}{blue:02x}"
