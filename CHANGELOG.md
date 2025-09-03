# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3a1] - 2025-09-03

### ✨ Added
- **Import rule validation**: Comprehensive validation of Python import relationships with configurable rules
  - Cross-package import detection and validation
  - Upward import prevention (child importing from parent)
  - Skip-level import detection (bypassing intermediate modules)
  - White-list configuration for allowed cross-package imports
- **YAML configuration support**: New `codeclinic.yaml` configuration format with fallback to TOML
- **Specialized analysis modules**: Separate analysis for import violations and stub completeness
  - `import_violations/violations.json` - Detailed import rule violations with severity levels
  - `stub_completeness/stub_summary.json` - Simplified stub function reports with depth metrics
- **Enhanced visualization**: 
  - Stub heatmap with HTML progress bars showing implementation completeness
  - Color-coded progress indicators (green for implemented, gray for stubs)
  - Simplified node names displaying only the last component (e.g., "A11" instead of "A.A1.A11")
- **Depth-based analysis**:
  - `package_depth`: Directory structure depth (0 for root level, +1 per directory)
  - `graph_depth`: Import dependency depth (0 for root dependencies, +1 per import level)
  - Stub functions sorted by package_depth (descending) for implementation priority

### 🔧 Enhanced
- **Data collection improvements**: Fixed import resolution logic for project-relative imports
- **JSON output simplification**: Streamlined outputs to contain only essential information
  - Violations analysis: Only violation details
  - Stub analysis: Only stub function information with depth metrics
- **Node type distinction**: Clear separation between MODULE (single .py files) and PACKAGE (directories with __init__.py)
- **Progress visualization**: HTML-based progress bars in Graphviz for better visual feedback

### 🐛 Fixed
- **Import detection**: Fixed major issue where 0 import edges were being detected
- **Function metadata**: Added missing `module_name` and `file_path` fields to `FunctionInfo`
- **JSON serialization**: Fixed serialization errors with configuration objects
- **Display formatting**: Corrected attribute access patterns for violation objects

### 📊 Technical Improvements
- Unified data collection with specialized analysis modules
- BFS-based graph depth calculation for accurate dependency levels
- Enhanced AST analysis for better import detection
- Improved error handling and warning messages

## [0.1.2] - 2025-01-09

### 🐛 Fixed
- Fixed version display issue: Updated `__version__` in source code to match package version
- Now correctly shows v0.1.2 when running `codeclinic --version` or `pip show codeclinic`

## [0.1.1] - 2025-01-09

### ✨ Added
- **JSON output format support**: Use `--format json` to generate machine-readable analysis results
- **Stub function detailed reports**: New `stub_report.json` file containing comprehensive stub function information
  - File paths and module locations
  - Function/method names with full qualified names (e.g., `ClassName.method_name`)
  - Complete docstring extraction from AST
  - Graph depth calculation for dependency priority analysis
  - Method vs function classification with class name tracking
- **Unified output directory structure**: All analysis results now organized in a single output folder
  - `analysis.json` - Overall project analysis and statistics
  - `stub_report.json` - Detailed stub function inventory
  - `dependency_graph.svg` - Visualization graph
  - `dependency_graph.dot` - Graphviz source file

### 🔧 Enhanced  
- **AST scanner improvements**: Enhanced to collect detailed stub function metadata during analysis
- **CLI default behavior**: Now generates all output formats by default for comprehensive analysis
- **Graph depth analysis**: Calculate dependency depth for each stub function to aid implementation prioritization
- **Sorting and organization**: Stub functions sorted by graph depth (deepest first) for better development planning

### 📊 Data Structure Improvements
- Extended `StubFunction` data type with comprehensive metadata
- Added graph analysis utilities for dependency depth calculation
- Improved JSON serialization with clean, structured output

### 🐛 Fixed
- Output directory creation now handles nested paths correctly
- Better error handling for AST parsing edge cases

## [0.1.0] - 2024-12-XX

### Initial Release
- Python project dependency analysis using AST parsing
- `@stub` decorator for marking incomplete functions
- Graphviz visualization of import dependencies
- Basic CLI interface with configurable output formats
- Support for SVG, PNG, PDF, and DOT output formats
- Configuration via `pyproject.toml` or `codeclinic.toml`
- Module and package level aggregation options