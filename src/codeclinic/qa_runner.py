from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import asdict
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .qa_config import QAConfig, load_qa_config, write_qa_config


def qa_init(force: bool = False, pre_commit: bool = False, github_actions: bool = False, makefile: bool = False) -> None:
    target = write_qa_config("codeclinic.yaml", force=force)
    if target.name.endswith(".qa.example.yaml"):
        print(f"⚠ 检测到已有 codeclinic.yaml，示例已生成: {target}")
        print("   请按需合并 QA 配置段落到现有文件。")
    else:
        print(f"✓ 已生成 QA 配置: {target}")

    if pre_commit:
        p = _write_pre_commit()
        print(f"✓ 已生成 pre-commit 配置: {p}")
    if github_actions:
        p = _write_github_actions()
        print(f"✓ 已生成 GitHub Actions 工作流: {p}")
    if makefile:
        p = _write_makefile()
        print(f"✓ 已生成 Makefile: {p}")


def qa_run(config_path: str = "codeclinic.yaml", output_override: Optional[str] = None) -> int:
    try:
        cfg = load_qa_config(config_path)
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return 2

    out_dir = Path(output_override or cfg.tool.output)
    logs_dir = out_dir / "logs"
    artifacts_dir = out_dir / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, Any] = {
        "version": "1.0",
        "status": "pending",
        "artifacts_base": str(out_dir),
        "logs": {},
        "metrics": {},
        "gates_failed": [],
    }

    # Provider: black --check
    fmt_status, fmt_log, fmt_clean = _run_black_check(cfg, logs_dir)
    results["logs"]["black"] = fmt_log
    results["metrics"]["formatter"] = {
        "provider": cfg.tools.formatter.provider,
        "clean": fmt_clean,
        "status": fmt_status,
    }

    # Provider: ruff check
    lint_status, lint_log, lint_errors = _run_ruff_check(cfg, logs_dir)
    results["logs"]["ruff"] = lint_log
    results["metrics"]["linter"] = {
        "provider": cfg.tools.linter.provider,
        "errors": lint_errors,
        "status": lint_status,
    }

    # Provider: mypy
    mypy_status, mypy_log, mypy_errors = _run_mypy(cfg, logs_dir)
    results["logs"]["mypy"] = mypy_log
    results["metrics"]["typecheck"] = {
        "provider": cfg.tools.typecheck.provider,
        "errors": mypy_errors,
        "status": mypy_status,
    }

    # Provider: pytest + coverage (+ JUnit XML)
    test_status, test_log, cov_pct, cov_xml, junit_xml = _run_pytest_coverage(cfg, logs_dir, artifacts_dir, out_dir)
    results["logs"]["pytest"] = test_log
    results["metrics"]["tests"] = {
        "provider": cfg.tools.tests.provider,
        "coverage_percent": cov_pct,
        "coverage_xml": cov_xml,
        "status": test_status,
    }

    # Provider: complexity (radon if available; fallback to builtin LOC)
    cpx_status, cpx_log, cpx_json, cpx_summary = _run_complexity(cfg, logs_dir, artifacts_dir)
    results["logs"]["complexity"] = cpx_log
    results["metrics"]["complexity"] = {
        "provider": cfg.tools.complexity.provider,
        "summary": cpx_summary,
        "report": cpx_json,
        "status": cpx_status,
    }

    # Internal: deps (+project data)。按要求移除 stub 比例统计/报表
    deps_metrics, project_data = _run_internal_analyses(cfg, artifacts_dir)
    results["metrics"]["deps"] = deps_metrics
    # 不再提供全局 stubs 指标与报表

    # Component tests aggregation (dependency-aware)
    comp_report, comp_summary = _aggregate_component_tests(cfg, artifacts_dir, project_data, stub_data, junit_xml)
    results["metrics"]["component_tests"] = {
        "provider": "pytest+junit",
        "components_total": comp_summary.get("components_total"),
        "components_dep_stub_free": comp_summary.get("components_dep_stub_free"),
        "components_dep_stub_free_green": comp_summary.get("components_dep_stub_free_green"),
        "report": str(comp_report) if comp_report else None,
        "status": "passed" if comp_summary.get("gate_failed_count", 0) == 0 else "failed",
    }

    # Extensions: function metrics, stub doc contracts, exports
    fn_over_count, fn_report = _ext_function_metrics(cfg, artifacts_dir)
    stub_missing_count, docs_report = _ext_doc_contracts(cfg, artifacts_dir)
    private_exports_count, exports_report = _ext_exports(cfg, artifacts_dir)
    results.setdefault("metrics", {})["function_metrics_ext"] = {
        "violations": fn_over_count,
        "report": str(fn_report) if fn_report else None,
        "status": "passed" if fn_over_count == 0 else "failed",
    }
    results["metrics"]["doc_contracts_ext"] = {
        "stub_doc_missing": stub_missing_count,
        "report": str(docs_report) if docs_report else None,
        "status": "passed" if stub_missing_count == 0 else "failed",
    }
    results["metrics"]["exports_ext"] = {
        "private_exports": private_exports_count,
        "report": str(exports_report) if exports_report else None,
        "status": "passed" if private_exports_count == 0 else "failed",
    }

    # Gates evaluation
    gates_failed: List[str] = []
    g = cfg.gates
    if g.formatter_clean and (fmt_status == "failed" or not fmt_clean):
        gates_failed.append("formatter_clean")
    if lint_errors is not None and lint_errors > g.linter_errors_max:
        gates_failed.append("linter_errors_max")
    if mypy_errors is not None and mypy_errors > g.mypy_errors_max:
        gates_failed.append("mypy_errors_max")
    if cov_pct is None or cov_pct < g.coverage_min:
        gates_failed.append("coverage_min")
    if deps_metrics.get("violations") is not None and deps_metrics["violations"] > g.import_violations_max:
        gates_failed.append("import_violations_max")
    # 按要求：移除 stub 比例门禁
    # Complexity gates
    max_loc = cpx_summary.get("max_file_loc") if cpx_summary else None
    if isinstance(max_loc, int) and max_loc > g.max_file_loc:
        gates_failed.append("max_file_loc")
    # 仅当使用radon并且配置了阈值时检查 CC/MI 门禁
    comp_provider = (cpx_summary or {}).get("provider") if isinstance(cpx_summary, dict) else None
    if comp_provider == "radon":
        # CC 等级门禁：不允许出现比阈值更差的等级（A最好、F最差）
        if g.cc_max_rank_max:
            try:
                worst_list = ((cpx_summary.get("worst") or {}).get("by_cc_max") or [])
                # 取最差一个的等级；如果列表为空则回退到分布
                if worst_list:
                    worst_rank = str(worst_list[0].get("cc_max_rank", "")).upper()
                else:
                    dist = ((cpx_summary.get("cc") or {}).get("cc_rank_distribution") or {})
                    # 从最差到最好查找
                    order = ["F","E","D","C","B","A"]
                    worst_rank = next((r for r in order if dist.get(r, 0) > 0), None)
                if worst_rank:
                    order_map = {k: i for i, k in enumerate(["A","B","C","D","E","F"], start=1)}
                    thr = order_map.get(g.cc_max_rank_max.upper())
                    wrv = order_map.get(worst_rank)
                    if thr is not None and wrv is not None and wrv > thr:
                        gates_failed.append("cc_max_rank_max")
            except Exception:
                # 忽略解析异常，不触发该门禁
                pass
        # MI 门禁：不允许文件MI低于阈值
        if isinstance(g.mi_min, int) and g.mi_min > 0:
            try:
                mi_min = ((cpx_summary.get("mi") or {}).get("min", None))
                if isinstance(mi_min, (int, float)) and mi_min < g.mi_min:
                    gates_failed.append("mi_min")
            except Exception:
                pass

    # Component tests gate
    if cfg.gates.components_dep_stub_free_requires_green:
        if comp_summary.get("gate_failed_count", 0) > 0:
            gates_failed.append("components_dep_stub_free_requires_green")

    # Packages require __init__.py gate
    if cfg.gates.packages_require_dunder_init:
        missing_init = _check_packages_require_dunder_init(cfg)
        if missing_init:
            results.setdefault("metrics", {}).setdefault("packages_integrity", {})["missing_init"] = missing_init
            gates_failed.append("packages_require_dunder_init")

    # Modules require named tests gate
    if cfg.gates.modules_require_named_tests:
        missing_tests, presence_report = _check_modules_require_named_tests(cfg, project_data)
        results.setdefault("metrics", {}).setdefault("tests_presence", {})["missing_named_tests"] = missing_tests
        results["metrics"]["tests_presence"]["report"] = str(presence_report)
        if missing_tests:
            gates_failed.append("modules_require_named_tests")

    # Extension gates
    try:
        thr = int(getattr(g, 'doc_contracts_missing_max', 0) or 0)
        if stub_missing_count > thr:
            gates_failed.append('doc_contracts_missing_max')
    except Exception: pass
    if any((getattr(g, 'fn_loc_max', 0), getattr(g, 'fn_args_max', 0), getattr(g, 'fn_nesting_max', 0))):
        if fn_over_count > 0:
            gates_failed.append('function_metrics_over_threshold')
    if bool(getattr(g, 'exports_no_private', False)) and private_exports_count > 0:
        gates_failed.append('exports_no_private')

    results["gates_failed"] = gates_failed
    results["status"] = "passed" if not gates_failed else "failed"

    # Write summary.json
    (out_dir / "summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    # Write simple HTML report
    _write_html_report(out_dir, results)
    print(f"\n📄 QA 汇总已写入: {out_dir / 'summary.json'}")

    return 0 if not gates_failed else 1


def qa_fix(config_path: str = "codeclinic.yaml") -> int:
    try:
        cfg = load_qa_config(config_path)
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return 2

    # Only auto-fix providers
    codes: List[int] = []
    code, _ = _call(
        ["black", f"--line-length={cfg.tools.formatter.line_length}"] + cfg.tool.paths
    )
    codes.append(code)

    ruff_args = ["ruff", "check", "--fix"]
    if cfg.tools.linter.unsafe_fixes:
        ruff_args.append("--unsafe-fixes")
    ruff_args += cfg.tool.paths
    code, _ = _call(ruff_args)
    codes.append(code)

    # Non-zero if any failed (missing provider or other failure)
    return 0 if all(c == 0 for c in codes) else 1


# -------- provider runners ---------


def _run_black_check(cfg: QAConfig, logs_dir: Path) -> Tuple[str, str, bool]:
    if cfg.tools.formatter.provider != "black":
        return ("skipped", "", True)
    log_path = logs_dir / "black.log"
    args = ["black", "--check", f"--line-length={cfg.tools.formatter.line_length}"] + cfg.tool.paths
    code, out = _call(args)
    log_path.write_text(out, encoding="utf-8")
    return ("passed" if code == 0 else "failed", str(log_path), code == 0)


def _run_ruff_check(cfg: QAConfig, logs_dir: Path) -> Tuple[str, str, Optional[int]]:
    if cfg.tools.linter.provider != "ruff":
        return ("skipped", "", None)
    log_path = logs_dir / "ruff.log"
    args = ["ruff", "check"] + cfg.tool.paths
    # line length and selected rules
    if cfg.tools.linter.ruleset:
        for r in cfg.tools.linter.ruleset:
            args += ["--select", r]
    args += [f"--line-length={cfg.tools.linter.line_length}"]
    # Optional: docstring convention via a temporary ruff config
    try:
        conv = getattr(cfg.tools.linter, 'docstyle_convention', None)
        if conv:
            tmp_cfg = logs_dir / "ruff_docstyle.toml"
            tmp_cfg.write_text(
                f"""
[tool.ruff]
line-length = 88

[tool.ruff.pydocstyle]
convention = "{conv}"
""",
                encoding="utf-8",
            )
            args += ["--config", str(tmp_cfg)]
    except Exception:
        pass
    code, out = _call(args)
    log_path.write_text(out, encoding="utf-8")
    errors = _count_ruff_issues(out) if code != 0 else 0
    return ("passed" if code == 0 else "failed", str(log_path), errors)


def _run_mypy(cfg: QAConfig, logs_dir: Path) -> Tuple[str, str, Optional[int]]:
    if cfg.tools.typecheck.provider != "mypy":
        return ("skipped", "", None)
    log_path = logs_dir / "mypy.log"
    # Run mypy via the same interpreter to ensure site-packages (incl. py.typed) from this environment are used
    args = [sys.executable, "-m", "mypy"] + cfg.tool.paths
    if cfg.tools.typecheck.config_file:
        args += ["--config-file", cfg.tools.typecheck.config_file]
    if cfg.tools.typecheck.strict:
        args.append("--strict")
    code, out = _call(args)
    log_path.write_text(out, encoding="utf-8")
    errors = _count_mypy_errors(out) if code != 0 else 0
    return ("passed" if code == 0 else "failed", str(log_path), errors)


def _run_pytest_coverage(cfg: QAConfig, logs_dir: Path, artifacts_dir: Path, out_dir: Path) -> Tuple[str, str, Optional[int], Optional[str], Optional[str]]:
    # Always require coverage+pytest; absence should cause failure via return code
    
    # Normal coverage path

    log_path = logs_dir / "pytest.log"
    cov_xml = artifacts_dir / "coverage.xml"
    # Ensure junit target path
    junit_xml_path: Optional[Path] = None
    if cfg.tools.tests.junit.enabled:
        raw = Path(cfg.tools.tests.junit.output)
        # If relative path, treat it as relative to CWD (not out_dir) to avoid duplication
        junit_xml_path = raw if raw.is_absolute() else raw
        junit_xml_path.parent.mkdir(parents=True, exist_ok=True)
    # Run tests
    pytest_cmd = ["coverage", "run", "-m", "pytest", *cfg.tools.tests.args]
    if junit_xml_path is not None:
        pytest_cmd += ["--junitxml", str(junit_xml_path)]
    code_run, out_run = _call(pytest_cmd)
    # Produce coverage xml regardless of test status to capture partial results
    _ = _call(["coverage", "xml", "-o", str(cov_xml)])[0]
    cov_pct = _parse_coverage_percent(cov_xml) if cov_xml.exists() else None
    combined = out_run
    log_path.write_text(combined, encoding="utf-8")
    status = "passed" if code_run == 0 else "failed"
    return (status, str(log_path), cov_pct, str(cov_xml) if cov_xml.exists() else None, str(junit_xml_path) if junit_xml_path else None)


def _run_internal_analyses(cfg: QAConfig, artifacts_dir: Path) -> Tuple[Dict[str, Any], Any]:
    # Prepare minimal adapter to existing collector
    from .data_collector import collect_project_data
    from .violations_analysis import analyze_violations, save_violations_report
    from .stub_analysis import analyze_stub_completeness, save_stub_report

    project_data = collect_project_data(
        paths=cfg.tool.paths,
        include=cfg.tool.include,
        exclude=cfg.tool.exclude,
        count_private=False,
        config={
            "import_rules": cfg.tools.deps.import_rules,
            "aggregate": "module",
            "format": "svg",
        },
    )

    # Violations
    vdata = analyze_violations(project_data)
    vjson = save_violations_report(vdata, project_data, artifacts_dir)
    dep_metrics = {
        "provider": cfg.tools.deps.provider,
        "violations": len(vdata["violations"]),
        "report": str(vjson),
        "status": "passed" if len(vdata["violations"]) == 0 else "failed",
    }

    # 按要求：移除 stub 比例统计与报表
    return dep_metrics, project_data


# -------- helpers ---------


def _call(args: List[str]) -> Tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out
    except FileNotFoundError as e:
        return 127, f"EXEC ERROR: {e} while running: {' '.join(args)}\n"


def _count_ruff_issues(output: str) -> int:
    # Basic heuristic: count lines like "path:line:col: code ..."
    return sum(1 for line in output.splitlines() if ":" in line and line.strip() and not line.startswith(" "))


def _count_mypy_errors(output: str) -> int:
    # mypy outputs one error per line typically, excluding summary lines
    lines = [l for l in output.splitlines() if l and ": error:" in l]
    return len(lines)


def _parse_coverage_percent(xml_path: Path) -> Optional[int]:
    try:
        txt = xml_path.read_text(encoding="utf-8", errors="ignore")
        # Look for 'line-rate="0.85"'
        import re

        m = re.search(r"line-rate=\"([0-9.]+)\"", txt)
        if not m:
            return None
        pct = float(m.group(1)) * 100.0
        return int(round(pct))
    except Exception:
        return None


# -------- complexity (radon) ---------


def _run_complexity(cfg: QAConfig, logs_dir: Path, artifacts_dir: Path) -> Tuple[str, str, Optional[str], Dict[str, Any]]:
    log_path = logs_dir / "complexity.log"
    report_path = artifacts_dir / "complexity.json"

    files = _collect_py_files(cfg.tool.paths, cfg.tool.include, cfg.tool.exclude)
    used_radon = True

    file_results: List[Dict[str, Any]] = []
    max_file_loc = 0
    over_limit: List[str] = []

    # Require radon; if not present, ImportError will bubble up and fail the run
    from radon.raw import analyze as radon_analyze  # type: ignore
    from radon.complexity import cc_visit, cc_rank  # type: ignore
    from radon.metrics import mi_visit  # type: ignore

    lines_log: List[str] = []

    for f in files:
        try:
            txt = Path(f).read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            lines_log.append(f"[skip] {f}: {e}")
            continue

        # radon-based metrics
        raw = radon_analyze(txt)
        cc_nodes = cc_visit(txt)
        mi = mi_visit(txt, True)  # multi=True
        loc = int(raw.loc)
        sloc = int(getattr(raw, "sloc", 0))
        lloc = int(getattr(raw, "lloc", 0))
        if cc_nodes:
            cc_values = [n.complexity for n in cc_nodes]
            cc_avg = sum(cc_values) / len(cc_values)
            cc_max = max(cc_values)
            cc_rank_max = cc_rank(cc_max)
        else:
            cc_avg = 0.0
            cc_max = 0.0
            cc_rank_max = "A"
        file_results.append({
            "path": f,
            "loc": loc,
            "sloc": sloc,
            "lloc": lloc,
            "mi": round(float(mi), 2) if mi is not None else None,
            "cc_avg": round(float(cc_avg), 2),
            "cc_max": round(float(cc_max), 2),
            "cc_max_rank": cc_rank_max,
        })
        max_file_loc = max(max_file_loc, loc)
        if loc > cfg.gates.max_file_loc:
            over_limit.append(f)
        lines_log.append(f"[ok] {f}: loc={loc} mi={mi:.2f} cc_avg={cc_avg:.2f} cc_max={cc_max:.2f}({cc_rank_max})")

    # Aggregations
    files_count = len(file_results)
    total_loc = sum(int(fr.get("loc") or 0) for fr in file_results)
    avg_loc = int(round(total_loc / files_count)) if files_count else 0

    cc_ranks = {k: 0 for k in list("ABCDEF")}
    cc_max_values = []
    cc_avg_values = []
    mi_values = []
    worst_cc_files = []
    worst_mi_files = []

    for fr in file_results:
        rank = fr.get("cc_max_rank")
        if rank in cc_ranks:
            cc_ranks[rank] += 1
        if fr.get("cc_max") is not None:
            cc_max_values.append(float(fr["cc_max"]))
        if fr.get("cc_avg") is not None:
            cc_avg_values.append(float(fr["cc_avg"]))
        if fr.get("mi") is not None:
            try:
                mi_values.append(float(fr["mi"]))
            except Exception:
                pass

    # Top offenders
    worst_cc_files = sorted(
        [fr for fr in file_results if fr.get("cc_max") is not None],
        key=lambda x: x["cc_max"], reverse=True
    )[:10]
    worst_mi_files = sorted(
        [fr for fr in file_results if fr.get("mi") is not None],
        key=lambda x: x["mi"]
    )[:10]

    # MI distribution buckets
    mi_dist = {"<70": 0, "70-80": 0, "80-90": 0, ">=90": 0}
    for v in mi_values:
        if v < 70:
            mi_dist["<70"] += 1
        elif v < 80:
            mi_dist["70-80"] += 1
        elif v < 90:
            mi_dist["80-90"] += 1
        else:
            mi_dist[">=90"] += 1

    summary = {
        "files_count": files_count,
        "total_loc": int(total_loc),
        "avg_loc": int(avg_loc),
        "max_file_loc": int(max_file_loc),
        "files_over_limit": over_limit,
        "provider": "radon" if used_radon else "builtin",
        "cc": {
            "cc_max_mean": round(sum(cc_max_values) / len(cc_max_values), 2) if cc_max_values else None,
            "cc_avg_mean": round(sum(cc_avg_values) / len(cc_avg_values), 2) if cc_avg_values else None,
            "cc_rank_distribution": cc_ranks,
        },
        "mi": {
            "mean": round(sum(mi_values) / len(mi_values), 2) if mi_values else None,
            "min": round(min(mi_values), 2) if mi_values else None,
            "max": round(max(mi_values), 2) if mi_values else None,
            "distribution": mi_dist,
        },
        "worst": {
            "by_cc_max": [
                {"path": fr["path"], "cc_max": fr["cc_max"], "cc_max_rank": fr.get("cc_max_rank"), "loc": fr.get("loc")}
                for fr in worst_cc_files
            ],
            "by_mi": [
                {"path": fr["path"], "mi": fr["mi"], "loc": fr.get("loc")}
                for fr in worst_mi_files
            ],
        },
    }

    report = {
        "version": "1.0",
        "summary": summary,
        "files": file_results,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log_path.write_text("\n".join(lines_log), encoding="utf-8")

    status = "passed" if not over_limit else "failed"
    return status, str(log_path), str(report_path), summary


def _collect_py_files(paths: List[str], include: List[str], exclude: List[str]) -> List[str]:
    import os, fnmatch
    collected: List[str] = []
    for root in paths:
        base = Path(root)
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            # filter directories by exclude patterns
            dir_rel_list = list(dirnames)
            for d in dir_rel_list:
                d_path = Path(dirpath) / d
                rel = str(d_path.relative_to(base))
                if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                    dirnames.remove(d)
            for fn in filenames:
                if not fn.endswith('.py'):
                    continue
                f_path = Path(dirpath) / fn
                try:
                    rel = str(f_path.relative_to(base))
                except Exception:
                    rel = str(f_path)
                if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                    continue
                if include:
                    if not any(fnmatch.fnmatch(rel, pat) for pat in include):
                        continue
                collected.append(str(f_path))
    return collected


def _aggregate_component_tests(
    cfg: QAConfig,
    artifacts_dir: Path,
    project_data: Any,
    stub_data: Dict[str, Any],
    junit_xml: Optional[str],
) -> Tuple[Optional[Path], Dict[str, Any]]:
    # Parse JUnit XML
    from xml.etree import ElementTree as ET
    junit_cases: List[Dict[str, Any]] = []
    if junit_xml and Path(junit_xml).exists():
        try:
            tree = ET.parse(junit_xml)
            root = tree.getroot()
            for case in root.iter("testcase"):
                fpath = case.get("file") or ""
                status = "passed"
                if list(case.findall("failure")) or list(case.findall("error")):
                    status = "failed"
                elif list(case.findall("skipped")):
                    status = "skipped"
                junit_cases.append({
                    "file": fpath,
                    "classname": case.get("classname") or "",
                    "status": status,
                })
        except Exception:
            pass

    # Build component mapping
    scope = cfg.components.scope
    tests_dir_name = cfg.components.tests_dir_name

    # Map component -> directory path (and file path for modules)
    components_dirs: Dict[str, Path] = {}
    module_file_map: Dict[str, Path] = {}
    if scope == "package":
        for name, node in project_data.packages.items():
            components_dirs[name] = Path(node.file_path).parent
    else:
        # module scope: each module as a component
        for name, node in project_data.modules.items():
            p = Path(node.file_path)
            components_dirs[name] = p.parent
            module_file_map[name] = p

    # Component stubs (self) and stubs per component for deps
    def pkg_of(node_name: str) -> str:
        return node_name if "." not in node_name else node_name.rsplit(".", 1)[0]

    def component_of_node(name: str) -> str:
        if scope == "package":
            return name if name in project_data.packages else pkg_of(name)
        else:
            return name

    stubs_per_component: Dict[str, int] = {}
    for node_name, node in project_data.nodes.items():
        comp = component_of_node(node_name)
        stubs_per_component[comp] = stubs_per_component.get(comp, 0) + int(node.stubs)

    # Build component dependency graph
    comp_edges: Dict[str, set] = {c: set() for c in components_dirs.keys()}
    for src, dst in project_data.import_edges:
        csrc = component_of_node(src)
        cdst = component_of_node(dst)
        if csrc != cdst and csrc in comp_edges:
            comp_edges.setdefault(csrc, set()).add(cdst)

    def deps_of(component: str) -> set:
        if cfg.components.dependency_scope == "direct":
            return set(comp_edges.get(component, set()))
        # transitive closure
        result = set()
        stack = list(comp_edges.get(component, set()))
        while stack:
            d = stack.pop()
            if d in result:
                continue
            result.add(d)
            stack.extend(list(comp_edges.get(d, set())))
        return result

    # Aggregate tests per component (same-level tests only)
    comps: List[Dict[str, Any]] = []
    for comp, comp_dir in components_dirs.items():
        if not comp:
            # skip root package component
            continue
        tests_dir = comp_dir / tests_dir_name
        # Count testcases by rule
        total = failed = skipped = 0
        if junit_cases:
            if scope == "module":
                # Strict mapping: tests/test_<module>.py
                mod_file = module_file_map.get(comp)
                if mod_file is not None:
                    expected = tests_dir / f"test_{mod_file.stem}.py"
                    for case in junit_cases:
                        f = case.get("file") or ""
                        try:
                            if f and Path(f).resolve() == expected.resolve():
                                total += 1
                                if case["status"] == "failed":
                                    failed += 1
                                elif case["status"] == "skipped":
                                    skipped += 1
                                continue
                        except Exception:
                            pass
                        # Fallback by classname
                        cls = case.get("classname") or ""
                        # e.g., example_project.pkg.tests.test_mod
                        if cls.endswith(f".tests.test_{mod_file.stem}"):
                            total += 1
                            if case["status"] == "failed":
                                failed += 1
                            elif case["status"] == "skipped":
                                skipped += 1
            else:
                # package scope: any tests under <pkg>/tests/**
                for case in junit_cases:
                    counted = False
                    f = case.get("file") or ""
                    if f and tests_dir.exists():
                        try:
                            if Path(f).resolve().is_relative_to(tests_dir.resolve()):
                                counted = True
                        except Exception:
                            if str(f).startswith(str(tests_dir)):
                                counted = True
                    if not counted:
                        cls = case.get("classname") or ""
                        if ".tests." in cls:
                            prefix = cls.split(".tests.")[0]
                            if prefix.endswith(comp) or prefix.endswith("." + comp):
                                counted = True
                    if counted:
                        total += 1
                        if case["status"] == "failed":
                            failed += 1
                        elif case["status"] == "skipped":
                            skipped += 1

        deps = deps_of(comp)
        deps_stub_free = all(stubs_per_component.get(d, 0) == 0 for d in deps)
        stubs_self = stubs_per_component.get(comp, 0)
        status = "green" if total > 0 and failed == 0 else ("missing" if total == 0 else "red")

        comps.append({
            "name": comp,
            "path": str(comp_dir),
            "tests_dir": str(tests_dir),
            "tests_total": total,
            "tests_failed": failed,
            "tests_skipped": skipped,
            "status": status,
            "deps_stub_free": bool(deps_stub_free),
            "dep_count": int(len(deps)),
            "stubs_self": int(stubs_self),
        })

    # Gate evaluation per rules
    failed_components: List[str] = []
    dep_stub_free_components = 0
    green_components = 0
    for c in comps:
        if c["deps_stub_free"]:
            dep_stub_free_components += 1
            # Gate 口径：当 require_self_stub_free=true 时，需要“自身无 stub 且依赖无 stub”才要求全绿；
            # 否则仅当依赖无 stub 时要求全绿。
            if cfg.components.require_self_stub_free:
                apply_gate = (c["deps_stub_free"]) and (c["stubs_self"] == 0)
            else:
                apply_gate = c["deps_stub_free"]
            if apply_gate:
                if c["tests_total"] == 0:
                    if not cfg.gates.allow_missing_component_tests:
                        failed_components.append(c["name"])
                elif c["tests_failed"] > 0:
                    failed_components.append(c["name"])
                else:
                    green_components += 1

    summary = {
        "components_total": len(comps),
        "components_dep_stub_free": dep_stub_free_components,
        "components_dep_stub_free_green": green_components,
        "gate_failed_count": len(failed_components),
        "failed_components": failed_components,
    }

    # Write report
    report_path = artifacts_dir / "component_tests.json"
    report = {
        "version": "1.0",
        "components": comps,
        "summary": summary,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report_path, summary


def _check_packages_require_dunder_init(cfg: QAConfig) -> List[str]:
    missing: List[str] = []
    for root in cfg.tool.paths:
        base = Path(root)
        if not base.exists():
            continue
        import os
        for dirpath, dirnames, filenames in os.walk(str(base)):
            dpath = Path(dirpath)
            # skip tests directories
            if dpath.name == "tests" or "/tests/" in (str(dpath) + "/"):
                continue
            py_files = [f for f in filenames if f.endswith(".py")]
            if py_files:
                if not (dpath / "__init__.py").exists():
                    missing.append(str(dpath))
    return missing


def _check_modules_require_named_tests(cfg: QAConfig, project_data: Any) -> Tuple[List[str], Path]:
    """Ensure every in-package module has a matching tests/test_<module>.py file.
    Only applies to modules inside packages (i.e., node.parent is not None)."""
    missing: List[str] = []
    tests_dir_name = cfg.components.tests_dir_name
    for name, node in project_data.modules.items():
        # Skip top-level modules (not inside package)
        if not getattr(node, "parent", None):
            continue
        mod_path = Path(node.file_path)
        if mod_path.name == "__init__.py":
            continue
        tests_dir = mod_path.parent / tests_dir_name
        expected = tests_dir / f"test_{mod_path.stem}.py"
        if not expected.exists():
            missing.append(name)

    report_path = Path(cfg.tool.output) / "artifacts" / "module_tests_presence.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"version": "1.0", "missing_named_tests": missing}
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return missing, report_path


def _write_html_report(out_dir: Path, results: Dict[str, Any]) -> None:
    artifacts_dir = out_dir / "artifacts"
    html_path = artifacts_dir / "report.html"
    status = results.get("status", "unknown")
    gates = results.get("gates_failed", [])
    metrics = results.get("metrics", {})

    def esc(s: Any) -> str:
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    rows = []
    for name, data in metrics.items():
        st = data.get("status", "-")
        provider = data.get("provider", "-")
        report = data.get("report") or data.get("coverage_xml")
        rows.append(f"<tr><td>{esc(name)}</td><td>{esc(provider)}</td><td>{esc(st)}</td><td>{esc(report or '')}</td></tr>")

    # Try load complexity aggregates
    cpx_path = artifacts_dir / "complexity.json"
    cpx_html = ""
    if cpx_path.exists():
        try:
            cdata = json.loads(cpx_path.read_text(encoding="utf-8"))
            summ = cdata.get("summary", {})
            cc = summ.get("cc", {})
            mi = summ.get("mi", {})
            worst = summ.get("worst", {})

            # CC rank distribution table
            rank_rows = "".join(
                f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in (cc.get("cc_rank_distribution") or {}).items()
            )
            worst_cc_rows = "".join(
                f"<tr><td>{esc(x.get('path'))}</td><td>{esc(x.get('cc_max'))}</td><td>{esc(x.get('cc_max_rank'))}</td><td>{esc(x.get('loc'))}</td></tr>"
                for x in (worst.get("by_cc_max") or [])
            )
            worst_mi_rows = "".join(
                f"<tr><td>{esc(x.get('path'))}</td><td>{esc(x.get('mi'))}</td><td>{esc(x.get('loc'))}</td></tr>"
                for x in (worst.get("by_mi") or [])
            )

            dist = mi.get("distribution") or {}
            mi_dist_rows = "".join(
                f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in dist.items()
            )

            cpx_html = f"""
  <h2>Complexity</h2>
  <p>Provider: <code>{esc(summ.get('provider'))}</code></p>
  <ul>
    <li>Files: {esc(summ.get('files_count'))}</li>
    <li>Total LOC: {esc(summ.get('total_loc'))} | Avg LOC/file: {esc(summ.get('avg_loc'))} | Max LOC/file: {esc(summ.get('max_file_loc'))}</li>
    <li>Files over limit: {esc(len(summ.get('files_over_limit') or []))}</li>
  </ul>
  <h3>CC Rank Distribution</h3>
  <table><thead><tr><th>Rank</th><th>Count</th></tr></thead><tbody>{rank_rows}</tbody></table>
  <p>CC means: avg={esc(cc.get('cc_avg_mean'))}, max={esc(cc.get('cc_max_mean'))}</p>
  <h3>Worst by CC Max (Top 10)</h3>
  <table><thead><tr><th>Path</th><th>CC Max</th><th>Rank</th><th>LOC</th></tr></thead><tbody>{worst_cc_rows}</tbody></table>

  <h3>Maintainability Index</h3>
  <p>MI mean={esc(mi.get('mean'))}, min={esc(mi.get('min'))}, max={esc(mi.get('max'))}</p>
  <table><thead><tr><th>Bucket</th><th>Count</th></tr></thead><tbody>{mi_dist_rows}</tbody></table>
  <h3>Worst by MI (Bottom 10)</h3>
  <table><thead><tr><th>Path</th><th>MI</th><th>LOC</th></tr></thead><tbody>{worst_mi_rows}</tbody></table>
"""
        except Exception:
            cpx_html = ""

    # Load component tests
    comp_path = artifacts_dir / "component_tests.json"
    comp_html = ""
    if comp_path.exists():
        try:
            cdata = json.loads(comp_path.read_text(encoding="utf-8"))
            summ = cdata.get("summary", {})
            comps = cdata.get("components", [])
            rows_comp = []
            for c in comps:
                st = c.get("status")
                color = "#0a0" if st == "green" else ("#c00" if st == "red" else "#999")
                rows_comp.append(
                    f"<tr><td>{esc(c.get('name'))}</td>"
                    f"<td>{esc('yes' if c.get('deps_stub_free') else 'no')}</td>"
                    f"<td>{esc(c.get('tests_total'))}</td>"
                    f"<td>{esc(c.get('tests_failed'))}</td>"
                    f"<td style='color:{color};font-weight:600'>{esc(st)}</td>"
                    f"<td><code>{esc(c.get('tests_dir'))}</code></td></tr>"
                )
            comp_html = f"""
  <h2>Component Tests</h2>
  <ul>
    <li>Components (total): {esc(summ.get('components_total'))}</li>
    <li>Components (deps stub-free): {esc(summ.get('components_dep_stub_free'))}</li>
    <li>Green among deps stub-free: {esc(summ.get('components_dep_stub_free_green'))}</li>
  </ul>
  <table>
    <thead><tr><th>Component</th><th>Deps Stub-Free</th><th>Tests</th><th>Failed</th><th>Status</th><th>Tests Dir</th></tr></thead>
    <tbody>{''.join(rows_comp)}</tbody>
  </table>
"""
        except Exception:
            comp_html = ""

    html = f"""
<!doctype html>
<html><head><meta charset='utf-8'><title>CodeClinic QA Report</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif; padding:16px;}}
.status{{font-weight:700; color:{'green' if status=='passed' else 'crimson'};}}
table{{border-collapse:collapse; width:100%;}}
th,td{{border:1px solid #ccc; padding:6px 8px; text-align:left;}}
</style></head>
<body>
  <h1>CodeClinic QA Report</h1>
  <p>Status: <span class='status'>{esc(status)}</span></p>
  <p>Failed Gates: {esc(', '.join(gates) or 'None')}</p>
  <h2>Metrics</h2>
  <table>
    <thead><tr><th>Name</th><th>Provider</th><th>Status</th><th>Artifact</th></tr></thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  {cpx_html}
  {comp_html}
  <p>Summary JSON: <code>{esc(str(out_dir / 'summary.json'))}</code></p>
</body></html>
"""
    html_path.write_text(html, encoding="utf-8")


def _write_pre_commit() -> Path:
    p = Path(".pre-commit-config.yaml")
    content = """
repos:
  - repo: https://github.com/psf/black
    rev: 23.7.0
    hooks:
      - id: black
        args: ["--line-length=88"]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.8
    hooks:
      - id: ruff
        args: ["--fix"]
      - id: ruff-format
""".lstrip()
    p.write_text(content, encoding="utf-8")
    return p


# -------- extensions: function metrics / doc contracts / exports ---------

import ast as _ast_ext
from typing import Any as _Any


def _ext_collect_files(cfg: QAConfig) -> list[str]:
    return _collect_py_files(cfg.tool.paths, cfg.tool.include, cfg.tool.exclude)


def _ext_is_public(name: str) -> bool:
    return not name.startswith('_') and name != '__init__'


def _ext_max_nesting(node: _ast_ext.AST) -> int:
    blockers = (_ast_ext.If, _ast_ext.For, _ast_ext.AsyncFor, _ast_ext.While, _ast_ext.With, _ast_ext.AsyncWith, _ast_ext.Try, _ast_ext.IfExp)
    def _d(n: _ast_ext.AST, cur: int = 0) -> int:
        if isinstance(n, blockers):
            cur += 1
        m = cur
        for c in _ast_ext.iter_child_nodes(n):
            m = max(m, _d(c, cur))
        return m
    md = 0
    for st in getattr(node, 'body', []):
        md = max(md, _d(st, 0))
    return md


def _ext_function_metrics(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    files = _ext_collect_files(cfg)
    gates = cfg.gates
    loc_thr = int(getattr(gates, 'fn_loc_max', 0) or 0)
    args_thr = int(getattr(gates, 'fn_args_max', 0) or 0)
    nest_thr = int(getattr(gates, 'fn_nesting_max', 0) or 0)
    count_doc = bool(getattr(gates, 'fn_count_docstrings', True))
    violations: list[dict[str, _Any]] = []
    per_file: list[dict[str, _Any]] = []
    for f in files:
        try:
            src = Path(f).read_text(encoding='utf-8')
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        funs: list[dict[str, _Any]] = []
        for node in [n for n in _ast_ext.walk(tree) if isinstance(n, (_ast_ext.FunctionDef, _ast_ext.AsyncFunctionDef))]:
            name = getattr(node, 'name', '')
            if not _ext_is_public(name):
                continue
            try:
                start_line = node.lineno
                if not count_doc:
                    # 跳过函数首个 docstring 的行数
                    body = getattr(node, 'body', []) or []
                    if body:
                        first = body[0]
                        # py>=3.8: Constant
                        is_doc = False
                        try:
                            import ast as _ast
                            is_doc = isinstance(first, _ast.Expr) and isinstance(getattr(first, 'value', None), _ast.Constant) and isinstance(first.value.value, str)
                        except Exception:
                            is_doc = False
                        if is_doc:
                            end_doc = getattr(first, 'end_lineno', getattr(first, 'lineno', start_line))
                            start_line = int(end_doc) + 1
                end_line = (getattr(node, 'end_lineno', None) or node.lineno)
                loc = int(end_line) - int(start_line) + 1
            except Exception:
                loc = None
            args_cnt = len(getattr(node, 'args', None).args or []) + len(getattr(node, 'args', None).kwonlyargs or [])
            nesting = _ext_max_nesting(node)
            funs.append({'name': name, 'lineno': node.lineno, 'loc': loc, 'args': args_cnt, 'nesting': nesting})
            viol = {'file': f, 'name': name, 'lineno': node.lineno}
            tagged = False
            if loc_thr and isinstance(loc, int) and loc > loc_thr:
                viol['loc'] = loc; tagged = True
            if args_thr and args_cnt > args_thr:
                viol['args'] = args_cnt; tagged = True
            if nest_thr and nesting > nest_thr:
                viol['nesting'] = nesting; tagged = True
            if tagged:
                violations.append(viol)
        per_file.append({'file': f, 'functions': funs})
    report = artifacts_dir / 'function_metrics.json'
    report.write_text(json.dumps({'violations': violations, 'files': per_file}, ensure_ascii=False, indent=2), encoding='utf-8')
    return len(violations), report


def _ext_doc_contracts(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    files = _ext_collect_files(cfg)
    stub_decorators = set(getattr(cfg.tools.stubs, 'decorator_names', ['stub']))
    missing: list[dict[str, _Any]] = []
    for f in files:
        try:
            src = Path(f).read_text(encoding='utf-8')
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        file_missing: list[dict[str, _Any]] = []
        for node in [n for n in _ast_ext.walk(tree) if isinstance(n, (_ast_ext.FunctionDef, _ast_ext.AsyncFunctionDef))]:
            # detect stub by decorator names
            decos = []
            for d in getattr(node, 'decorator_list', []) or []:
                if isinstance(d, _ast_ext.Name): decos.append(d.id)
                elif isinstance(d, _ast_ext.Attribute): decos.append(d.attr)
            if not any(d in stub_decorators for d in decos):
                continue
            doc = _ast_ext.get_docstring(node) or ''
            # 强制要求五要素：功能概述/前置条件/后置条件/不变量/副作用
            required = ['功能概述', '前置条件', '后置条件', '不变量', '副作用']
            if not doc.strip():
                file_missing.append({'name': node.name, 'lineno': node.lineno, 'reason': 'no_doc'})
            else:
                if not all(kw in doc for kw in required):
                    file_missing.append({'name': node.name, 'lineno': node.lineno, 'reason': 'missing_sections', 'required': required})
        if file_missing:
            missing.append({'file': f, 'missing': file_missing})
    report = artifacts_dir / 'doc_contracts.json'
    report.write_text(json.dumps({'stub_missing': missing}, ensure_ascii=False, indent=2), encoding='utf-8')
    total_missing = sum(len(item.get('missing', [])) for item in missing)
    return total_missing, report


def _ext_exports(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    paths = cfg.tool.paths
    priv_list: list[dict[str, _Any]] = []
    for root in paths:
        base = Path(root)
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            if '__init__.py' in filenames:
                initp = Path(dirpath) / '__init__.py'
                try:
                    tree = _ast_ext.parse(initp.read_text(encoding='utf-8'))
                except Exception:
                    continue
                priv: list[str] = []
                for node in tree.body:
                    if isinstance(node, _ast_ext.Assign):
                        for target in node.targets:
                            if isinstance(target, _ast_ext.Name) and target.id == '__all__':
                                if isinstance(node.value, (_ast_ext.List, _ast_ext.Tuple)):
                                    for elt in node.value.elts:
                                        if isinstance(elt, _ast_ext.Str):
                                            name = elt.s
                                            if name.startswith('_'):
                                                priv.append(name)
                if priv:
                    priv_list.append({'package_init': str(initp), 'private_exports': priv})
    report = artifacts_dir / 'exports.json'
    report.write_text(json.dumps({'private_exports': priv_list}, ensure_ascii=False, indent=2), encoding='utf-8')
    count = sum(len(item.get('private_exports', [])) for item in priv_list)
    return count, report


def _write_github_actions() -> Path:
    wf_dir = Path(".github/workflows")
    wf_dir.mkdir(parents=True, exist_ok=True)
    p = wf_dir / "codeclinic-qa.yml"
    content = """
name: CodeClinic QA
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e .
          pip install black ruff mypy pytest coverage radon pyyaml
      - name: Run CodeClinic QA
        run: |
          codeclinic qa run
      - name: Upload QA artifacts
        uses: actions/upload-artifact@v4
        with:
          name: codeclinic-qa
          path: build/codeclinic
""".lstrip()
    p.write_text(content, encoding="utf-8")
    return p


def _write_makefile() -> Path:
    p = Path("Makefile")
    content = """
.PHONY: qa-init qa-run qa-fix

qa-init:
	codeclinic qa init

qa-run:
	codeclinic qa run

qa-fix:
	codeclinic qa fix
""".lstrip()
    p.write_text(content, encoding="utf-8")
    return p
