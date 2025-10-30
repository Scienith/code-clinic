"""
Tree visualization for code structure with LOC per module (excluding docstrings).

Outputs a containment-only Graphviz tree similar in style to the stub heatmap.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import ast

from .node_types import NodeInfo, NodeType, ProjectData


def _docstring_spans(tree: ast.AST) -> List[Tuple[int, int]]:
    """Collect (lineno, end_lineno) spans for module/class/function docstrings.

    We treat a docstring as the first statement of a module, class, or function
    if it is a literal string expression. Requires Python 3.8+ for end_lineno.
    """
    spans: List[Tuple[int, int]] = []

    def record_if_docstring(body: List[ast.stmt]) -> None:
        if not body:
            return
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(getattr(first, "value", None), ast.Constant)
            and isinstance(getattr(first, "value", None).value, str)
        ):
            start = getattr(first, "lineno", None)
            end = getattr(first, "end_lineno", None)
            if isinstance(start, int):
                if not isinstance(end, int):
                    end = start
                spans.append((start, end))

    class V(ast.NodeVisitor):
        def visit_Module(self, node: ast.Module) -> None:  # type: ignore[override]
            record_if_docstring(getattr(node, "body", []) or [])
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # type: ignore[override]
            record_if_docstring(node.body)
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # type: ignore[override]
            record_if_docstring(node.body)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # type: ignore[override]
            record_if_docstring(node.body)
            self.generic_visit(node)

    V().visit(tree)
    return spans


def _loc_excluding_docstrings(file_path: str) -> int:
    """Compute physical LOC excluding docstring spans.

    We do not remove comments or blank lines unless they are part of a docstring.
    """
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            return 0

    total_lines = len(text.splitlines())

    try:
        tree = ast.parse(text, filename=file_path)
    except Exception:
        return total_lines

    spans = _docstring_spans(tree)
    if not spans:
        return total_lines

    # Build set of docstring line numbers (inclusive ranges)
    doc_lines: Set[int] = set()
    for start, end in spans:
        if isinstance(start, int) and isinstance(end, int):
            for ln in range(max(1, start), max(start, end) + 1):
                doc_lines.add(ln)

    # Count lines not part of docstrings
    non_doc = 0
    for i, _ in enumerate(text.splitlines(), start=1):
        if i not in doc_lines:
            non_doc += 1
    return non_doc


def _build_loc_map(nodes: Dict[str, NodeInfo]) -> Dict[str, int]:
    """Build LOC map for module and package nodes.

    For modules: count LOC excluding docstrings.
    For packages: count LOC of its __init__.py (if any); aggregation for display is done in renderer.
    """
    loc_map: Dict[str, int] = {}
    for name, node in nodes.items():
        try:
            loc_map[name] = _loc_excluding_docstrings(node.file_path)
        except Exception:
            loc_map[name] = 0
    return loc_map


def generate_tree_loc(project_data: ProjectData, output_dir: Path) -> Optional[Path]:
    """Generate LOC tree visualization under output_dir/tree/loc_tree.svg.

    Returns the SVG path if generation succeeds, otherwise None.
    """
    try:
        from .graphviz_render import render_tree_loc
    except Exception as e:
        # Graphviz not available
        _ = e
        return None

    tree_dir = Path(output_dir) / "tree"
    tree_dir.mkdir(parents=True, exist_ok=True)
    svg_base = tree_dir / "loc_tree"

    loc_map = _build_loc_map(project_data.nodes)
    try:
        _dot, svg = render_tree_loc(
            project_data.nodes, project_data.child_edges, loc_map, str(svg_base)
        )
        return Path(svg) if svg else None
    except Exception:
        return None
