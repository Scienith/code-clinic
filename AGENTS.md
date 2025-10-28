# Repository Guidelines

## Project Structure & Module Organization
- Source code lives in `src/codeclinic/` (package `codeclinic`).
- Primary CLI entry is `src/codeclinic/cli.py`; legacy/dev entry exists at `cli.py`.
- Config files: `codeclinic.yaml` (local overrides), `example_config.yaml` (reference).
- Examples: `example_project/` for quick end‑to‑end runs.
- Packaging: `pyproject.toml` (hatchling). Outputs default to `codeclinic_results/`.

## Build, Test, and Development Commands
- Install editable: `pip install -e .`
- Run CLI (init/show): `codeclinic --init`, `codeclinic --show-config`
- Analyze a project: `codeclinic --path example_project --out codeclinic_results --format svg`
- Legacy mode: `codeclinic --legacy --path example_project`
- Dev execution (without install): `python cli.py --path example_project`
- Build distribution: `python -m build` (creates `dist/`).

## QA Facade
- Unified quality gates via `codeclinic qa ...`:
  - Init: `codeclinic qa init`
  - Run checks: `codeclinic qa run`
  - Auto-fix: `codeclinic qa fix`
- Outputs in `build/codeclinic/`:
  - `summary.json`, `logs/`, and `artifacts/` (coverage.xml, complexity.json, report.html, import_violations/, stub_completeness/)
- Gates: formatter, linter, mypy, coverage, max_file_loc, import_violations. All required tools are installed with this package.

## Coding Style & Naming Conventions
- Follow PEP 8; 4‑space indentation; include type hints where practical.
- Names: modules and functions `snake_case`, classes `PascalCase`.
- Keep CLI UX consistent with existing flags and output structure; avoid adding heavy deps.
- Prefer small, focused functions; document public APIs with concise docstrings.

## Testing Guidelines
- Preferred framework: `pytest`.
- Place tests under `tests/`; files named `test_*.py` mirroring package paths.
- Run locally with `pytest -q`. Add targeted tests for new behavior and bugs.

## Commit & Pull Request Guidelines
- Use Conventional Commits (e.g., `feat:`, `fix:`, `docs:`) as in history (e.g., `fix: Generate violations graph`).
- Keep commits scoped and imperative; one logical change per commit.
- PRs should include: clear summary, linked issue, CLI usage example (command + brief output), and notes on config/docs updates. Attach screenshots/artifacts from `codeclinic_results/` when relevant.

## Agent-Specific Instructions
- Modify code only under `src/codeclinic/` unless explicitly changing packaging or examples.
- Update `src/codeclinic/cli.py` for CLI behavior; avoid unrelated refactors.
- Do not commit generated outputs (`codeclinic_results/`, `dist/`). Keep patches minimal and style‑consistent.
