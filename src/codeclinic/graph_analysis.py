"""Graph analysis utilities for dependency analysis."""

from typing import Dict, Set, List
from collections import defaultdict, deque
from .types import GraphEdges, StubFunction, StubFunctions


def calculate_module_depths(edges: GraphEdges) -> Dict[str, int]:
    """
    Calculate the maximum depth of each module in the dependency graph.
    
    Depth is defined as the longest path from any root node (nodes with no incoming edges)
    to the current node.
    """
    # Build adjacency lists
    adj: Dict[str, List[str]] = defaultdict(list)  # from -> [to, ...]
    reverse_adj: Dict[str, List[str]] = defaultdict(list)  # to -> [from, ...]
    all_nodes: Set[str] = set()
    
    for src, dst in edges:
        adj[src].append(dst)
        reverse_adj[dst].append(src)
        all_nodes.add(src)
        all_nodes.add(dst)
    
    # Find root nodes (no incoming edges)
    root_nodes = [node for node in all_nodes if not reverse_adj[node]]
    
    # If no root nodes (circular dependencies), pick arbitrary starting points
    if not root_nodes:
        root_nodes = list(all_nodes)[:1]  # Just pick one node
    
    # Calculate maximum depth using BFS from all root nodes
    depths: Dict[str, int] = {}
    
    for root in root_nodes:
        # BFS to calculate depths from this root
        queue = deque([(root, 0)])
        visited: Set[str] = set()
        
        while queue:
            node, depth = queue.popleft()
            
            if node in visited:
                continue
            visited.add(node)
            
            # Update depth if this path is longer
            if node not in depths or depth > depths[node]:
                depths[node] = depth
            
            # Add neighbors to queue
            for neighbor in adj[node]:
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))
    
    # Ensure all nodes have a depth (isolated nodes get depth 0)
    for node in all_nodes:
        if node not in depths:
            depths[node] = 0
    
    return depths


def add_graph_depths_to_stubs(stub_functions: StubFunctions, edges: GraphEdges) -> List[Dict]:
    """
    Add graph depth information to stub functions and return as list of dictionaries.
    """
    module_depths = calculate_module_depths(edges)
    
    result = []
    for stub_func in stub_functions:
        depth = module_depths.get(stub_func.module_name, 0)
        
        stub_dict = {
            "module_name": stub_func.module_name,
            "file_path": stub_func.file_path,
            "function_name": stub_func.function_name,
            "full_name": stub_func.full_name,
            "docstring": stub_func.docstring,
            "is_method": stub_func.is_method,
            "class_name": stub_func.class_name,
            "graph_depth": depth
        }
        result.append(stub_dict)
    
    # Sort by graph depth (deepest first), then by module name, then by function name
    result.sort(key=lambda x: (-x["graph_depth"], x["module_name"], x["function_name"]))
    
    return result