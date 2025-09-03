"""JSON output functionality for codeclinic analysis results."""

import json
from typing import Dict, Any, List
from pathlib import Path

from .types import ModuleStats, Modules, GraphEdges, ChildEdges


def serialize_to_json(modules: Modules, edges: GraphEdges, child_edges: ChildEdges, root_path: str) -> Dict[str, Any]:
    """Serialize analysis results to JSON-serializable dictionary."""
    
    # Convert modules to JSON-serializable format
    modules_data = []
    for module_name, stats in modules.items():
        modules_data.append({
            "name": stats.name,
            "file": stats.file,
            "functions_total": stats.functions_total,
            "functions_public": stats.functions_public,
            "stubs": stats.stubs,
            "stub_ratio": stats.stub_ratio
        })
    
    # Convert edges to list of tuples
    edges_data = [{"from": src, "to": dst} for src, dst in sorted(edges)]
    
    # Convert child edges to list of tuples
    child_edges_data = [{"parent": parent, "child": child} for parent, child in sorted(child_edges)]
    
    # Calculate summary statistics
    total_funcs = sum(m.functions_total for m in modules.values())
    total_public = sum(m.functions_public for m in modules.values())
    total_stubs = sum(m.stubs for m in modules.values())
    overall_ratio = (total_stubs / total_public) if total_public else 0.0
    
    return {
        "metadata": {
            "root_path": root_path,
            "total_modules": len(modules),
            "total_import_edges": len(edges),
            "total_child_edges": len(child_edges),
        },
        "summary": {
            "functions_total": total_funcs,
            "functions_public": total_public,
            "stubs_total": total_stubs,
            "overall_stub_ratio": overall_ratio
        },
        "modules": modules_data,
        "import_dependencies": edges_data,
        "parent_child_relationships": child_edges_data
    }


def save_json_output(modules: Modules, edges: GraphEdges, child_edges: ChildEdges, 
                     root_path: str, output_path: str) -> str:
    """Save analysis results as JSON file."""
    data = serialize_to_json(modules, edges, child_edges, root_path)
    
    # Ensure output path has .json extension
    json_path = Path(output_path)
    if json_path.suffix != '.json':
        json_path = json_path.with_suffix('.json')
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return str(json_path)