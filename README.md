# CodeClinic (codeclinic)

> Diagnose your Python project: import dependencies → maturity metrics (stub ratio) → Graphviz visualization.

## Install
```bash
pip install codeclinic
# or, from source (dev):
pip install -e .
```
> **Note:** Rendering SVG/PNG requires the Graphviz **system** tool (`dot`) in your PATH. macOS: `brew install graphviz`; Ubuntu: `sudo apt-get install graphviz`.

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
from codeclinic import stub

@stub
def todo_api():
    pass
```
`@stub` will (1) mark the function for static counting and (2) emit a `warnings.warn` when it’s actually called.

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
