#!/usr/bin/env python3
"""
CodeClinic CLI tool - Python project dependency and stub analysis

This is the main entry point for the CodeClinic CLI tool.
It imports and uses the core library from src/codeclinic.
"""

import sys
import argparse
import os
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Tuple

# 新版导入
from codeclinic.data_collector import collect_project_data
from codeclinic.config_loader import load_config, ExtendedConfig
from codeclinic.violations_analysis import analyze_violations, save_violations_report
from codeclinic.stub_analysis import analyze_stub_completeness, save_stub_report
from codeclinic.graphviz_render import render_graph

# 保持向后兼容的导入
from codeclinic.ast_scanner import scan_project_ast as scan_project
from codeclinic.config import Config
from codeclinic.types import ModuleStats, Modules, GraphEdges
from codeclinic.json_output import save_json_output
from codeclinic.stub_report import save_stub_report as save_legacy_stub_report


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="codeclinic",
        description="Diagnose your Python project: import graph + stub metrics + import rules compliance",
    )
    
    # 配置管理命令
    parser.add_argument("--init", action="store_true", help="Generate default configuration file (codeclinic.yaml)")
    parser.add_argument("--show-config", action="store_true", help="Show current effective configuration")
    
    # 分析参数
    parser.add_argument("--path", help="Root path to scan (package folder or src root)")
    parser.add_argument("--out", default=None, help="Output directory for results (default: ./codeclinic_results)")
    parser.add_argument("--format", default=None, choices=["svg", "png", "pdf", "dot", "json"], help="Output format (svg/png/pdf/dot for visualization, json for data)")
    parser.add_argument("--aggregate", default=None, choices=["module", "package"], help="Aggregate nodes by module or package")
    parser.add_argument("--count-private", action="store_true", help="Count private (_prefixed) functions in metrics")
    parser.add_argument("--legacy", action="store_true", help="Use legacy analysis mode (backward compatibility)")

    args = parser.parse_args()

    # 处理配置管理命令
    if args.init:
        from codeclinic.config_init import init_config
        init_config()
        return
    
    if args.show_config:
        from codeclinic.config_init import show_config
        show_config()
        return
    
    # 如果没有指定 --path，要求用户提供
    if not args.path:
        print("❌ 错误: 必须指定 --path 参数")
        print("💡 提示:")
        print("  • 分析项目: codeclinic --path /path/to/project")
        print("  • 生成配置: codeclinic --init")
        print("  • 查看配置: codeclinic --show-config")
        sys.exit(1)

    # 如果使用legacy模式，调用旧版本函数
    if args.legacy:
        _run_legacy_analysis(args)
        return
    
    # === 新版分析流程 ===
    
    # 1. 加载配置
    try:
        config = load_config()
        white_list_count = len(config.import_rules.white_list) if config.import_rules.white_list else 0
        print(f"已加载配置: {white_list_count} 个白名单项")
    except Exception as e:
        print(f"警告: 配置加载失败，使用默认配置: {e}")
        config = ExtendedConfig()
    
    # 2. 合并命令行参数
    if args.path:
        config.paths = [args.path]
    if args.out:
        config.output = args.out
    if args.format:
        config.format = args.format
    if args.aggregate:
        config.aggregate = args.aggregate
    if args.count_private:
        config.count_private = True
    
    print(f"\n🔍 开始分析项目: {config.paths}")
    print(f"📁 输出目录: {config.output}")
    
    # 3. 收集项目数据
    project_data = collect_project_data(
        paths=config.paths,
        include=config.include,
        exclude=config.exclude,
        count_private=config.count_private,
        config={
            'import_rules': config.import_rules,
            'aggregate': config.aggregate,
            'format': config.format
        }
    )
    
    # 处理聚合模式
    if config.aggregate == "package":
        project_data.nodes, project_data.import_edges = _aggregate_to_packages_new(
            project_data.nodes, project_data.import_edges
        )
    
    # 4. 打印摘要
    _print_project_summary(project_data, root=args.path)
    
    # 5. 创建输出目录
    output_dir = Path(config.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📂 输出目录: {output_dir.absolute()}")
    
    # 6. 保存完整项目数据
    data_json_path = output_dir / "data.json"
    _save_project_data(project_data, data_json_path)
    print(f"✓ 项目数据保存到: {data_json_path}")
    
    # 7. 并行进行专项分析
    print(f"\n🔬 开始专项分析...")
    
    # 7.1 导入违规分析
    violations_data = analyze_violations(project_data)
    violations_json = save_violations_report(violations_data, project_data, output_dir)
    
    # 7.2 Stub完整度分析
    stub_data = analyze_stub_completeness(project_data)
    stub_json = save_stub_report(stub_data, project_data, output_dir)
    
    # 8. 总结报告
    _print_final_summary(violations_data, stub_data, output_dir)


def _save_project_data(project_data, json_path: Path) -> None:
    """保存完整的项目数据为JSON文件"""
    from .node_types import NodeType, FunctionInfo
    
    # 准备可序列化的数据
    config_data = {}
    for key, value in project_data.config.items():
        if hasattr(value, '__dict__'):
            # 如果是对象，转换为字典
            config_data[key] = value.__dict__
        else:
            config_data[key] = value
    
    json_data = {
        "version": project_data.version,
        "timestamp": project_data.timestamp,
        "project_root": project_data.project_root,
        "config": config_data,
        "summary": {
            "total_nodes": len(project_data.nodes),
            "total_modules": len(project_data.modules),
            "total_packages": len(project_data.packages),
            "total_import_edges": len(project_data.import_edges),
            "total_child_edges": len(project_data.child_edges),
            "total_functions": sum(node.functions_total for node in project_data.nodes.values()),
            "total_stubs": sum(node.stubs for node in project_data.nodes.values())
        },
        "nodes": {},
        "import_edges": list(project_data.import_edges),
        "child_edges": list(project_data.child_edges)
    }
    
    # 序列化节点数据
    for name, node in project_data.nodes.items():
        # 序列化函数信息
        functions_data = []
        for func in node.functions:
            functions_data.append({
                "name": func.name,
                "full_name": func.full_name,
                "is_stub": func.is_stub,
                "is_public": func.is_public,
                "docstring": func.docstring,
                "line_number": func.line_number,
                "is_method": func.is_method,
                "class_name": func.class_name
            })
        
        # 序列化类方法信息
        classes_data = {}
        for class_name, methods in node.classes.items():
            classes_data[class_name] = []
            for method in methods:
                classes_data[class_name].append({
                    "name": method.name,
                    "full_name": method.full_name,
                    "is_stub": method.is_stub,
                    "is_public": method.is_public,
                    "docstring": method.docstring,
                    "line_number": method.line_number,
                    "is_method": method.is_method,
                    "class_name": method.class_name
                })
        
        json_data["nodes"][name] = {
            "name": node.name,
            "node_type": node.node_type.value,
            "file_path": node.file_path,
            "functions": functions_data,
            "classes": classes_data,
            "imports": list(node.imports),
            "functions_total": node.functions_total,
            "functions_public": node.functions_public,
            "stubs": node.stubs,
            "stub_ratio": node.stub_ratio,
            "parent": node.parent,
            "children": list(node.children),
            "package_depth": node.package_depth,
            "graph_depth": node.graph_depth
        }
    
    # 写入JSON文件
    with json_path.open('w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)


def _aggregate_to_packages_new(nodes, edges):
    """新版的包聚合函数"""
    from .node_types import NodeInfo, NodeType
    
    # 按包名聚合
    def pkg_of(mod: str) -> str:
        return mod if "." not in mod else mod.rsplit(".", 1)[0]

    pkg_nodes = {}
    for node_name, node in nodes.items():
        pkg_name = pkg_of(node_name)
        if pkg_name not in pkg_nodes:
            # 创建包节点
            pkg_nodes[pkg_name] = NodeInfo(
                name=pkg_name,
                node_type=NodeType.PACKAGE,
                file_path=node.file_path  # 使用第一个找到的文件路径
            )
        
        # 聚合统计数据
        pkg_node = pkg_nodes[pkg_name]
        pkg_node.functions.extend(node.functions)
        for class_name, methods in node.classes.items():
            if class_name not in pkg_node.classes:
                pkg_node.classes[class_name] = []
            pkg_node.classes[class_name].extend(methods)
        pkg_node.imports.update(node.imports)
        
        # 重新计算统计信息
        pkg_node.__post_init__()

    # 聚合边
    pkg_edges = set()
    for src, dst in edges:
        src_pkg, dst_pkg = pkg_of(src), pkg_of(dst)
        if src_pkg != dst_pkg:
            pkg_edges.add((src_pkg, dst_pkg))
    
    return pkg_nodes, pkg_edges


def _print_project_summary(project_data, root: str) -> None:
    """打印项目摘要信息"""
    total_funcs = sum(node.functions_total for node in project_data.nodes.values())
    total_public = sum(node.functions_public for node in project_data.nodes.values())
    total_stubs = sum(node.stubs for node in project_data.nodes.values())
    ratio = (total_stubs / total_public) if total_public else 0.0

    print("\n== CodeClinic v0.1.3a1 项目分析摘要 ==")
    print(f"📁 项目根目录: {root}")
    print(f"📊 节点统计: {len(project_data.nodes)} 个 "
          f"({len(project_data.modules)} modules + {len(project_data.packages)} packages)")
    print(f"🔗 关系统计: {len(project_data.import_edges)} 个导入关系, "
          f"{len(project_data.child_edges)} 个包含关系")
    print(f"⚙️  函数统计: {total_public}/{total_funcs} (公共/总计)")
    print(f"🚧 Stub统计: {total_stubs} 个stub ({ratio:.1%})")

    # 显示导入关系（简化）
    if len(project_data.import_edges) <= 20:  # 只在边数较少时显示
        adj = defaultdict(set)
        for s, d in project_data.import_edges:
            adj[s].add(d)
        print(f"\n📈 导入关系图:")
        for src in sorted(list(adj.keys())[:10]):  # 最多显示10个
            src_display = _get_display_name(src)
            target_names = [_get_display_name(t) for t in sorted(list(adj[src])[:3])]
            targets = ", ".join(target_names)  # 每个最多显示3个目标
            if len(adj[src]) > 3:
                targets += f" (+{len(adj[src])-3} more)"
            print(f"  {src_display} -> {targets}")
        if len(adj) > 10:
            print(f"  ... (+{len(adj)-10} more nodes)")


def _get_display_name(full_name: str) -> str:
    """获取用于显示的简化名称（只显示最后一级）"""
    if not full_name:
        return "root"
    return full_name.split('.')[-1]


def _print_final_summary(violations_data, stub_data, output_dir: Path) -> None:
    """打印最终分析摘要"""
    print(f"\n📋 === 分析完成 ===")
    
    # 违规摘要 - 从violations计算
    total_violations = len(violations_data["violations"])
    
    # 按类型统计违规
    violations_by_type = {}
    for v in violations_data["violations"]:
        vtype = v.violation_type  # ImportViolation对象的属性
        violations_by_type[vtype] = violations_by_type.get(vtype, 0) + 1
    
    # 计算合规率需要获取总边数，这里简化处理
    print(f"🚨 导入合规性: {total_violations} 个违规")
    
    if total_violations > 0:
        for vtype, count in violations_by_type.items():
            print(f"   - {vtype}: {count} 个")
    
    # Stub摘要 - 从stub_functions计算
    total_stubs = len(stub_data["stub_functions"])
    # 从stub_functions统计总函数数（这里简化处理）
    print(f"🚧 实现完整度: {total_stubs} 个stub函数")
    
    # 输出文件摘要
    print(f"\n📁 输出文件:")
    print(f"   📄 data.json - 完整项目数据")
    print(f"   📂 import_violations/ - 导入违规分析")
    print(f"   📂 stub_completeness/ - 实现完整度分析")
    
    print(f"\n🎉 所有结果保存在: {output_dir.absolute()}")


def _run_legacy_analysis(args):
    """运行旧版分析流程，保持向后兼容"""
    print("🔄 使用传统分析模式...")
    
    # 加载旧版配置
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
        stub_report_path = save_legacy_stub_report(stub_functions, edges, args.path, output_dir / "stub_report.json")
        print(f"✓ Stub function report saved to: {stub_report_path}")
    else:
        print("✓ No stub functions found in project")

    # Always generate visualization
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