"""
CodeXray public API - Simple facade for project analysis.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

from .ast_scanner import scan_project_ast as scan_project
from .graphviz_render import render_graph
from .types import ModuleStats


def analyze_project(
    path: str,
    *,
    output: Optional[str] = None,
    format: str = "svg",
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    count_private: bool = False
) -> Dict[str, Any]:
    """
    Analyze a Python project for dependencies and stub metrics.
    
    Args:
        path: Root path of the project to analyze
        output: Output file base name (without extension)
        format: Output format (svg, png, pdf, dot)
        include: File patterns to include (default: ["**/*.py"])
        exclude: File patterns to exclude (default: standard excludes)
        count_private: Whether to count private functions in metrics
    
    Returns:
        Dictionary containing:
        - modules: Dict[str, ModuleStats] - Module statistics
        - summary: Dict with overall project statistics
        - files: Dict with generated file paths (if output specified)
    """
    # Use defaults if not specified
    if include is None:
        include = ["**/*.py"]
    if exclude is None:
        exclude = [
            "**/tests/**", "**/.venv/**", "**/venv/**", 
            "**/__pycache__/**", "**/build/**", "**/dist/**"
        ]
    
    # Scan the project
    modules, edges, child_edges = scan_project([path], include, exclude, count_private)
    
    # Calculate summary statistics
    total_funcs = sum(m.functions_total for m in modules.values())
    total_public = sum(m.functions_public for m in modules.values())
    total_stubs = sum(m.stubs for m in modules.values())
    stub_ratio = (total_stubs / total_public) if total_public else 0.0
    
    result = {
        'modules': modules,
        'summary': {
            'total_modules': len(modules),
            'total_functions': total_funcs,
            'public_functions': total_public,
            'stub_functions': total_stubs,
            'stub_ratio': stub_ratio,
            'import_edges': len(edges),
            'child_edges': len(child_edges)
        }
    }
    
    # Generate visualization if output specified
    if output:
        dot_path, viz_path = render_graph(modules, edges, child_edges, output, format)
        result['files'] = {
            'dot_file': dot_path,
            'visualization': viz_path if viz_path else None
        }
    
    return result


