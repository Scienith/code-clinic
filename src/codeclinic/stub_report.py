"""Generate stub function reports."""

import json
from pathlib import Path
from typing import Dict, Any
from .types import StubFunctions, GraphEdges
from .graph_analysis import add_graph_depths_to_stubs


def generate_stub_report(stub_functions: StubFunctions, edges: GraphEdges, root_path: str) -> Dict[str, Any]:
    """Generate a comprehensive report of all @stub decorated functions."""
    
    # Add graph depth information to stub functions
    stub_details = add_graph_depths_to_stubs(stub_functions, edges)
    
    # Calculate summary statistics
    total_stubs = len(stub_details)
    modules_with_stubs = len(set(stub["module_name"] for stub in stub_details))
    method_stubs = sum(1 for stub in stub_details if stub["is_method"])
    function_stubs = total_stubs - method_stubs
    
    # Group by depth for analysis
    depth_groups = {}
    for stub in stub_details:
        depth = stub["graph_depth"]
        if depth not in depth_groups:
            depth_groups[depth] = []
        depth_groups[depth].append(stub)
    
    # Calculate depth statistics
    depths = [stub["graph_depth"] for stub in stub_details] if stub_details else [0]
    max_depth = max(depths) if depths else 0
    avg_depth = sum(depths) / len(depths) if depths else 0
    
    return {
        "metadata": {
            "root_path": root_path,
            "total_stub_functions": total_stubs,
            "modules_with_stubs": modules_with_stubs,
            "function_stubs": function_stubs,
            "method_stubs": method_stubs
        },
        "depth_analysis": {
            "max_depth": max_depth,
            "average_depth": round(avg_depth, 2),
            "depth_distribution": {
                str(depth): len(stubs) 
                for depth, stubs in sorted(depth_groups.items())
            }
        },
        "stub_functions": stub_details
    }


def save_stub_report(stub_functions: StubFunctions, edges: GraphEdges, root_path: str, output_path: str) -> str:
    """Save stub function report as JSON file."""
    report = generate_stub_report(stub_functions, edges, root_path)
    
    # Ensure output path has .json extension
    json_path = Path(output_path)
    if json_path.suffix != '.json':
        json_path = json_path.with_suffix('.json')
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    return str(json_path)