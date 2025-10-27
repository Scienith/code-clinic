# CodeClinic (codeclinic)

> Diagnose your Python project: import dependencies → maturity metrics (stub ratio) → Graphviz visualization.

## Install
```bash
# from GitHub main branch
pip install git+https://github.com/Scienith/code-clinic@main
```
> **Note:** Rendering SVG/PNG requires the Graphviz **system** tool (`dot`) in your PATH. macOS: `brew install graphviz`; Ubuntu: `sudo apt-get install graphviz`.

## QA Facade (one-stop quality gates)
CodeClinic ships with a QA facade that unifies formatting, linting, type checks, tests/coverage, complexity, and internal import/stub analysis behind a single command.

Commands
- Initialize config and optional scaffolding:
  - `codeclinic qa init [--pre-commit --github-actions --makefile]`
- Run checks (no auto-fix):
  - `codeclinic qa run`
- Auto-fix format/lint issues only:
  - `codeclinic qa fix`

Outputs (default `build/codeclinic/`)
- `summary.json` (overall status, failed gates, key metrics)
- `logs/*.log` (black/ruff/mypy/pytest/complexity)
- `artifacts/`:
  - `coverage.xml`
  - `complexity.json`, `report.html`
  - `import_violations/violations.json`
  - `stub_completeness/stub_summary.json`

Gates (configurable in `codeclinic.yaml`)
- `formatter_clean`, `linter_errors_max`, `mypy_errors_max`, `coverage_min`, `max_file_loc`, `import_violations_max`, `stub_ratio_max`
- Optional complexity gates (radon-based): `cc_max_rank_max` (A–F) and `mi_min` (0–100)

All QA provider tools (black, ruff, mypy, pytest, coverage, radon, pyyaml) are installed with CodeClinic and expected to be present.

### Detect Long Files (LOC gate)
- Set threshold in `codeclinic.yaml`:
  ```yaml
  gates:
    max_file_loc: 500
    # Optional complexity gates:
    # cc_max_rank_max: "C"
    # mi_min: 70
  ```
- Run QA: `codeclinic qa run`
- Inspect results:
  - Over-limit files: `build/codeclinic/artifacts/complexity.json` → `summary.files_over_limit`
  - Quick print (no jq required):
    ```bash
    python3 - <<'PY'
    import json
    p='build/codeclinic/artifacts/complexity.json'
    d=json.load(open(p))
    print('\n'.join(d['summary'].get('files_over_limit', [])))
    PY
    ```
  - With LOC values:
    ```bash
    python3 - <<'PY'
    import json
    d=json.load(open('build/codeclinic/artifacts/complexity.json'))
    for f in d['files']:
        if isinstance(f.get('loc'), int) and f['loc']>500:
            print(f["path"], f["loc"])  # adjust 500 if needed
    PY
    ```

## Quick start
```bash
codeclinic --path ./src --out results
```
This prints a summary + adjacency list and writes:
- `results/analysis.json` (project analysis data)
- `results/stub_report.json` (detailed stub function report)
- `results/dependency_graph.dot` (DOT source)
- `results/dependency_graph.svg` (rendered visualization)

## Marking stubs
```python
from codeclinic.stub import stub

@stub
def todo_api():
    pass
```
`@stub` will (1) mark the function for static counting (sets `__codeclinic_stub__=True`) and (2) emit a `warnings.warn` when it’s actually called.

## Config
You can keep settings in `pyproject.toml` under `[tool.codeclinic]` or in a `codeclinic.toml` file:
```toml
[tool.codeclinic]
paths = ["src"]
include = ["**/*.py"]
exclude = ["**/tests/**", "**/.venv/**"]
aggregate = "package"     # "module" | "package"
format = "svg"            # svg | png | pdf | dot
output = "build/cc_graph"
count_private = false
```
CLI flags override config.

## Output Formats

### All-in-One (Default)
```bash
codeclinic --path ./src --out results
```
Generates complete analysis with all output files in a single directory.

### JSON Data Only
```bash
codeclinic --path ./src --out results --format json
```
Generates only JSON files (analysis + stub report) without visualization.

### Specific Visualization Formats
```bash
codeclinic --path ./src --out results --format svg    # SVG visualization
codeclinic --path ./src --out results --format png    # PNG visualization  
codeclinic --path ./src --out results --format pdf    # PDF visualization
```

## Stub Function Reports

The `stub_report.json` file contains detailed information about all `@stub` decorated functions:

```json
{
  "metadata": {
    "total_stub_functions": 5,
    "modules_with_stubs": 3,
    "function_stubs": 3,
    "method_stubs": 2
  },
  "stub_functions": [
    {
      "module_name": "myproject.utils",
      "file_path": "/path/to/utils.py", 
      "function_name": "incomplete_feature",
      "full_name": "incomplete_feature",
      "docstring": "This feature is not yet implemented.",
      "is_method": false,
      "class_name": null,
      "graph_depth": 2
    }
  ]
}
```

Each stub function includes:
- **File location** and module information
- **Function/method name** with full qualified name (e.g., `ClassName.method_name`)
- **Docstring** extracted from the function
- **Graph depth** - dependency level for implementation prioritization
- **Method classification** - whether it's a standalone function or class method

## CLI
```bash
codeclinic --path PATH [--out OUTPUT_DIR] [--format svg|png|pdf|dot|json] [--aggregate module|package]
```

## How it works
- Parses your code with `ast` (no import-time side effects).
- Builds an internal import graph (absolute & relative imports resolved).
- Counts public functions/methods and `@stub`-decorated ones to compute a stub ratio per node.
- Renders a Graphviz graph with node colors by ratio (green→yellow→red).

## Roadmap
- Smell detectors (circulars, forbidden deps, god packages, layer rules).
- HTML/PDF report with dashboards.
- Plugin entry points: `codeclinic.detector`.

## License
MIT
