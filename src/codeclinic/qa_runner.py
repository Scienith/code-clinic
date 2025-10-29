from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .qa_config import (
    QAConfig,
    _strict_template_or_default,
    load_qa_config,
    write_qa_config,
)


def qa_init(force: bool = False) -> None:
    # Always write/update root config for backward-compat
    target = write_qa_config("codeclinic.yaml", force=force)
    if target.name.endswith(".qa.example.yaml"):
        print(f"⚠ 检测到已有 codeclinic.yaml，示例已生成: {target}")
        print("   请按需合并 QA 配置段落到现有文件。")
    else:
        print(f"✓ 已生成 QA 配置: {target}")

    # Additionally scaffold codeclinic/ folder with wrapper + colocated yaml
    try:
        from pathlib import Path as _P

        proj = _P.cwd()
        cc_dir = proj / "codeclinic"
        cc_dir.mkdir(parents=True, exist_ok=True)
        # Write colocated YAML using strict template
        (cc_dir / "codeclinic.yaml").write_text(
            _strict_template_or_default(), encoding="utf-8"
        )
        # Write wrapper script from packaged template
        try:
            from importlib.resources import files as _files  # type: ignore
        except Exception:
            _files = None  # type: ignore
        wrapper_text = None
        if _files is not None:
            try:
                wrapper_text = (
                    _files(__package__) / "templates" / "codeclinic.sh"
                ).read_text(encoding="utf-8")
            except Exception:
                wrapper_text = None
        if not wrapper_text:
            # Fallback to filesystem
            try:
                wrapper_text = (
                    _P(__file__).parent / "templates" / "codeclinic.sh"
                ).read_text(encoding="utf-8")
            except Exception:
                wrapper_text = None
        if wrapper_text:
            wrapper_path = cc_dir / "codeclinic.sh"
            wrapper_path.write_text(wrapper_text, encoding="utf-8")
            try:
                import os as _os

                _os.chmod(wrapper_path, 0o755)
            except Exception:
                pass
        print(f"✓ 已生成 codeclinic/ 包装与配置: {cc_dir}")
        print("   - 运行质检: codeclinic/codeclinic.sh qa run")
        print("   - 自动修复: codeclinic/codeclinic.sh qa fix")
    except Exception as e:
        _ = e
        # non-fatal


