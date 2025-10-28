from __future__ import annotations
from graphviz import Digraph
from graphviz.backend import ExecutableNotFound
from typing import Dict, Iterable, Tuple, Set
from .types import Modules, GraphEdges, ChildEdges
from .node_types import NodeInfo, NodeType


def _aggregate_pkg_ratio_generic(name: str, modules: Modules) -> tuple[int, int, float]:
    node = modules[name]
    if node.node_type != NodeType.PACKAGE:
        return int(node.stubs), int(node.functions_total), float(node.stub_ratio)
    stubs = 0
    total = 0
    stack = [name]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in modules:
            nd = modules[cur]
            stubs += int(nd.stubs)
            total += int(nd.functions_total)
            for ch in nd.children:
                stack.append(ch)
    ratio = (stubs / max(1, total)) if total else 0.0
    return stubs, total, ratio


def _color_for_ratio(r: float) -> str:
    # simple traffic light
    if r <= 0.05:
        return "#4CAF50"  # green
    if r <= 0.30:
        return "#FFC107"  # amber
    return "#F44336"      # red


def _get_short_name(module_name: str) -> str:
    """Get a shortened display name for a module - only last part."""
    if not module_name:
        return "root"
    
    parts = module_name.split('.')
    
    # Always show only the last part
    return parts[-1]


def render_graph(modules: Modules, edges: GraphEdges, child_edges: ChildEdges, output_base: str, fmt: str = "svg") -> Tuple[str, str]:
    dot = Digraph(
        "codeclinic",
        graph_attr={"rankdir": "TB", "splines": "spline"},
        node_attr={"shape": "box", "style": "rounded,filled", "fontname": "Helvetica"},
        edge_attr={"arrowhead": "vee"},
    )

    for name, st in modules.items():
        # Use aggregated ratio/denominator for packages; direct for modules
        stubs, total, ratio = _aggregate_pkg_ratio_generic(name, modules)
        pct = int(round(ratio * 100))
        display_name = _get_short_name(name)
        label = f"{display_name}\nstub {stubs}/{max(1, total)} ({pct}%)"
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
    fmt: str = "svg",
    child_edges: Set[Tuple[str, str]] | None = None,
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

    # 添加节点（统一样式：shape=box, style=rounded,filled, 填充统一白色）
    for name, node in nodes.items():
        display_name = _get_short_name(name)
        icon = "\U0001F4E6" if node.node_type == NodeType.PACKAGE else "\U0001F4C4"  # 📦 or 📄
        label = f"{icon} {display_name}\n{node.node_type.value}"
        dot.node(name, label=label, fillcolor="#FFFFFF", shape="box", style="rounded,filled")

    # 不再绘制“文件夹/包含”关系，只展示导入依赖关系

    # 再画合法导入边（绿色）
    for src, dst in sorted(legal_edges):
        if src in nodes and dst in nodes:
            dot.edge(src, dst, color="#4CAF50", style="solid", penwidth="2")

    # 最后画违规导入边（红色，加粗置顶）
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


