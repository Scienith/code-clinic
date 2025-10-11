#!/usr/bin/env python3
"""
QA CLI entrypoint for CodeClinic

Subcommands:
  - qa init:    generate QA config (codeclinic.yaml or example)
  - qa run:     run checks (black/ruff/mypy/pytest + internal deps/stubs)
  - qa fix:     auto-fix format/lint issues (black/ruff --fix)

Kept separate from the legacy CLI to avoid breaking existing flags.
"""
from __future__ import annotations

import sys
import argparse


def qa_cli_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="codeclinic qa", description="Quality gates facade")
    sub = parser.add_subparsers(dest="qa_cmd")

    p_init = sub.add_parser("init", help="Generate QA configuration (codeclinic.yaml)")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing codeclinic.yaml if present")
    p_init.add_argument("--pre-commit", action="store_true", help="Also scaffold .pre-commit-config.yaml")
    p_init.add_argument("--github-actions", action="store_true", help="Also scaffold GitHub Actions workflow")
    p_init.add_argument("--makefile", action="store_true", help="Also scaffold a simple Makefile")

    p_run = sub.add_parser("run", help="Run QA checks (no auto-fix)")
    p_run.add_argument("--config", default="codeclinic.yaml", help="Path to QA config (YAML)")
    p_run.add_argument("--output", default=None, help="Override output directory (default from config)")

    p_fix = sub.add_parser("fix", help="Auto-fix format/lint issues only")
    p_fix.add_argument("--config", default="codeclinic.yaml", help="Path to QA config (YAML)")

    args = parser.parse_args(argv)

    if not args.qa_cmd:
        parser.print_help()
        sys.exit(0)

    # Lazy import to keep base CLI import time minimal
    if args.qa_cmd == "init":
        from .qa_runner import qa_init
        qa_init(force=args.force, pre_commit=args.pre_commit, github_actions=args.github_actions, makefile=args.makefile)
        return

    if args.qa_cmd == "run":
        from .qa_runner import qa_run
        exit_code = qa_run(config_path=args.config, output_override=args.output)
        sys.exit(exit_code)

    if args.qa_cmd == "fix":
        from .qa_runner import qa_fix
        exit_code = qa_fix(config_path=args.config)
        sys.exit(exit_code)
