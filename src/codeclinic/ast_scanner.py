"""
AST-based dependency scanner that can analyze any Python files/directories.
No requirement for packages or __init__.py files.
"""

from __future__ import annotations
import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from .types import ModuleStats, Modules, GraphEdges, ChildEdges


def scan_project_ast(paths: List[str], include: List[str], exclude: List[str], count_private: bool) -> Tuple[Modules, GraphEdges, ChildEdges]:
    """
    Scan project using pure AST analysis.
    
    Can analyze:
    - Any Python files (.py)
    - Any directory structure 
    - Multiple independent paths
    - No requirement for __init__.py files
    """
    modules: Modules = {}
    edges: GraphEdges = set()
    child_edges: ChildEdges = set()
    
    # First pass: collect all Python files and create module mapping
    all_files: Dict[str, Path] = {}  # module_name -> file_path
    path_to_module: Dict[Path, str] = {}  # file_path -> module_name
    
    for path_str in paths:
        path = Path(path_str).resolve()
        if not path.exists():
            print(f"Warning: Path {path} does not exist")
            continue
            
        collected = _collect_python_files(path, include, exclude)
        for file_path in collected:
            module_name = _path_to_module_name(file_path, path)
            all_files[module_name] = file_path
            path_to_module[file_path] = module_name
    
    print(f"Found {len(all_files)} Python files")
    
    # Second pass: analyze each file for functions/stubs and imports
    for module_name, file_path in all_files.items():
        # Analyze functions and stubs
        stats = _count_functions_and_stubs(file_path, module_name, count_private)
        modules[module_name] = stats
        
        # Analyze imports
        imports = _extract_imports(file_path)
        for imported_name in imports:
            # Try to resolve import to actual module
            resolved_module = _resolve_import(imported_name, module_name, all_files)
            if resolved_module and resolved_module != module_name:
                edges.add((module_name, resolved_module))
    
    # Third pass: create parent-child relationships based on file structure
    for module_name in modules.keys():
        parts = module_name.split('.')
        if len(parts) > 1:
            parent = '.'.join(parts[:-1])
            if parent in modules:
                child_edges.add((parent, module_name))
    
    return modules, edges, child_edges


def _collect_python_files(base_path: Path, include: List[str], exclude: List[str]) -> List[Path]:
    """Collect all Python files matching include/exclude patterns."""
    python_files = []
    
    if base_path.is_file() and base_path.suffix == '.py':
        return [base_path]
    
    for root, dirs, files in os.walk(base_path):
        root_path = Path(root)
        
        # Skip excluded directories
        dirs[:] = [d for d in dirs if not _should_exclude_dir(root_path / d, exclude)]
        
        for file in files:
            if file.endswith('.py'):
                file_path = root_path / file
                if _should_include_file(file_path, base_path, include, exclude):
                    python_files.append(file_path)
    
    return python_files


def _should_exclude_dir(dir_path: Path, exclude: List[str]) -> bool:
    """Check if directory should be excluded."""
    DEFAULT_EXCLUDE_DIRS = {".git", ".hg", ".svn", "__pycache__", "build", "dist", ".venv", "venv", ".pytest_cache"}
    
    if dir_path.name in DEFAULT_EXCLUDE_DIRS:
        return True
        
    for pattern in exclude:
        if dir_path.match(pattern):
            return True
    
    return False


def _should_include_file(file_path: Path, base_path: Path, include: List[str], exclude: List[str]) -> bool:
    """Check if file should be included based on patterns."""
    try:
        rel_path = file_path.relative_to(base_path)
    except ValueError:
        return False
    
    # Check exclude patterns first
    for pattern in exclude:
        if rel_path.match(pattern):
            return False
    
    # Check include patterns
    if not include:
        return True
    
    # Special case: if it's a .py file, always include it
    # This handles cases like root __init__.py which might not match **/*.py
    if file_path.suffix == '.py':
        return True
        
    for pattern in include:
        if rel_path.match(pattern):
            return True
    
    return False


def _path_to_module_name(file_path: Path, base_path: Path) -> str:
    """Convert file path to module name."""
    try:
        rel_path = file_path.relative_to(base_path)
    except ValueError:
        # If relative path fails, use file stem
        return file_path.stem
    
    # Remove .py extension
    if rel_path.suffix == '.py':
        rel_path = rel_path.with_suffix('')
    
    # Convert path separators to dots
    parts = rel_path.parts
    
    # Handle __init__.py files
    if parts and parts[-1] == '__init__':
        parts = parts[:-1]
    
    if not parts:
        # Root __init__.py case - return base directory name
        return base_path.name
    
    # Build full module name with base_path as prefix
    module_parts = [base_path.name] + list(parts)
    return '.'.join(module_parts)


def _extract_imports(file_path: Path) -> Set[str]:
    """Extract all import statements from a Python file."""
    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(content, filename=str(file_path))
    except (OSError, SyntaxError) as e:
        print(f"Warning: Could not parse {file_path}: {e}")
        return set()
    
    imports = set()
    
    class ImportVisitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                imports.add(alias.name)
        
        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                imports.add(node.module)
                # Also add specific imports if they might be modules
                for alias in node.names:
                    if alias.name != '*':
                        full_name = f"{node.module}.{alias.name}"
                        imports.add(full_name)
    
    ImportVisitor().visit(tree)
    return imports


def _resolve_import(imported_name: str, importer_module: str, all_modules: Dict[str, Path]) -> Optional[str]:
    """
    Resolve an import name to an actual module name.
    
    This is a simplified resolver - in a real implementation you might want
    to handle relative imports, namespace packages, etc.
    """
    # Direct match
    if imported_name in all_modules:
        return imported_name
    
    # Try to find partial matches for submodules
    for module_name in all_modules:
        if module_name.startswith(imported_name + '.') or module_name.endswith('.' + imported_name):
            return module_name
    
    # Handle relative imports (simplified)
    if imported_name.startswith('.'):
        # This would need more sophisticated handling in a real implementation
        pass
    
    return None


def _count_functions_and_stubs(file_path: Path, module_name: str, count_private: bool) -> ModuleStats:
    """Count functions and @stub decorators in a file."""
    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(content, filename=str(file_path))
    except (OSError, SyntaxError) as e:
        print(f"Warning: Could not parse {file_path}: {e}")
        return ModuleStats(name=module_name, file=str(file_path))
    
    total = 0
    public = 0
    stubs = 0
    
    def is_stub_decorator(dec: ast.AST) -> bool:
        """Check if decorator is @stub."""
        def _name_of(expr: ast.AST) -> str:
            if isinstance(expr, ast.Name):
                return expr.id
            if isinstance(expr, ast.Attribute):
                parts = []
                cur = expr
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                parts.reverse()
                return ".".join(parts)
            return ""
        
        if isinstance(dec, ast.Call):
            name = _name_of(dec.func)
        else:
            name = _name_of(dec)
        return name.endswith(".stub") or name == "stub"
    
    class FunctionVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            nonlocal total, public, stubs
            total += 1
            is_public = not node.name.startswith("_") or count_private
            if is_public:
                public += 1
            if any(is_stub_decorator(d) for d in node.decorator_list):
                stubs += 1
            self.generic_visit(node)
        
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.visit_FunctionDef(node)  # Same logic
    
    FunctionVisitor().visit(tree)
    return ModuleStats(
        name=module_name,
        file=str(file_path),
        functions_total=total,
        functions_public=public,
        stubs=stubs
    )