def qa_run(
    config_path: str = "codeclinic.yaml", output_override: Optional[str] = None
) -> int:
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
    test_status, test_log, cov_pct, cov_xml, junit_xml = _run_pytest_coverage(
        cfg, logs_dir, artifacts_dir, out_dir
    )
    results["logs"]["pytest"] = test_log
    results["metrics"]["tests"] = {
        "provider": cfg.tools.tests.provider,
        "coverage_percent": cov_pct,
        "coverage_xml": cov_xml,
        "status": test_status,
    }

    # Provider: complexity (radon if available; fallback to builtin LOC)
    cpx_status, cpx_log, cpx_json, cpx_summary = _run_complexity(
        cfg, logs_dir, artifacts_dir
    )
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
    comp_report, comp_summary = _aggregate_component_tests(
        cfg, artifacts_dir, project_data, {}, junit_xml
    )
    results["metrics"]["component_tests"] = {
        "provider": "pytest+junit",
        "components_total": comp_summary.get("components_total"),
        "components_dep_stub_free": comp_summary.get("components_dep_stub_free"),
        "components_dep_stub_free_green": comp_summary.get(
            "components_dep_stub_free_green"
        ),
        "report": str(comp_report) if comp_report else None,
        "status": (
            "passed" if comp_summary.get("gate_failed_count", 0) == 0 else "failed"
        ),
    }

    # Extensions: function metrics, stub doc contracts, exports, private symbol imports
    fn_over_count, fn_report = _ext_function_metrics(cfg, artifacts_dir)
    stub_missing_count, docs_report = _ext_doc_contracts(cfg, artifacts_dir)
    private_exports_count, exports_report = _ext_exports(cfg, artifacts_dir)
    missing_nonempty_all_count, exports_all_report = _ext_exports_require_nonempty_all(
        cfg, artifacts_dir
    )
    privsym_count, privsym_report = _ext_private_symbol_imports(cfg, artifacts_dir)
    # New: fail-fast checks, public exports side-effects, import cycles, JUnit failure types, stubs NotImplemented
    ff_count, ff_report = _ext_failfast(cfg, artifacts_dir)
    pubse_count, pubse_report = _ext_public_no_side_effects(cfg, artifacts_dir)
    cycles_count, cycles_report = _ext_import_cycles(cfg, artifacts_dir, project_data)
    notimpl_count, notimpl_report = _ext_stubs_no_notimplemented(cfg, artifacts_dir)
    # New: validate_call runtime validation
    rv_missing, rv_order_warn, rv_report = _ext_runtime_validate_call(
        cfg, artifacts_dir
    )
    junit_failures, junit_errors = _ext_junit_failure_types(
        results.get("metrics", {}).get("tests", {}).get("coverage_xml"),
        artifacts_dir,
        results.get("logs", {}).get("pytest"),
    )
    # Classes: super().__init__ in subclass __init__
    superinit_missing, superinit_report = _ext_classes_require_super_init(
        cfg, artifacts_dir
    )
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
        "missing_nonempty_all": missing_nonempty_all_count,
        "report": str(exports_report) if exports_report else None,
        "report_all": str(exports_all_report) if exports_all_report else None,
        "status": "passed" if private_exports_count == 0 else "failed",
    }
    results["metrics"]["imports_private_symbols"] = {
        "violations": privsym_count,
        "report": str(privsym_report) if privsym_report else None,
        "status": "passed" if privsym_count == 0 else "failed",
    }
    results["metrics"]["failfast"] = {
        "violations": ff_count,
        "report": str(ff_report) if ff_report else None,
        "status": "passed" if ff_count == 0 else "failed",
    }
    results["metrics"]["public_exports"] = {
        "violations": pubse_count,
        "report": str(pubse_report) if pubse_report else None,
        "status": "passed" if pubse_count == 0 else "failed",
    }
    results["metrics"]["import_cycles"] = {
        "violations": cycles_count,
        "report": str(cycles_report) if cycles_report else None,
        "status": "passed" if cycles_count == 0 else "failed",
    }
    results["metrics"]["stubs_notimplemented"] = {
        "violations": notimpl_count,
        "report": str(notimpl_report) if notimpl_report else None,
        "status": "passed" if notimpl_count == 0 else "failed",
    }
    results["metrics"]["runtime_validation"] = {
        "missing": rv_missing,
        "order_warnings": rv_order_warn,
        "report": str(rv_report) if rv_report else None,
        "status": (
            "passed"
            if (rv_missing == 0 and rv_order_warn == 0)
            else "failed"
        ),
    }
    results["metrics"]["tests_junit_types"] = {
        "failures": junit_failures,
        "errors": junit_errors,
        "status": "passed" if (junit_errors or 0) == 0 else "failed",
    }
    results["metrics"]["classes_super_init"] = {
        "missing": superinit_missing,
        "report": str(superinit_report) if superinit_report else None,
        "status": "passed" if superinit_missing == 0 else "failed",
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
    if (
        deps_metrics.get("violations") is not None
        and deps_metrics["violations"] > g.import_violations_max
    ):
        gates_failed.append("import_violations_max")
    # 按要求：移除 stub 比例门禁
    # Complexity gates
    max_loc = cpx_summary.get("max_file_loc") if cpx_summary else None
    if isinstance(max_loc, int) and max_loc > g.max_file_loc:
        gates_failed.append("max_file_loc")
    # 仅当使用radon并且配置了阈值时检查 CC/MI 门禁
    comp_provider = (
        (cpx_summary or {}).get("provider") if isinstance(cpx_summary, dict) else None
    )
    if comp_provider == "radon":
        # CC 等级门禁：不允许出现比阈值更差的等级（A最好、F最差）
        if g.cc_max_rank_max:
            try:
                worst_list = (cpx_summary.get("worst") or {}).get("by_cc_max") or []
                # 取最差一个的等级；如果列表为空则回退到分布
                if worst_list:
                    worst_rank = str(worst_list[0].get("cc_max_rank", "")).upper()
                else:
                    dist = (cpx_summary.get("cc") or {}).get(
                        "cc_rank_distribution"
                    ) or {}
                    # 从最差到最好查找
                    order = ["F", "E", "D", "C", "B", "A"]
                    worst_rank = next((r for r in order if dist.get(r, 0) > 0), None)
                if worst_rank:
                    order_map = {
                        k: i
                        for i, k in enumerate(["A", "B", "C", "D", "E", "F"], start=1)
                    }
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
                mi_min = (cpx_summary.get("mi") or {}).get("min", None)
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
            results.setdefault("metrics", {}).setdefault("packages_integrity", {})[
                "missing_init"
            ] = missing_init
            gates_failed.append("packages_require_dunder_init")

    # Modules require named tests gate
    if cfg.gates.modules_require_named_tests:
        missing_tests, presence_report = _check_modules_require_named_tests(
            cfg, project_data, artifacts_dir
        )
        results.setdefault("metrics", {}).setdefault("tests_presence", {})[
            "missing_named_tests"
        ] = missing_tests
        results["metrics"]["tests_presence"]["report"] = str(presence_report)
        if missing_tests:
            gates_failed.append("modules_require_named_tests")

    # Extension gates
    try:
        thr = int(getattr(g, "doc_contracts_missing_max", 0) or 0)
        if stub_missing_count > thr:
            gates_failed.append("doc_contracts_missing_max")
    except Exception:
        pass
    if any(
        (
            getattr(g, "fn_loc_max", 0),
            getattr(g, "fn_args_max", 0),
            getattr(g, "fn_nesting_max", 0),
        )
    ):
        if fn_over_count > 0:
            gates_failed.append("function_metrics_over_threshold")
    if bool(getattr(g, "exports_no_private", False)) and private_exports_count > 0:
        gates_failed.append("exports_no_private")
    if (
        bool(getattr(g, "exports_require_nonempty_all", False))
        and missing_nonempty_all_count > 0
    ):
        gates_failed.append("exports_require_nonempty_all")
    if bool(getattr(g, "imports_forbid_private_symbols", False)) and privsym_count > 0:
        gates_failed.append("imports_forbid_private_symbols")
    # New gates
    if (
        any(
            [
                (
                    g.failfast_forbid_dict_get_default
                    or g.failfast_forbid_getattr_default
                    or g.failfast_forbid_env_default
                    or g.failfast_forbid_import_fallback
                    or getattr(g, "failfast_forbid_attr_fallback", False)
                    or getattr(g, "failfast_forbid_key_fallback", False)
                )
            ]
        )
        and ff_count > 0
    ):
        gates_failed.append("failfast")
    try:
        cyc_thr = int(getattr(g, "imports_cycles_max", 0))
        if cyc_thr >= 0 and cycles_count > cyc_thr:
            gates_failed.append("imports_cycles_max")
    except Exception:
        pass
    if bool(getattr(g, "packages_public_no_side_effects", False)) and pubse_count > 0:
        gates_failed.append("packages_public_no_side_effects")
    if bool(getattr(g, "stubs_no_notimplemented_non_abc", False)) and notimpl_count > 0:
        gates_failed.append("stubs_no_notimplemented_non_abc")
    if (
        bool(getattr(g, "tests_red_failures_are_assertions", False))
        and (junit_errors or 0) > 0
    ):
        gates_failed.append("tests_red_failures_are_assertions")
    if bool(getattr(g, "classes_require_super_init", False)) and (
        superinit_missing > 0
    ):
        gates_failed.append("classes_require_super_init")
    # Runtime validation gates
    if bool(getattr(g, "runtime_validation_require_validate_call", False)) and (
        rv_missing > 0
    ):
        gates_failed.append("runtime_validation_require_validate_call")
    if bool(getattr(g, "runtime_validation_require_innermost", False)) and (
        rv_order_warn > 0
    ):
        gates_failed.append("runtime_validation_require_innermost")

    results["gates_failed"] = gates_failed
    results["status"] = "passed" if not gates_failed else "failed"

    # Write summary.json
    (out_dir / "summary.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
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
    # black (single-source): use ephemeral config to avoid repo-level configs
    logs_dir = Path(cfg.tool.output) / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    black_cfg = logs_dir / "black.generated.toml"
    try:
        black_cfg.write_text(
            "[tool.black]\n" f"line-length = {cfg.tools.formatter.line_length}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    black_args = [
        "black",
        "--config",
        str(black_cfg),
        f"--line-length={cfg.tools.formatter.line_length}",
    ] + cfg.tool.paths
    code, _ = _call(black_args)
    codes.append(code)

    # ruff (single-source): ephemeral config
    ruff_cfg = logs_dir / "ruff.generated.toml"
    try:
        content: list[str] = [
            f"line-length = {cfg.tools.linter.line_length}",
        ]
        # Optional ignore list from YAML
        try:
            ignores = list(getattr(cfg.tools.linter, "ignore", []) or [])
        except Exception:
            ignores = []
        if ignores:
            joined = ", ".join(f'"{c}"' for c in ignores)
            content += ["[lint]", f"ignore = [{joined}]"]
        conv = getattr(cfg.tools.linter, "docstyle_convention", None)
        if conv:
            content += ["[lint.pydocstyle]", f'convention = "{conv}"']
        ruff_cfg.write_text("\n".join(content) + "\n", encoding="utf-8")
    except Exception:
        pass
    ruff_args = ["ruff", "check", "--config", str(ruff_cfg), "--fix"]
    if cfg.tools.linter.ruleset:
        for r in cfg.tools.linter.ruleset:
            ruff_args += ["--select", r]
    ruff_args += [f"--line-length={cfg.tools.linter.line_length}"]
    # Mirror ignore list on CLI to ensure precedence regardless of Ruff version/config parsing
    try:
        _ignores = list(getattr(cfg.tools.linter, "ignore", []) or [])
        for _c in _ignores:
            ruff_args += ["--ignore", str(_c)]
    except Exception:
        pass
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
    # Ephemeral Black config to avoid picking up repo-level config files
    black_cfg = logs_dir / "black.generated.toml"
    try:
        black_cfg.write_text(
            "[tool.black]\n" f"line-length = {cfg.tools.formatter.line_length}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    args = [
        "black",
        "--check",
        "--config",
        str(black_cfg),
        f"--line-length={cfg.tools.formatter.line_length}",
        *cfg.tool.paths,
    ]
    code, out = _call(args)
    log_path.write_text(out, encoding="utf-8")
    return ("passed" if code == 0 else "failed", str(log_path), code == 0)


def _run_ruff_check(cfg: QAConfig, logs_dir: Path) -> Tuple[str, str, Optional[int]]:
    if cfg.tools.linter.provider != "ruff":
        return ("skipped", "", None)
    log_path = logs_dir / "ruff.log"
    # Build an ephemeral Ruff config to enforce single-source settings
    ruff_cfg = logs_dir / "ruff.generated.toml"
    try:
        lines: list[str] = [
            f"line-length = {cfg.tools.linter.line_length}",
        ]
        # Optional ignore list configured via YAML
        try:
            ignores = list(getattr(cfg.tools.linter, "ignore", []) or [])
        except Exception:
            ignores = []
        if ignores:
            joined = ", ".join(f'"{c}"' for c in ignores)
            lines += ["[lint]", f"ignore = [{joined}]"]
        conv = getattr(cfg.tools.linter, "docstyle_convention", None)
        if conv:
            lines += [
                "[lint.pydocstyle]",
                f'convention = "{conv}"',
            ]
        ruff_cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass
    args = ["ruff", "check", "--config", str(ruff_cfg)]
    if cfg.tools.linter.ruleset:
        for r in cfg.tools.linter.ruleset:
            args += ["--select", r]
    args += [f"--line-length={cfg.tools.linter.line_length}"]
    # Mirror ignore list on CLI to ensure precedence regardless of Ruff version/config parsing
    try:
        _ignores = list(getattr(cfg.tools.linter, "ignore", []) or [])
        for _c in _ignores:
            args += ["--ignore", str(_c)]
    except Exception:
        pass
    args += cfg.tool.paths
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
    # Always use an ephemeral mypy config to avoid picking up repo-level configs
    mypy_cfg = logs_dir / "mypy.generated.ini"
    try:
        strict = bool(getattr(cfg.tools.typecheck, "strict", True))
        lines: list[str] = [
            "[mypy]",
            "pretty = True",
            "show_error_codes = True",
            "namespace_packages = True",
        ]
        if strict:
            lines += [
                "disallow_untyped_defs = True",
                "disallow_incomplete_defs = True",
                "no_implicit_optional = True",
                "warn_redundant_casts = True",
                "warn_unused_ignores = True",
                "warn_return_any = True",
                "check_untyped_defs = True",
            ]
        # Map tool.exclude to a robust mypy exclude regex (segment-based)
        try:
            ex_globs = list(getattr(cfg.tool, 'exclude', []) or [])
            segments = set()
            for g in ex_globs:
                s = str(g)
                for name in ('tests', '.venv', 'venv', '__pycache__', 'build', 'dist', 'migrations'):
                    if f'/{name}/' in s or s.startswith(name) or s.endswith(name):
                        segments.add(name)
            if segments:
                seg_alt = '|'.join(name.replace('.', '\\.') for name in sorted(segments))
                rx = f'(?:^|.*/)(?:{seg_alt})/'
                lines += [f'exclude = {rx}']
        except Exception:
            pass
# Per-module ignore_missing_imports sections
        try:
            patterns = list(getattr(cfg.tools.typecheck, "ignore_missing_imports", []) or [])
        except Exception:
            patterns = []
        for pat in patterns:
            lines += [f"[mypy-{pat}]", "ignore_missing_imports = True"]
        mypy_cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass
    args += ["--config-file", str(mypy_cfg)]
    if cfg.tools.typecheck.strict:
        args.append("--strict")
    code, out = _call(args)
    log_path.write_text(out, encoding="utf-8")
    errors = _count_mypy_errors(out) if code != 0 else 0
    return ("passed" if code == 0 else "failed", str(log_path), errors)


def _run_pytest_coverage(
    cfg: QAConfig, logs_dir: Path, artifacts_dir: Path, out_dir: Path
) -> Tuple[str, str, Optional[int], Optional[str], Optional[str]]:
    # Always require coverage+pytest; absence should cause failure via return code

    # Normal coverage path

    log_path = logs_dir / "pytest.log"
    cov_xml = artifacts_dir / "coverage.xml"
    # Ensure junit target path
    junit_xml_path: Optional[Path] = None
    if cfg.tools.tests.junit.enabled:
        # 统一将 JUnit 报告写到 <output>/artifacts/junit.xml，不再依赖配置中的路径
        junit_xml_path = out_dir / "artifacts" / "junit.xml"
        junit_xml_path.parent.mkdir(parents=True, exist_ok=True)
    # Run tests
    # Use the current interpreter to guarantee the same venv/site-packages
    # Generate an ephemeral coverage config from codeclinic.yaml settings (single-source)
    cov_rc = logs_dir / "coveragerc.generated"
    try:
        excl_patterns = list(cfg.tool.exclude or [])
        # Always omit tests/ and virtualenv caches if not already present
        defaults = ["**/tests/**", "**/.venv/**", "**/venv/**", "**/__pycache__/**"]
        for d in defaults:
            if d not in excl_patterns:
                excl_patterns.append(d)
        # Convert globs to coverage omit-style patterns (keep as-is)
        lines = ["[run]", "branch = True", "source = "]
        for p in cfg.tool.paths:
            lines.append(f"    {p}")
        lines += ["omit ="]
        for pat in excl_patterns:
            lines.append(f"    {pat}")
        cov_rc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        # best-effort; fallback to defaults
        pass

    # Ephemeral pytest.ini to avoid picking up repo-level pytest config
    pytest_cfg = logs_dir / "pytest.generated.ini"
    try:
        pytest_cfg.write_text("[pytest]\n", encoding="utf-8")
    except Exception:
        pass
    # Ensure coverage data (.coverage) is written under the output directory
    try:
        import os as _os_env

        _os_env.environ["COVERAGE_FILE"] = str(out_dir / ".coverage")
    except Exception:
        pass

    data_file = str(out_dir / ".coverage")
    pytest_cmd = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        f"--data-file={data_file}",
        "--rcfile",
        str(cov_rc),
        "-m",
        "pytest",
        "-c",
        str(pytest_cfg),
        *cfg.tools.tests.args,
    ]
    if junit_xml_path is not None:
        pytest_cmd += ["--junitxml", str(junit_xml_path)]
    code_run, out_run = _call(pytest_cmd)
    # Produce coverage xml regardless of test status to capture partial results
    cov_xml_cmd = [
        "coverage",
        "xml",
        "-o",
        str(cov_xml),
        "--rcfile",
        str(cov_rc),
        f"--data-file={data_file}",
    ]
    _ = _call(cov_xml_cmd)[0]
    cov_pct = _parse_coverage_percent(cov_xml) if cov_xml.exists() else None
    combined = out_run
    log_path.write_text(combined, encoding="utf-8")
    status = "passed" if code_run == 0 else "failed"
    return (
        status,
        str(log_path),
        cov_pct,
        str(cov_xml) if cov_xml.exists() else None,
        str(junit_xml_path) if junit_xml_path else None,
    )


def _run_internal_analyses(
    cfg: QAConfig, artifacts_dir: Path
) -> Tuple[Dict[str, Any], Any]:
    # Prepare minimal adapter to existing collector
    from .data_collector import collect_project_data
    from .stub_analysis import analyze_stub_completeness, save_stub_report
    from .violations_analysis import analyze_violations, save_violations_report

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

    # Stub 明细报表：仅生成每模块/包的明细与热力图，不产出项目级聚合与门禁
    try:
        from .stub_analysis import (
            _generate_stub_heatmap,
            _prepare_stub_json_data,
            analyze_stub_completeness,
        )

        sdata = analyze_stub_completeness(project_data)
        # 写明细 JSON
        stub_dir = artifacts_dir / "stub_completeness"
        stub_dir.mkdir(parents=True, exist_ok=True)
        json_path = stub_dir / "stub_summary.json"
        json_data = _prepare_stub_json_data(sdata, project_data)
        (stub_dir / "stub_summary.json").write_text(
            json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # 生成热力图
        # 控制是否在热力图用红/绿边框标识模块测试状态
        _generate_stub_heatmap(
            sdata,
            project_data,
            stub_dir,
            show_test_borders=cfg.visuals.show_test_status_borders,
        )
    except Exception as e:
        # do not fail the run due to reporting errors
        _ = e
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
    return sum(
        1
        for line in output.splitlines()
        if ":" in line and line.strip() and not line.startswith(" ")
    )


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


def _run_complexity(
    cfg: QAConfig, logs_dir: Path, artifacts_dir: Path
) -> Tuple[str, str, Optional[str], Dict[str, Any]]:
    log_path = logs_dir / "complexity.log"
    report_path = artifacts_dir / "complexity.json"

    files = _collect_py_files(cfg.tool.paths, cfg.tool.include, cfg.tool.exclude)
    used_radon = True

    file_results: List[Dict[str, Any]] = []
    max_file_loc = 0
    over_limit: List[str] = []

    # Require radon; if not present, ImportError will bubble up and fail the run
    from radon.complexity import cc_rank, cc_visit  # type: ignore
    from radon.metrics import mi_visit  # type: ignore
    from radon.raw import analyze as radon_analyze  # type: ignore

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
        file_results.append(
            {
                "path": f,
                "loc": loc,
                "sloc": sloc,
                "lloc": lloc,
                "mi": round(float(mi), 2) if mi is not None else None,
                "cc_avg": round(float(cc_avg), 2),
                "cc_max": round(float(cc_max), 2),
                "cc_max_rank": cc_rank_max,
            }
        )
        max_file_loc = max(max_file_loc, loc)
        if loc > cfg.gates.max_file_loc:
            over_limit.append(f)
        lines_log.append(
            f"[ok] {f}: loc={loc} mi={mi:.2f} cc_avg={cc_avg:.2f} cc_max={cc_max:.2f}({cc_rank_max})"
        )

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
        key=lambda x: x["cc_max"],
        reverse=True,
    )[:10]
    worst_mi_files = sorted(
        [fr for fr in file_results if fr.get("mi") is not None], key=lambda x: x["mi"]
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
            "cc_max_mean": (
                round(sum(cc_max_values) / len(cc_max_values), 2)
                if cc_max_values
                else None
            ),
            "cc_avg_mean": (
                round(sum(cc_avg_values) / len(cc_avg_values), 2)
                if cc_avg_values
                else None
            ),
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
                {
                    "path": fr["path"],
                    "cc_max": fr["cc_max"],
                    "cc_max_rank": fr.get("cc_max_rank"),
                    "loc": fr.get("loc"),
                }
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
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log_path.write_text("\n".join(lines_log), encoding="utf-8")

    status = "passed" if not over_limit else "failed"
    return status, str(log_path), str(report_path), summary


def _collect_py_files(
    paths: List[str], include: List[str], exclude: List[str]
) -> List[str]:
    import fnmatch
    import os

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
                if not fn.endswith(".py"):
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
                junit_cases.append(
                    {
                        "file": fpath,
                        "classname": case.get("classname") or "",
                        "status": status,
                    }
                )
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
        status = (
            "green"
            if total > 0 and failed == 0
            else ("missing" if total == 0 else "red")
        )

        comps.append(
            {
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
            }
        )

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
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report_path, summary


def _check_packages_require_dunder_init(cfg: QAConfig) -> List[str]:
    missing: List[str] = []
    excludes = list(getattr(cfg.gates, "packages_missing_init_exclude", []) or [])
    import fnmatch

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
            # exclude by patterns (absolute and best-effort relative)
            path_str = str(dpath)
            rel_str = path_str
            try:
                rel_str = str(dpath.relative_to(Path.cwd()))
            except Exception:
                pass
            if any(
                fnmatch.fnmatch(path_str, pat) or fnmatch.fnmatch(rel_str, pat)
                for pat in excludes
            ):
                continue
            py_files = [f for f in filenames if f.endswith(".py")]
            if py_files:
                if not (dpath / "__init__.py").exists():
                    missing.append(str(dpath))
    return missing


def _check_modules_require_named_tests(
    cfg: QAConfig, project_data: Any, artifacts_dir: Path
) -> Tuple[List[str], Path]:
    """Ensure every in-package module has a matching tests/test_<module>.py file.
    Only applies to modules inside packages (i.e., node.parent is not None)."""
    missing: List[str] = []
    tests_dir_name = cfg.components.tests_dir_name
    import fnmatch

    excludes = list(getattr(cfg.gates, "modules_named_tests_exclude", []) or [])
    for name, node in project_data.modules.items():
        # Skip top-level modules (not inside package)
        if not getattr(node, "parent", None):
            continue
        mod_path = Path(node.file_path)
        if mod_path.name == "__init__.py":
            continue
        # Exclude by glob patterns (supports absolute or relative-like matching)
        path_str = str(mod_path)
        rel_str = path_str
        try:
            # best-effort relative to CWD
            rel_str = str(mod_path.relative_to(Path.cwd()))
        except Exception:
            pass
        skip = any(
            fnmatch.fnmatch(path_str, pat) or fnmatch.fnmatch(rel_str, pat)
            for pat in excludes
        )
        if skip:
            continue
        tests_dir = mod_path.parent / tests_dir_name
        expected = tests_dir / f"test_{mod_path.stem}.py"
        if not expected.exists():
            missing.append(name)

    report_path = Path(artifacts_dir) / "module_tests_presence.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"version": "1.0", "missing_named_tests": missing}
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
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
        rows.append(
            f"<tr><td>{esc(name)}</td><td>{esc(provider)}</td><td>{esc(st)}</td><td>{esc(report or '')}</td></tr>"
        )

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
                f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>"
                for k, v in (cc.get("cc_rank_distribution") or {}).items()
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


# pre-commit scaffolding intentionally not provided by CodeClinic


# Removed per-tool persistent config scaffolding to enforce single-source (codeclinic.yaml)


# -------- extensions: function metrics / doc contracts / exports ---------

import ast as _ast_ext
from typing import Any as _Any


def _ext_collect_files(cfg: QAConfig) -> list[str]:
    return _collect_py_files(cfg.tool.paths, cfg.tool.include, cfg.tool.exclude)


def _ext_is_public(name: str) -> bool:
    return not name.startswith("_") and name != "__init__"


def _ext_max_nesting(node: _ast_ext.AST) -> int:
    blockers = (
        _ast_ext.If,
        _ast_ext.For,
        _ast_ext.AsyncFor,
        _ast_ext.While,
        _ast_ext.With,
        _ast_ext.AsyncWith,
        _ast_ext.Try,
        _ast_ext.IfExp,
    )

    def _d(n: _ast_ext.AST, cur: int = 0) -> int:
        if isinstance(n, blockers):
            cur += 1
        m = cur
        for c in _ast_ext.iter_child_nodes(n):
            m = max(m, _d(c, cur))
        return m

    md = 0
    for st in getattr(node, "body", []):
        md = max(md, _d(st, 0))
    return md


def _ext_function_metrics(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    files = _ext_collect_files(cfg)
    gates = cfg.gates
    loc_thr = int(getattr(gates, "fn_loc_max", 0) or 0)
    args_thr = int(getattr(gates, "fn_args_max", 0) or 0)
    nest_thr = int(getattr(gates, "fn_nesting_max", 0) or 0)
    count_doc = bool(getattr(gates, "fn_count_docstrings", True))
    violations: list[dict[str, _Any]] = []
    per_file: list[dict[str, _Any]] = []
    for f in files:
        try:
            src = Path(f).read_text(encoding="utf-8")
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        funs: list[dict[str, _Any]] = []
        for node in [
            n
            for n in _ast_ext.walk(tree)
            if isinstance(n, (_ast_ext.FunctionDef, _ast_ext.AsyncFunctionDef))
        ]:
            name = getattr(node, "name", "")
            if not _ext_is_public(name):
                continue
            try:
                start_line = node.lineno
                if not count_doc:
                    # 跳过函数首个 docstring 的行数
                    body = getattr(node, "body", []) or []
                    if body:
                        first = body[0]
                        # py>=3.8: Constant
                        is_doc = False
                        try:
                            import ast as _ast

                            is_doc = (
                                isinstance(first, _ast.Expr)
                                and isinstance(
                                    getattr(first, "value", None), _ast.Constant
                                )
                                and isinstance(first.value.value, str)
                            )
                        except Exception:
                            is_doc = False
                        if is_doc:
                            end_doc = getattr(
                                first,
                                "end_lineno",
                                getattr(first, "lineno", start_line),
                            )
                            start_line = int(end_doc) + 1
                end_line = getattr(node, "end_lineno", None) or node.lineno
                loc = int(end_line) - int(start_line) + 1
            except Exception:
                loc = None
            args_cnt = len(getattr(node, "args", None).args or []) + len(
                getattr(node, "args", None).kwonlyargs or []
            )
            nesting = _ext_max_nesting(node)
            funs.append(
                {
                    "name": name,
                    "lineno": node.lineno,
                    "loc": loc,
                    "args": args_cnt,
                    "nesting": nesting,
                }
            )
            viol = {"file": f, "name": name, "lineno": node.lineno}
            tagged = False
            if loc_thr and isinstance(loc, int) and loc > loc_thr:
                viol["loc"] = loc
                tagged = True
            if args_thr and args_cnt > args_thr:
                viol["args"] = args_cnt
                tagged = True
            if nest_thr and nesting > nest_thr:
                viol["nesting"] = nesting
                tagged = True
            if tagged:
                violations.append(viol)
        per_file.append({"file": f, "functions": funs})
    report = artifacts_dir / "function_metrics.json"
    report.write_text(
        json.dumps(
            {"violations": violations, "files": per_file}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    return len(violations), report


def _ext_private_symbol_imports(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    """Scan for symbol-level private imports, e.g. `from x import _private`.
    We intentionally limit to ImportFrom alias names beginning with '_' to avoid
    duplication with module-path private checks handled by import rules.
    """
    files = _ext_collect_files(cfg)
    violations: list[dict[str, _Any]] = []
    for f in files:
        try:
            src = Path(f).read_text(encoding="utf-8")
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        for node in [
            n for n in _ast_ext.walk(tree) if isinstance(n, _ast_ext.ImportFrom)
        ]:
            mod = getattr(node, "module", None) or ""
            for alias in getattr(node, "names", []) or []:
                try:
                    name = getattr(alias, "name", "") or ""
                except Exception:
                    name = ""
                if not name or name == "*":
                    continue
                last = name.split(".")[-1]
                if last.startswith("_"):
                    violations.append(
                        {
                            "file": f,
                            "lineno": getattr(node, "lineno", 0) or 0,
                            "module": mod,
                            "import": name,
                        }
                    )
    report = artifacts_dir / "private_symbol_imports.json"
    report.write_text(
        json.dumps({"violations": violations}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(violations), report


def _line_has_allow_comment(src: str, lineno: int, tags: List[str]) -> bool:
    try:
        line = src.splitlines()[max(0, lineno - 1)]
    except Exception:
        return False
    ls = line.lower()
    return any(tag.lower() in ls for tag in tags)


def _ext_failfast(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    files = _ext_collect_files(cfg)
    tags = list(getattr(cfg.gates, "failfast_allow_comment_tags", []) or [])
    forbid_dict_get = bool(getattr(cfg.gates, "failfast_forbid_dict_get_default", True))
    forbid_dict_get_any = bool(
        getattr(cfg.gates, "failfast_forbid_dict_get_any", False)
    )
    forbid_getattr = bool(getattr(cfg.gates, "failfast_forbid_getattr_default", True))
    forbid_getattr_any = bool(getattr(cfg.gates, "failfast_forbid_getattr_any", False))
    forbid_env = bool(getattr(cfg.gates, "failfast_forbid_env_default", True))
    forbid_imp_fb = bool(getattr(cfg.gates, "failfast_forbid_import_fallback", True))
    forbid_hasattr = bool(getattr(cfg.gates, "failfast_forbid_hasattr", True))
    violations: list[dict[str, _Any]] = []
    for f in files:
        try:
            src = Path(f).read_text(encoding="utf-8")
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        # getattr any or default-only
        if forbid_getattr_any or forbid_getattr:
            for n in [n for n in _ast_ext.walk(tree) if isinstance(n, _ast_ext.Call)]:
                try:
                    func = n.func
                    if isinstance(func, _ast_ext.Name) and func.id == "getattr":
                        argc = len(getattr(n, "args", []) or [])
                        if forbid_getattr_any or argc >= 3:
                            if not _line_has_allow_comment(
                                src, getattr(n, "lineno", 0) or 0, tags
                            ):
                                vtype = (
                                    "getattr_any"
                                    if forbid_getattr_any
                                    else "getattr_default"
                                )
                                violations.append(
                                    {
                                        "file": f,
                                        "lineno": getattr(n, "lineno", 0) or 0,
                                        "type": vtype,
                                    }
                                )
                except Exception:
                    pass
        # hasattr probing (treated as fallback)
        if forbid_hasattr:
            for n in [n for n in _ast_ext.walk(tree) if isinstance(n, _ast_ext.Call)]:
                func = getattr(n, "func", None)
                if isinstance(func, _ast_ext.Name) and func.id == "hasattr":
                    # hasattr(obj, 'attr')
                    if not _line_has_allow_comment(
                        src, getattr(n, "lineno", 0) or 0, tags
                    ):
                        violations.append(
                            {
                                "file": f,
                                "lineno": getattr(n, "lineno", 0) or 0,
                                "type": "hasattr_probing",
                            }
                        )
        # dict.get default & os.getenv/environ.get default
        for n in [n for n in _ast_ext.walk(tree) if isinstance(n, _ast_ext.Call)]:
            func = getattr(n, "func", None)
            if not isinstance(func, (_ast_ext.Attribute, _ast_ext.Name)):
                continue
            argc = len(getattr(n, "args", []) or [])
            # os.getenv
            if (
                forbid_env
                and isinstance(func, _ast_ext.Attribute)
                and isinstance(func.value, _ast_ext.Name)
                and func.value.id == "os"
                and func.attr == "getenv"
                and argc >= 2
            ):
                if not _line_has_allow_comment(src, getattr(n, "lineno", 0) or 0, tags):
                    violations.append(
                        {
                            "file": f,
                            "lineno": getattr(n, "lineno", 0) or 0,
                            "type": "env_default",
                            "call": "os.getenv",
                        }
                    )
                continue
            # os.environ.get
            if (
                forbid_env
                and isinstance(func, _ast_ext.Attribute)
                and isinstance(func.value, _ast_ext.Attribute)
                and isinstance(func.value.value, _ast_ext.Name)
                and func.value.value.id == "os"
                and func.value.attr == "environ"
                and func.attr == "get"
                and argc >= 2
            ):
                if not _line_has_allow_comment(src, getattr(n, "lineno", 0) or 0, tags):
                    violations.append(
                        {
                            "file": f,
                            "lineno": getattr(n, "lineno", 0) or 0,
                            "type": "env_default",
                            "call": "os.environ.get",
                        }
                    )
                continue
            # generic .get (heuristic) — any or default-only
            if (
                isinstance(func, _ast_ext.Attribute)
                and func.attr == "get"
                and (forbid_dict_get_any or (forbid_dict_get and argc >= 2))
            ):
                # Heuristic exclusions to avoid common false positives (e.g., requests.get)
                base = func.value
                base_name = ""
                if isinstance(base, _ast_ext.Name):
                    base_name = base.id
                elif isinstance(base, _ast_ext.Attribute):
                    # get root name
                    cur = base
                    while isinstance(cur, _ast_ext.Attribute):
                        cur = cur.value
                    if isinstance(cur, _ast_ext.Name):
                        base_name = cur.id
                if base_name in {"requests", "httpx"}:
                    continue
                if not _line_has_allow_comment(src, getattr(n, "lineno", 0) or 0, tags):
                    vtype = (
                        "dict_get_any" if forbid_dict_get_any else "dict_get_default"
                    )
                    violations.append(
                        {
                            "file": f,
                            "lineno": getattr(n, "lineno", 0) or 0,
                            "type": vtype,
                        }
                    )
        # try/except ImportError fallback
        if forbid_imp_fb:
            for t in [x for x in _ast_ext.walk(tree) if isinstance(x, _ast_ext.Try)]:
                for h in getattr(t, "handlers", []) or []:
                    tp = getattr(h, "type", None)
                    name = ""
                    if isinstance(tp, _ast_ext.Name):
                        name = tp.id
                    elif isinstance(tp, _ast_ext.Attribute):
                        name = tp.attr
                    if name == "ImportError":
                        # Allow inline comment override on 'try' line
                        if _line_has_allow_comment(
                            src, getattr(t, "lineno", 0) or 0, tags
                        ):
                            continue
                        violations.append(
                            {
                                "file": f,
                                "lineno": getattr(h, "lineno", 0) or 0,
                                "type": "import_fallback",
                            }
                        )
        # try/except AttributeError fallback for missing attributes
        if bool(getattr(cfg.gates, "failfast_forbid_attr_fallback", True)):
            for t in [x for x in _ast_ext.walk(tree) if isinstance(x, _ast_ext.Try)]:
                for h in getattr(t, "handlers", []) or []:
                    tp = getattr(h, "type", None)
                    name = ""
                    if isinstance(tp, _ast_ext.Name):
                        name = tp.id
                    elif isinstance(tp, _ast_ext.Attribute):
                        name = tp.attr
                    if name == "AttributeError":
                        if _line_has_allow_comment(
                            src, getattr(t, "lineno", 0) or 0, tags
                        ):
                            continue
                        violations.append(
                            {
                                "file": f,
                                "lineno": getattr(h, "lineno", 0) or 0,
                                "type": "attr_fallback",
                            }
                        )
        # try/except KeyError fallback for missing dict keys
        if bool(getattr(cfg.gates, "failfast_forbid_key_fallback", True)):
            for t in [x for x in _ast_ext.walk(tree) if isinstance(x, _ast_ext.Try)]:
                for h in getattr(t, "handlers", []) or []:
                    tp = getattr(h, "type", None)
                    name = ""
                    if isinstance(tp, _ast_ext.Name):
                        name = tp.id
                    elif isinstance(tp, _ast_ext.Attribute):
                        name = tp.attr
                    if name == "KeyError":
                        if _line_has_allow_comment(
                            src, getattr(t, "lineno", 0) or 0, tags
                        ):
                            continue
                        violations.append(
                            {
                                "file": f,
                                "lineno": getattr(h, "lineno", 0) or 0,
                                "type": "key_fallback",
                            }
                        )
        # 'in obj.__dict__' probing for attribute existence
        if bool(getattr(cfg.gates, "failfast_forbid_attr_fallback", True)):
            for n in [x for x in _ast_ext.walk(tree) if isinstance(x, _ast_ext.Compare)]:
                # pattern: <left> in <obj>.__dict__  OR  <left> not in <obj>.__dict__
                try:
                    ops = getattr(n, "ops", []) or []
                    if not ops:
                        continue
                    comp = getattr(n, "comparators", []) or []
                    if not comp:
                        continue
                    right = comp[0]
                    if isinstance(right, _ast_ext.Attribute) and right.attr == "__dict__":
                        if any(isinstance(op, (_ast_ext.In, _ast_ext.NotIn)) for op in ops):
                            if not _line_has_allow_comment(src, getattr(n, "lineno", 0) or 0, tags):
                                violations.append(
                                    {
                                        "file": f,
                                        "lineno": getattr(n, "lineno", 0) or 0,
                                        "type": "attr_dict_probe",
                                    }
                                )
                except Exception:
                    pass
    report = artifacts_dir / "failfast_violations.json"
    report.write_text(
        json.dumps({"violations": violations}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(violations), report


def _ext_public_no_side_effects(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    files = _ext_collect_files(cfg)
    forbid = bool(getattr(cfg.gates, "packages_public_no_side_effects", True))
    forbidden_calls = list(
        getattr(cfg.gates, "packages_public_side_effect_forbidden_calls", []) or []
    )
    if not forbid:
        # Disabled
        report = artifacts_dir / "public_exports_side_effects.json"
        report.write_text(
            json.dumps({"violations": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0, report

    def dotted_name(n: _ast_ext.AST) -> str:
        if isinstance(n, _ast_ext.Name):
            return n.id
        if isinstance(n, _ast_ext.Attribute):
            parts = []
            cur = n
            while isinstance(cur, _ast_ext.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, _ast_ext.Name):
                parts.append(cur.id)
            parts.reverse()
            return ".".join(parts)
        return ""

    import fnmatch as _fnm

    violations: list[dict[str, _Any]] = []
    for f in files:
        if not f.endswith("__init__.py"):
            continue
        try:
            src = Path(f).read_text(encoding="utf-8")
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        # Top-level only
        for idx, st in enumerate(getattr(tree, "body", []) or []):
            if (
                idx == 0
                and isinstance(st, _ast_ext.Expr)
                and isinstance(getattr(st, "value", None), _ast_ext.Constant)
                and isinstance(st.value.value, str)
            ):
                # module docstring allowed
                continue
            if isinstance(st, (_ast_ext.Import, _ast_ext.ImportFrom)):
                continue
            # allow __all__ = [...] or tuple
            if isinstance(st, _ast_ext.Assign):
                # any target is __all__
                ok = False
                for tgt in getattr(st, "targets", []) or []:
                    if isinstance(tgt, _ast_ext.Name) and tgt.id == "__all__":
                        ok = True
                        break
                if ok:
                    continue
            # detect top-level calls
            if isinstance(st, _ast_ext.Expr) and isinstance(
                getattr(st, "value", None), _ast_ext.Call
            ):
                dn = dotted_name(getattr(st.value, "func", None))
                if dn and any(_fnm.fnmatch(dn, pat) for pat in forbidden_calls):
                    violations.append(
                        {
                            "file": f,
                            "lineno": getattr(st, "lineno", 0) or 0,
                            "type": "forbidden_call",
                            "call": dn,
                        }
                    )
                    continue
            # everything else forbidden
            violations.append(
                {
                    "file": f,
                    "lineno": getattr(st, "lineno", 0) or 0,
                    "type": "disallowed_top_level",
                }
            )
    report = artifacts_dir / "public_exports_side_effects.json"
    report.write_text(
        json.dumps({"violations": violations}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(violations), report


def _ext_import_cycles(
    cfg: QAConfig, artifacts_dir: Path, project_data: Any
) -> tuple[int, Path]:
    # Build adjacency list from project_data.import_edges
    edges = list(project_data.import_edges)
    nodes: Dict[str, int] = {}
    for a, b in edges:
        if a not in nodes:
            nodes[a] = len(nodes)
        if b not in nodes:
            nodes[b] = len(nodes)
    adj: Dict[int, list[int]] = {nodes[n]: [] for n in nodes}
    for a, b in edges:
        adj[nodes[a]].append(nodes[b])
    # Tarjan SCC
    index = 0
    indices: Dict[int, int] = {}
    lowlink: Dict[int, int] = {}
    stack: list[int] = []
    onstack: set[int] = set()
    sccs: list[list[str]] = []
    sys.setrecursionlimit(10000)

    def strongconnect(v: int):
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)
        for w in adj.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in onstack:
                lowlink[v] = min(lowlink[v], indices[w])
        if lowlink[v] == indices[v]:
            comp: list[str] = []
            while True:
                w = stack.pop()
                onstack.discard(w)
                # find name by index
                name = next((n for n, i in nodes.items() if i == w), None)
                if name:
                    comp.append(name)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(sorted(comp))

    for v in list(nodes.values()):
        if v not in indices:
            strongconnect(v)
    report = artifacts_dir / "import_cycles.json"
    report.write_text(
        json.dumps(
            {"scc_groups": sccs, "count": len(sccs)}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    return len(sccs), report


def _ext_stubs_no_notimplemented(
    cfg: QAConfig, artifacts_dir: Path
) -> tuple[int, Path]:
    files = _ext_collect_files(cfg)
    violations: list[dict[str, _Any]] = []

    # Helpers to check ABC context
    def class_is_abc(cls: _ast_ext.ClassDef) -> bool:
        # bases contain ABC/abc.ABC/ABCMeta
        for b in getattr(cls, "bases", []) or []:
            if isinstance(b, _ast_ext.Name) and b.id in {"ABC", "ABCMeta"}:
                return True
            if (
                isinstance(b, _ast_ext.Attribute)
                and isinstance(b.value, _ast_ext.Name)
                and b.value.id == "abc"
                and b.attr in {"ABC", "ABCMeta"}
            ):
                return True
        return False

    def has_abstractmethod(fn: _ast_ext.AST) -> bool:
        for d in getattr(fn, "decorator_list", []) or []:
            if isinstance(d, _ast_ext.Name) and d.id == "abstractmethod":
                return True
            if isinstance(d, _ast_ext.Attribute) and d.attr == "abstractmethod":
                return True
        return False

    for f in files:
        try:
            src = Path(f).read_text(encoding="utf-8")
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        class_ctx: dict[int, bool] = {}
        # Map function to class ABC-ness
        for n in [n for n in _ast_ext.walk(tree) if isinstance(n, _ast_ext.ClassDef)]:
            class_ctx[id(n)] = class_is_abc(n)
        for n in [
            n
            for n in _ast_ext.walk(tree)
            if isinstance(n, (_ast_ext.FunctionDef, _ast_ext.AsyncFunctionDef))
        ]:
            # Find enclosing class
            parent_abc = False
            # Walk parents by re-parsing? AST has no parent link; we can heuristically ignore and assume non-ABC unless decorated
            # Simple heuristic: if function name startswith '_'? not used here.
            # Better: infer by scanning for immediate class scope by looking at lineno ranges
            enclosing: _ast_ext.ClassDef | None = None
            for c in [c for c in tree.body if isinstance(c, _ast_ext.ClassDef)]:
                if (
                    getattr(c, "lineno", 0)
                    <= getattr(n, "lineno", 0)
                    <= (getattr(c, "end_lineno", 1 << 30))
                ):
                    enclosing = c
                    break
            if enclosing is not None:
                parent_abc = class_is_abc(enclosing)
            if has_abstractmethod(n) or parent_abc:
                continue
            # Detect raise NotImplementedError
            has_raise_notimpl = any(
                isinstance(x, _ast_ext.Raise)
                and (
                    isinstance(getattr(x, "exc", None), _ast_ext.Name)
                    and getattr(x.exc, "id", "") == "NotImplementedError"
                    or (
                        isinstance(getattr(x, "exc", None), _ast_ext.Call)
                        and isinstance(getattr(x.exc, "func", None), _ast_ext.Name)
                        and getattr(x.exc.func, "id", "") == "NotImplementedError"
                    )
                )
                for x in _ast_ext.walk(n)
            )
            # Detect pass-only body (ignore docstring at position 0)
            body = getattr(n, "body", []) or []
            body_eff = (
                body[1:]
                if (
                    body
                    and isinstance(body[0], _ast_ext.Expr)
                    and isinstance(getattr(body[0], "value", None), _ast_ext.Constant)
                    and isinstance(body[0].value.value, str)
                )
                else body
            )
            pass_only = (
                all(isinstance(x, (_ast_ext.Pass,)) for x in body_eff)
                and len(body_eff) > 0
            )
            if has_raise_notimpl or pass_only:
                violations.append(
                    {
                        "file": f,
                        "lineno": getattr(n, "lineno", 0) or 0,
                        "name": getattr(n, "name", ""),
                        "type": "notimplemented_or_pass",
                    }
                )
    report = artifacts_dir / "stubs_no_notimplemented_non_abc.json"
    report.write_text(
        json.dumps({"violations": violations}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(violations), report


def _ext_junit_failure_types(
    cov_xml_path: _Any, artifacts_dir: Path, pytest_log_path: _Any
) -> tuple[int, int]:
    # cov_xml_path is not junit; try to derive junit path from logs dir or metrics
    # We'll best-effort search artifacts_dir for junit.xml
    junit = None
    # Known path in config default
    cand = artifacts_dir / "junit.xml"
    if cand.exists():
        junit = cand
    else:
        # fallback: search artifacts dir
        try:
            for p in artifacts_dir.glob("**/junit.xml"):
                junit = p
                break
        except Exception:
            pass
    if junit is None or not junit.exists():
        return 0, 0
    try:
        from xml.etree import ElementTree as ET

        tree = ET.parse(str(junit))
        root = tree.getroot()
        failures = 0
        errors = 0
        for case in root.iter("testcase"):
            if list(case.findall("failure")):
                failures += 1
            if list(case.findall("error")):
                errors += 1
        return failures, errors
    except Exception:
        return 0, 0


def _ext_doc_contracts(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    files = _ext_collect_files(cfg)
    missing: list[dict[str, _Any]] = []
    required = list(getattr(cfg.gates, "doc_required_sections", []) or [])
    if not required:
        required = ["功能概述", "前置条件", "后置条件", "不变量", "副作用"]
    case_sensitive = bool(getattr(cfg.gates, "doc_case_sensitive", False))
    for f in files:
        try:
            src = Path(f).read_text(encoding="utf-8")
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        file_missing: list[dict[str, _Any]] = []
        for node in [
            n
            for n in _ast_ext.walk(tree)
            if isinstance(n, (_ast_ext.FunctionDef, _ast_ext.AsyncFunctionDef))
        ]:
            # 检查所有函数（不区分是否 @stub 或公开）
            doc = _ast_ext.get_docstring(node) or ""
            if not doc.strip():
                file_missing.append(
                    {"name": node.name, "lineno": node.lineno, "reason": "no_doc"}
                )
            else:
                txt = doc if case_sensitive else doc.lower()
                keys = required if case_sensitive else [k.lower() for k in required]
                if not all(k in txt for k in keys):
                    file_missing.append(
                        {
                            "name": node.name,
                            "lineno": node.lineno,
                            "reason": "missing_sections",
                            "required": required,
                        }
                    )
        if file_missing:
            missing.append({"file": f, "missing": file_missing})
    report = artifacts_dir / "doc_contracts.json"
    report.write_text(
        json.dumps({"stub_missing": missing}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    total_missing = sum(len(item.get("missing", [])) for item in missing)
    return total_missing, report


def _ext_exports(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    paths = cfg.tool.paths
    priv_list: list[dict[str, _Any]] = []
    for root in paths:
        base = Path(root)
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            if "__init__.py" in filenames:
                initp = Path(dirpath) / "__init__.py"
                try:
                    tree = _ast_ext.parse(initp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                priv: list[str] = []
                for node in tree.body:
                    if isinstance(node, _ast_ext.Assign):
                        for target in node.targets:
                            if (
                                isinstance(target, _ast_ext.Name)
                                and target.id == "__all__"
                            ):
                                if isinstance(
                                    node.value, (_ast_ext.List, _ast_ext.Tuple)
                                ):
                                    for elt in node.value.elts:
                                        if isinstance(elt, _ast_ext.Str):
                                            name = elt.s
                                            if name.startswith("_"):
                                                priv.append(name)
                if priv:
                    priv_list.append(
                        {"package_init": str(initp), "private_exports": priv}
                    )
    report = artifacts_dir / "exports.json"
    report.write_text(
        json.dumps({"private_exports": priv_list}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    count = sum(len(item.get("private_exports", [])) for item in priv_list)
    return count, report


def _ext_exports_require_nonempty_all(
    cfg: QAConfig, artifacts_dir: Path
) -> tuple[int, Path]:
    """检查包内 __init__.py 是否定义非空 __all__。

    返回 (missing_count, report_path)
    报表包含缺少或空 __all__ 的 __init__.py 列表。
    支持通过 gates.exports_nonempty_all_exclude (glob) 排除。
    """
    paths = cfg.tool.paths
    missing: list[dict[str, _Any]] = []
    import fnmatch

    excludes = list(getattr(cfg.gates, "exports_nonempty_all_exclude", []) or [])
    for root in paths:
        base = Path(root)
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            if "__init__.py" not in filenames:
                continue
            initp = Path(dirpath) / "__init__.py"
            # 排除
            path_str = str(initp)
            rel_str = path_str
            try:
                rel_str = str(initp.relative_to(Path.cwd()))
            except Exception:
                pass
            if any(
                fnmatch.fnmatch(path_str, pat) or fnmatch.fnmatch(rel_str, pat)
                for pat in excludes
            ):
                continue
            try:
                tree = _ast_ext.parse(initp.read_text(encoding="utf-8"))
            except Exception:
                continue
            found = False
            nonempty = False
            for node in tree.body:
                if isinstance(node, _ast_ext.Assign):
                    for target in node.targets:
                        if isinstance(target, _ast_ext.Name) and target.id == "__all__":
                            found = True
                            if isinstance(node.value, (_ast_ext.List, _ast_ext.Tuple)):
                                nonempty = (
                                    len(getattr(node.value, "elts", []) or []) > 0
                                )
                            elif isinstance(node.value, _ast_ext.Call):
                                # 允许 list([...]) 之类表达式，无法静态判定长度 -> 视为存在但未知；不计为缺失
                                nonempty = True
                            else:
                                # 其他不可静态检查的情况，视为存在
                                nonempty = True
            if not found or not nonempty:
                missing.append(
                    {"package_init": str(initp), "has_all": found, "nonempty": nonempty}
                )
    report = artifacts_dir / "exports_nonempty_all.json"
    report.write_text(
        json.dumps({"missing_nonempty_all": missing}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(missing), report


"""
GitHub Actions and Makefile scaffolding intentionally not provided by CodeClinic.
"""

# --- New: runtime validation (pydantic.validate_call) ---
def _ext_runtime_validate_call(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, int, Path]:
    files = _ext_collect_files(cfg)
    # Apply extra excludes
    import fnmatch as _fnm
    extra_ex = list(getattr(cfg.gates, "runtime_validation_exclude", []) or [])
    if extra_ex:
        filtered = []
        for f in files:
            p = str(f)
            if any(_fnm.fnmatch(p, pat) for pat in extra_ex):
                continue
            filtered.append(f)
        files = filtered

    skip_private = bool(getattr(cfg.gates, "runtime_validation_skip_private", True))
    skip_magic = bool(getattr(cfg.gates, "runtime_validation_skip_magic", True))
    skip_props = bool(getattr(cfg.gates, "runtime_validation_skip_properties", True))
    tags = list(getattr(cfg.gates, "runtime_validation_allow_comment_tags", []) or [])

    def _dotted_name(dec: _ast_ext.AST) -> str:
        # Convert decorator AST to dotted text
        try:
            if isinstance(dec, _ast_ext.Name):
                return dec.id
            if isinstance(dec, _ast_ext.Attribute):
                parts = []
                cur = dec
                while isinstance(cur, _ast_ext.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, _ast_ext.Name):
                    parts.append(cur.id)
                parts.reverse()
                return ".".join(parts)
            if isinstance(dec, _ast_ext.Call):
                return _dotted_name(dec.func)
        except Exception:
            return ""
        return ""

    def _is_property(decorators: list[_ast_ext.AST]) -> bool:
        for d in decorators:
            dn = _dotted_name(d)
            if dn.endswith("property") or dn.endswith("cached_property"):
                return True
        return False

    def _has_allow_comment(src: str, node: _ast_ext.AST) -> bool:
        try:
            line = src.splitlines()[max(0, getattr(node, "lineno", 1) - 1)]
            ls = line.lower()
            return any(t.lower() in ls for t in tags)
        except Exception:
            return False

    missing: list[dict[str, _Any]] = []
    order_warn: list[dict[str, _Any]] = []

    for f in files:
        try:
            src = Path(f).read_text(encoding="utf-8")
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        for node in [
            n
            for n in _ast_ext.walk(tree)
            if isinstance(n, (_ast_ext.FunctionDef, _ast_ext.AsyncFunctionDef))
        ]:
            name = getattr(node, "name", "")
            # Skip conditions
            if skip_magic and (name.startswith("__") and name.endswith("__")):
                continue
            if skip_private and name.startswith("_"):
                continue
            if skip_props and _is_property(getattr(node, "decorator_list", []) or []):
                continue
            if _has_allow_comment(src, node):
                continue
            decorators = getattr(node, "decorator_list", []) or []
            dotted = [_dotted_name(d) for d in decorators]
            has_vc = any(d == "validate_call" or d.endswith(".validate_call") for d in dotted)
            if not has_vc:
                missing.append({"file": f, "name": name, "lineno": getattr(node, "lineno", 0) or 0})
                continue
            # Order checking: require innermost (last in list)
            try:
                last = dotted[-1] if dotted else ""
            except Exception:
                last = ""
            if bool(getattr(cfg.gates, "runtime_validation_require_innermost", False)):
                if not (last == "validate_call" or last.endswith(".validate_call")):
                    order_warn.append(
                        {
                            "file": f,
                            "name": name,
                            "lineno": getattr(node, "lineno", 0) or 0,
                            "decorators": dotted,
                        }
                    )

    report = artifacts_dir / "validate_call_missing.json"
    report.write_text(
        json.dumps(
            {"missing": missing, "order_warnings": order_warn},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return len(missing), len(order_warn), report


def _ext_classes_require_super_init(cfg: QAConfig, artifacts_dir: Path) -> tuple[int, Path]:
    files = _ext_collect_files(cfg)
    import fnmatch as _fnm
    ex = list(getattr(cfg.gates, "classes_super_init_exclude", []) or [])
    if ex:
        files = [f for f in files if not any(_fnm.fnmatch(str(f), pat) for pat in ex)]
    tags = list(getattr(cfg.gates, "classes_super_init_allow_comment_tags", []) or [])

    def _has_allow_comment(src: str, node: _ast_ext.AST) -> bool:
        try:
            line = src.splitlines()[max(0, getattr(node, "lineno", 1) - 1)]
            ls = line.lower()
            return any(t.lower() in ls for t in tags)
        except Exception:
            return False

    def _calls_super_init(func_node: _ast_ext.FunctionDef | _ast_ext.AsyncFunctionDef) -> bool:
        for n in _ast_ext.walk(func_node):
            if isinstance(n, _ast_ext.Call):
                fn = getattr(n, "func", None)
                # super().__init__(...)
                if isinstance(fn, _ast_ext.Attribute) and fn.attr == "__init__":
                    val = fn.value
                    if isinstance(val, _ast_ext.Call):
                        callee = getattr(val, "func", None)
                        if isinstance(callee, _ast_ext.Name) and callee.id == "super":
                            return True
        return False

    violations: list[dict[str, _Any]] = []
    for f in files:
        try:
            src = Path(f).read_text(encoding="utf-8")
            tree = _ast_ext.parse(src)
        except Exception:
            continue
        for cls in [n for n in _ast_ext.walk(tree) if isinstance(n, _ast_ext.ClassDef)]:
            # only subclasses (has base other than built-in 'object')
            bases = getattr(cls, "bases", []) or []
            if not bases:
                continue
            # ignore pure object subclass explicitly declared
            is_only_object = False
            try:
                if len(bases) == 1:
                    b = bases[0]
                    if isinstance(b, _ast_ext.Name) and b.id == "object":
                        is_only_object = True
            except Exception:
                pass
            if is_only_object:
                continue
            inits = [
                n
                for n in getattr(cls, "body", []) or []
                if isinstance(n, (_ast_ext.FunctionDef, _ast_ext.AsyncFunctionDef))
                and getattr(n, "name", "") == "__init__"
            ]
            if not inits:
                continue
            for init in inits:
                if _has_allow_comment(src, init):
                    continue
                if not _calls_super_init(init):
                    violations.append(
                        {
                            "file": f,
                            "class": getattr(cls, "name", ""),
                            "lineno": getattr(init, "lineno", 0) or 0,
                        }
                    )

    report = artifacts_dir / "super_init_violations.json"
    report.write_text(
        json.dumps({"missing_super_init": violations}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(violations), report
