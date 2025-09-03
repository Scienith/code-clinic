# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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