def render_violations_tree_graph(
    nodes: Dict[str, NodeInfo],
    legal_edges: Set[Tuple[str, str]],
    violation_edges: Set[Tuple[str, str]],
    output_base: str,
    fmt: str = "svg",
    child_edges: Set[Tuple[str, str]] | None = None,
) -> Tuple[str, str]:
    """
    渲染基于“包+模块”的树形依赖图：
    - 仅展示导入依赖关系；不再绘制文件夹父子（包含）关系或虚拟根节点
    - 节点：📦=package，📄=module
    - 叠加依赖连线：绿色=合法，红色=违规（保持不影响布局 constraint=false）
    """
    dot = Digraph(
        "violations_tree",
        graph_attr={"rankdir": "TB", "splines": "spline", "label": "Package/Module Tree + Import Overlay", "labelloc": "t"},
        node_attr={"shape": "box", "style": "rounded,filled", "fontname": "Helvetica"},
        edge_attr={"arrowhead": "vee"},
    )

    # 添加所有节点（包+模块）
    for name, node in nodes.items():
        display_name = _get_short_name(name)
        icon = "\U0001F4E6" if node.node_type == NodeType.PACKAGE else "\U0001F4C4"
        kind = "package" if node.node_type == NodeType.PACKAGE else "module"
        label = f"{icon} {display_name}\n{kind}"
        dot.node(name, label=label, fillcolor="#FFFFFF", shape="box", style="rounded,filled")

    # 不绘制任何“包含”关系，仅叠加导入依赖边

    # 叠加依赖边：模块/包之间的直接依赖（不聚合，保留粒度）
    for src, dst in sorted(legal_edges):
        if src in nodes and dst in nodes:
            dot.edge(src, dst, color="#4CAF50", style="solid", penwidth="2", constraint="false")
    for src, dst in sorted(violation_edges):
        if src in nodes and dst in nodes:
            dot.edge(src, dst, color="#F44336", style="solid", penwidth="3", constraint="false")

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
    fmt: str = "svg",
    test_status: Dict[str, str] | None = None,
    test_pass_counts: Dict[str, Tuple[int, int]] | None = None,
) -> Tuple[str, str]:
    """
    渲染Stub热力图，节点颜色从白色（0% stub）到红色（100% stub）渐变
    """
    dot = Digraph(
        "stub_heatmap",
        graph_attr={"rankdir": "TB", "splines": "spline", "label": "Implementation Completeness Heatmap\\nProgress: 🟩 Implemented  ⬜ Stub", "labelloc": "t"},
        node_attr={"shape": "box", "style": "rounded,filled", "fontname": "Helvetica"},
        edge_attr={"arrowhead": "vee", "color": "#999999"},
    )

    # 添加节点，使用统一样式，边框可叠加测试通过/失败状态
    for name, node in nodes.items():
        display_name = _get_short_name(name)
        # 统一以“stub/total”为标签口径；package 采用聚合，module 直接取节点数据
        if node.node_type == NodeType.PACKAGE:
            stubs, total, ratio = _aggregate_pkg_ratio_generic(name, nodes)
        else:
            stubs = int(node.stubs)
            total = int(node.functions_total)
            ratio = (stubs / float(total)) if total > 0 else None
        pct_str = f"{int(round(ratio * 100))}%" if isinstance(ratio, float) else "N/A"
        
        # 使用统一的白色背景
        color = "#FFFFFF"
        border_color = None
        if test_status is not None and node.node_type == NodeType.MODULE:
            status = test_status.get(name)
            if status == "green":
                border_color = "#2e7d32"  # green
            else:
                border_color = "#c62828"  # red
        
        # 统一节点形状与样式；保留类型图标以便识别
        shape = "box"
        style = "rounded,filled"
        type_indicator = "📦" if node.node_type == NodeType.PACKAGE else "📄"
        
        # 创建进度条使用HTML表格渐变
        progress_bar = _create_html_progress_bar(ratio)

        # Tests pass/total line for modules (do not change fillcolor)
        tests_line = ""
        if node.node_type == NodeType.MODULE and test_pass_counts is not None:
            t_passed, t_total = test_pass_counts.get(name, (None, None)) if test_pass_counts else (None, None)
            if isinstance(t_passed, int) and isinstance(t_total, int):
                test_color = "#2e7d32" if t_total > 0 and t_passed == t_total else "#c62828"
                if t_total == 0:
                    test_color = "#c62828"
                tests_line = f"<TR><TD>Tests: <FONT COLOR=\"{test_color}\">{t_passed}/{t_total}</FONT></TD></TR>"

        # 进度条以完成度（1 - stub_ratio）展示；ratio=None 时在进度条内处理成灰条
        
        # 创建HTML标签包含进度条
        label = f'''<
        <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0">
            <TR><TD>{type_indicator} {display_name}</TD></TR>
            <TR><TD>stub {stubs}/{total} ({pct_str})</TD></TR>
            {tests_line}
            <TR><TD>{progress_bar}</TD></TR>
        </TABLE>
        >'''
        
        attrs = {"label": label, "fillcolor": color, "shape": shape, "style": style}
        if border_color:
            attrs["color"] = border_color
            attrs["penwidth"] = "2"
        dot.node(name, **attrs)

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


