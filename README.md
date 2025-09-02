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
codeclinic --path ./src --out build/cc_graph --format svg
```
This prints a summary + adjacency list and writes:
- `build/cc_graph.dot` (DOT source)
- `build/cc_graph.svg` (rendered)

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

## CLI
```bash
codeclinic --path PATH [--out OUTPUT_BASE] [--format svg|png|pdf|dot] [--aggregate module|package]
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
