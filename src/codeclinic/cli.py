#!/usr/bin/env python3
"""
CodeClinic CLI tool - Python project dependency and stub analysis

This is the main entry point for the CodeClinic CLI tool.
It imports and uses the core library from src/codeclinic.
"""

import sys
import argparse
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, Tuple

from codeclinic.ast_scanner import scan_project_ast as scan_project
from codeclinic.graphviz_render import render_graph
from codeclinic.config import Config
from codeclinic.types import ModuleStats, Modules, GraphEdges
from codeclinic.json_output import save_json_output
from codeclinic.stub_report import save_stub_report


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="codeclinic",
        description="Diagnose your Python project: import graph + stub metrics + Graphviz rendering",
    )
    parser.add_argument("--path", required=True, help="Root path to scan (package folder or src root)")
    parser.add_argument("--out", default=None, help="Output directory for results (default: ./codeclinic_results)")
    parser.add_argument("--format", default=None, choices=["svg", "png", "pdf", "dot", "json"], help="Output format (svg/png/pdf/dot for visualization, json for data)")
    parser.add_argument("--aggregate", default=None, choices=["module", "package"], help="Aggregate nodes by module or package")
    parser.add_argument("--count-private", action="store_true", help="Count private (_prefixed) functions in metrics")

    args = parser.parse_args()

    # Load config and merge
    cfg = Config.from_files(os.getcwd())
    cfg.paths = [args.path] if args.path else cfg.paths
    if args.out:
        cfg.output = args.out
    if args.format:
        cfg.format = args.format
    if args.aggregate:
        cfg.aggregate = args.aggregate
    if args.count_private:
        cfg.count_private = True

    modules, edges, child_edges, stub_functions = scan_project(cfg.paths, cfg.include, cfg.exclude, cfg.count_private)

    if cfg.aggregate == "package":
        modules, edges = _aggregate_to_packages(modules, edges)
        # TODO: Also aggregate child_edges for package mode

    _print_summary(modules, edges, child_edges, root=args.path)

    # Create output directory
    output_dir = Path(cfg.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nOutput directory: {output_dir.absolute()}")

    # Always generate JSON output
    json_path = save_json_output(modules, edges, child_edges, args.path, output_dir / "analysis.json")
    print(f"✓ JSON analysis saved to: {json_path}")
    
    # Generate stub function report
    if stub_functions:
        stub_report_path = save_stub_report(stub_functions, edges, args.path, output_dir / "stub_report.json")
        print(f"✓ Stub function report saved to: {stub_report_path}")
    else:
        print("✓ No stub functions found in project")

    # Always generate visualization (unless explicitly JSON-only)
    graph_base = output_dir / "dependency_graph"
    dot_path, viz_path = render_graph(modules, edges, child_edges, str(graph_base), cfg.format)
    print(f"✓ DOT file saved to: {dot_path}")
    if viz_path:
        print(f"✓ Visualization saved to: {viz_path}")
    else:
        print("⚠ Graphviz 'dot' executable not found. Install Graphviz to render visualizations (DOT file still created).")
    
    print(f"\n📁 All results saved in: {output_dir.absolute()}")


def _aggregate_to_packages(modules, edges):
    # map module -> package (drop last segment)
    def pkg_of(mod: str) -> str:
        return mod if "." not in mod else mod.rsplit(".", 1)[0]

    pkg_stats: Modules = {}
    for m, st in modules.items():
        p = pkg_of(m)
        acc = pkg_stats.get(p)
        if not acc:
            acc = ModuleStats(name=p, file=st.file, functions_total=0, functions_public=0, stubs=0)
            pkg_stats[p] = acc
        acc.functions_total += st.functions_total
        acc.functions_public += st.functions_public
        acc.stubs += st.stubs

    pkg_edges: GraphEdges = set()
    for src, dst in edges:
        s, d = pkg_of(src), pkg_of(dst)
        if s != d:
            pkg_edges.add((s, d))
    return pkg_stats, pkg_edges


def _print_summary(modules, edges, child_edges, root: str) -> None:
    total_funcs = sum(m.functions_total for m in modules.values())
    total_public = sum(m.functions_public for m in modules.values())
    total_stubs = sum(m.stubs for m in modules.values())
    ratio = (total_stubs / total_public) if total_public else 0.0

    print("\n== CodeXray summary ==")
    print(f"root: {root}")
    print(f"nodes: {len(modules)}  edges: {len(edges)}  child edges: {len(child_edges)}")
    print(f"functions(public/total): {total_public}/{total_funcs}")
    print(f"stubs: {total_stubs}  ratio: {ratio:.1%}")

    # Adjacency list (brief)
    adj = defaultdict(set)
    for s, d in edges:
        adj[s].add(d)
    print("\nImport graph (adjacency):")
    for src in sorted(adj.keys()):
        targets = ", ".join(sorted(adj[src]))
        print(f" - {src} -> {targets}")
    
    # Child relationships
    if child_edges:
        child_adj = defaultdict(set)
        for parent, child in child_edges:
            child_adj[parent].add(child)
        print("\nParent-child relationships:")
        for parent in sorted(child_adj.keys()):
            children = ", ".join(sorted(child_adj[parent]))
            print(f" - {parent} contains {children}")


def cli_main():
    """Entry point for CLI tool when installed via pip."""
    main()


if __name__ == "__main__":
    main()