from typing import Optional


def _create_html_progress_bar(ratio: Optional[float], width: int = 120) -> str:
    """
    创建HTML表格形式的进度条，简洁显示
    
    Args:
        ratio: stub比例 (0.0 到 1.0)
        width: 进度条像素宽度
        
    Returns:
        str: HTML表格进度条
    """
    # 计算实现比例（1 - stub_ratio）；当 total==0 → ratio=None，用纯灰色条表示 N/A
    if ratio is None:
        return f'''<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" STYLE="ROUNDED">\n            <TR>\n                <TD WIDTH="{width}" HEIGHT="14" BGCOLOR="lightgray"></TD>\n            </TR>\n        </TABLE>'''

    completion_ratio = 1.0 - float(ratio)
    completion_pct = int(round(completion_ratio * 100))
    
    # 计算进度条填充宽度
    filled_width = int(width * completion_ratio)
    empty_width = width - filled_width
    
    if completion_ratio >= 1.0:
        # 100% 完成 - 全绿色，只在第一个节点显示百分比
        progress_bar = f'''<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" STYLE="ROUNDED">
            <TR>
                <TD WIDTH="{width}" HEIGHT="14" BGCOLOR="green"></TD>
            </TR>
        </TABLE>'''
    else:
        # 部分完成 - 绿色+灰色分段，只在第一个遇到的部分完成节点显示百分比
        if filled_width > 0 and empty_width > 0:
            progress_bar = f'''<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" STYLE="ROUNDED">
                <TR>
                    <TD WIDTH="{filled_width}" HEIGHT="14" BGCOLOR="green"></TD>
                    <TD WIDTH="{empty_width}" HEIGHT="14" BGCOLOR="lightgray"></TD>
                </TR>
            </TABLE>'''
        elif filled_width <= 0:
            # 几乎没有完成
            progress_bar = f'''<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" STYLE="ROUNDED">
                <TR>
                    <TD WIDTH="{width}" HEIGHT="14" BGCOLOR="lightgray"></TD>
                </TR>
            </TABLE>'''
        else:
            # 几乎全部完成
            progress_bar = f'''<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" STYLE="ROUNDED">
                <TR>
                    <TD WIDTH="{width}" HEIGHT="14" BGCOLOR="green"></TD>
                </TR>
            </TABLE>'''
    
    return progress_bar


def _create_progress_bar(ratio: float, width: int = 10) -> str:
    """
    创建统一的进度条，用简洁的符号体现完成度
    
    Args:
        ratio: stub比例 (0.0 到 1.0)
        width: 进度条宽度
        
    Returns:
        str: 进度条字符串
    """
    # 计算实现比例（1 - stub_ratio）
    completion_ratio = 1.0 - ratio
    completion_pct = int(round(completion_ratio * 100))
    
    # 计算进度条填充长度
    filled_length = int(width * completion_ratio)
    empty_length = width - filled_length
    
    # 尝试不同的进度条样式
    if completion_ratio >= 1.0:
        # 100% 完成 - 全绿色实心条
        bar = "█" * width
        bar_display = f"🟢[{bar}] {completion_pct}%"
    else:
        # 部分完成 - 实心部分 + 空心部分
        filled = "█" * filled_length if filled_length > 0 else ""
        empty = "░" * empty_length if empty_length > 0 else ""
        bar_display = f"🟡[{filled}{empty}] {completion_pct}%"
    
    return bar_display


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
