from __future__ import annotations
from graphviz import Digraph
from graphviz.backend import ExecutableNotFound
from typing import Dict, Iterable, Tuple
from .types import Modules, GraphEdges, ChildEdges


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
