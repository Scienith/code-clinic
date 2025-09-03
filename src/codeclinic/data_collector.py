"""
统一数据收集器 - 收集项目中所有module和package的信息
"""

from __future__ import annotations
import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
from datetime import datetime

from .node_types import (
    NodeType, NodeInfo, FunctionInfo, ProjectData,
    GraphEdges, ChildEdges
)


def collect_project_data(
    paths: List[str], 
    include: List[str], 
    exclude: List[str], 
    count_private: bool,
    config: Dict = None
) -> ProjectData:
    """
    收集完整的项目数据
    """
    project_data = ProjectData(
        timestamp=datetime.now().isoformat(),
        project_root=",".join(paths),
        config=config or {}
    )
    
    print(f"开始收集项目数据，扫描路径: {paths}")
    
    # 第一步：收集所有Python文件并识别节点
    all_files = _collect_python_files(paths, include, exclude)
    project_data.nodes = _identify_nodes(all_files, paths)
    
    print(f"识别到 {len(project_data.nodes)} 个节点 "
          f"({len(project_data.modules)} modules, {len(project_data.packages)} packages)")
    
    # 第二步：分析每个节点的内容和导入
    for node_name, node in project_data.nodes.items():
        _analyze_node_content(node, count_private)
        _analyze_node_imports(node, project_data.nodes)
    
    # 第三步：构建关系图
    project_data.import_edges, project_data.child_edges = _build_relationships(project_data.nodes)
    
    # 第四步：计算深度
    _calculate_depths(project_data)
    
    print(f"分析完成: {len(project_data.import_edges)} 个导入关系, "
          f"{len(project_data.child_edges)} 个包含关系")
    
    return project_data


def _collect_python_files(paths: List[str], include: List[str], exclude: List[str]) -> Dict[str, Path]:
    """收集所有Python文件"""
    all_files = {}
    
    for path_str in paths:
        path = Path(path_str).resolve()
        if not path.exists():
            print(f"警告: 路径 {path} 不存在")
            continue
            
        if path.is_file() and path.suffix == '.py':
            # 单个文件
            module_name = path.stem
            all_files[module_name] = path
        else:
            # 目录
            for py_file in _walk_python_files(path, include, exclude):
                rel_path = py_file.relative_to(path)
                module_name = _path_to_module_name(rel_path)
                all_files[module_name] = py_file
    
    return all_files


def _walk_python_files(base_path: Path, include: List[str], exclude: List[str]) -> List[Path]:
    """遍历目录收集Python文件"""
    python_files = []
    
    for root, dirs, files in os.walk(base_path):
        root_path = Path(root)
        
        # 过滤目录
        dirs[:] = [d for d in dirs if not _should_exclude_dir(root_path / d, exclude)]
        
        for file in files:
            if file.endswith('.py'):
                file_path = root_path / file
                if _should_include_file(file_path, base_path, include, exclude):
                    python_files.append(file_path)
    
    return python_files


def _should_exclude_dir(dir_path: Path, exclude: List[str]) -> bool:
    """检查目录是否应被排除"""
    DEFAULT_EXCLUDE_DIRS = {
        ".git", ".hg", ".svn", "__pycache__", "build", "dist", 
        ".venv", "venv", ".pytest_cache", "node_modules"
    }
    
    if dir_path.name in DEFAULT_EXCLUDE_DIRS:
        return True
        
    for pattern in exclude:
        if dir_path.match(pattern):
            return True
    
    return False


def _should_include_file(file_path: Path, base_path: Path, include: List[str], exclude: List[str]) -> bool:
    """检查文件是否应被包含"""
    try:
        rel_path = file_path.relative_to(base_path)
    except ValueError:
        return False
    
    # 先检查排除模式
    for pattern in exclude:
        if rel_path.match(pattern):
            return False
    
    # 如果没有包含模式，或者是.py文件，则包含
    if not include or file_path.suffix == '.py':
        return True
        
    # 检查包含模式
    for pattern in include:
        if rel_path.match(pattern):
            return True
    
    return False


def _path_to_module_name(rel_path: Path) -> str:
    """将相对路径转换为模块名"""
    # 移除.py扩展名
    if rel_path.suffix == '.py':
        rel_path = rel_path.with_suffix('')
    
    # 转换路径分隔符为点
    parts = rel_path.parts
    
    # 处理__init__.py文件
    if parts and parts[-1] == '__init__':
        parts = parts[:-1]
    
    return '.'.join(parts) if parts else rel_path.stem


def _identify_nodes(all_files: Dict[str, Path], root_paths: List[str]) -> Dict[str, NodeInfo]:
    """识别所有节点，区分module和package"""
    nodes = {}
    
    # 识别所有package（有__init__.py的目录）
    package_dirs = set()
    for file_path in all_files.values():
        if file_path.name == '__init__.py':
            package_dir = file_path.parent
            # 计算package的模块名
            for root_str in root_paths:
                root_path = Path(root_str).resolve()
                try:
                    rel_path = package_dir.relative_to(root_path)
                    package_name = _path_to_module_name(rel_path)
                    package_dirs.add((package_name, file_path))
                    break
                except ValueError:
                    continue
    
    # 创建package节点
    for package_name, init_file in package_dirs:
        nodes[package_name] = NodeInfo(
            name=package_name,
            node_type=NodeType.PACKAGE,
            file_path=str(init_file)
        )
    
    # 创建module节点（非__init__.py文件）
    for module_name, file_path in all_files.items():
        if file_path.name != '__init__.py':
            nodes[module_name] = NodeInfo(
                name=module_name,
                node_type=NodeType.MODULE,
                file_path=str(file_path)
            )
    
    # 建立父子关系
    for node_name, node in nodes.items():
        parts = node_name.split('.')
        if len(parts) > 1:
            parent_name = '.'.join(parts[:-1])
            if parent_name in nodes:
                node.parent = parent_name
                nodes[parent_name].children.add(node_name)
    
    return nodes


def _analyze_node_content(node: NodeInfo, count_private: bool) -> None:
    """分析节点内容（函数、类等）"""
    try:
        content = Path(node.file_path).read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(content, filename=node.file_path)
    except (OSError, SyntaxError) as e:
        print(f"警告: 无法解析 {node.file_path}: {e}")
        return
    
    visitor = _FunctionVisitor(node.name, count_private)
    visitor.visit(tree)
    
    # 设置函数的file_path
    for func in visitor.functions:
        func.file_path = node.file_path
    for methods in visitor.classes.values():
        for method in methods:
            method.file_path = node.file_path
    
    node.functions = visitor.functions
    node.classes = visitor.classes
    
    # 强制重新计算统计信息
    node.__post_init__()


def _analyze_node_imports(node: NodeInfo, all_nodes: Dict[str, NodeInfo]) -> None:
    """分析节点的导入关系"""
    try:
        content = Path(node.file_path).read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(content, filename=node.file_path)
    except (OSError, SyntaxError) as e:
        return
    
    imports = set()
    
    class ImportVisitor(ast.NodeVisitor):
        def visit_Import(self, node_ast: ast.Import) -> None:
            for alias in node_ast.names:
                imports.add(alias.name)
        
        def visit_ImportFrom(self, node_ast: ast.ImportFrom) -> None:
            if node_ast.module:
                imports.add(node_ast.module)
                # 也添加具体导入，可能是子模块
                for alias in node_ast.names:
                    if alias.name != '*':
                        full_name = f"{node_ast.module}.{alias.name}"
                        imports.add(full_name)
    
    ImportVisitor().visit(tree)
    
    # 解析导入，只保留内部模块
    for import_name in imports:
        resolved = _resolve_import(import_name, all_nodes)
        if resolved and resolved != node.name:
            node.imports.add(resolved)


def _resolve_import(import_name: str, all_nodes: Dict[str, NodeInfo]) -> Optional[str]:
    """解析导入名称到实际模块"""
    # 直接匹配
    if import_name in all_nodes:
        return import_name
    
    # 处理绝对导入（如 example_project.common -> common）
    parts = import_name.split('.')
    if len(parts) > 1:
        # 尝试移除第一个部分（项目名）
        relative_name = '.'.join(parts[1:])
        if relative_name in all_nodes:
            return relative_name
        
        # 尝试移除更多前缀部分
        for i in range(2, len(parts)):
            candidate = '.'.join(parts[i:])
            if candidate in all_nodes:
                return candidate
    
    # 寻找部分匹配
    for node_name in all_nodes:
        if node_name.startswith(import_name + '.') or node_name.endswith('.' + import_name):
            return node_name
        
        # 检查是否为相同的后缀（如 example_project.A.A1.A12 匹配 A.A1.A12）
        if import_name.endswith('.' + node_name) or node_name.endswith('.' + import_name.split('.')[-1]):
            # 更精确的后缀匹配
            import_parts = import_name.split('.')
            node_parts = node_name.split('.')
            if len(import_parts) >= len(node_parts):
                if import_parts[-len(node_parts):] == node_parts:
                    return node_name
    
    return None


def _build_relationships(nodes: Dict[str, NodeInfo]) -> Tuple[GraphEdges, ChildEdges]:
    """构建导入关系和包含关系"""
    import_edges = set()
    child_edges = set()
    
    for node_name, node in nodes.items():
        # 导入关系
        for imported in node.imports:
            if imported in nodes:
                import_edges.add((node_name, imported))
        
        # 包含关系
        if node.parent:
            child_edges.add((node.parent, node_name))
    
    return import_edges, child_edges


def _calculate_depths(project_data: ProjectData) -> None:
    """计算两种深度"""
    # 1. 包深度已在NodeInfo.__post_init__中计算
    
    # 2. 计算依赖图深度
    graph_depths = _calculate_graph_depths(project_data.import_edges)
    
    for node_name, node in project_data.nodes.items():
        node.graph_depth = graph_depths.get(node_name, 0)


def _calculate_graph_depths(edges: GraphEdges) -> Dict[str, int]:
    """计算依赖图中每个节点的最大深度"""
    adj: Dict[str, List[str]] = defaultdict(list)
    reverse_adj: Dict[str, List[str]] = defaultdict(list)
    all_nodes: Set[str] = set()
    
    for src, dst in edges:
        adj[src].append(dst)
        reverse_adj[dst].append(src)
        all_nodes.add(src)
        all_nodes.add(dst)
    
    # 找出根节点（无入边）
    root_nodes = [node for node in all_nodes if not reverse_adj[node]]
    
    # 如果存在循环，选择包深度最小的作为根
    if not root_nodes and all_nodes:
        root_nodes = [min(all_nodes, key=lambda n: n.count('.'))]
    
    # BFS计算最大深度
    depths: Dict[str, int] = {}
    
    for root in root_nodes:
        queue = deque([(root, 0)])
        visited: Set[str] = set()
        
        while queue:
            node, depth = queue.popleft()
            
            if node in visited:
                continue
            visited.add(node)
            
            # 更新为最大深度
            depths[node] = max(depths.get(node, 0), depth)
            
            # 添加邻居
            for neighbor in adj[node]:
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))
    
    # 确保所有节点都有深度
    for node in all_nodes:
        if node not in depths:
            depths[node] = 0
    
    return depths


class _FunctionVisitor(ast.NodeVisitor):
    """AST访问器，收集函数和类信息"""
    
    def __init__(self, module_name: str, count_private: bool):
        self.module_name = module_name
        self.count_private = count_private
        self.functions: List[FunctionInfo] = []
        self.classes: Dict[str, List[FunctionInfo]] = {}
        self.current_class = None
        self.class_stack = []
    
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(self.current_class)
        self.current_class = node.name
        self.classes[node.name] = []
        self.generic_visit(node)
        self.current_class = self.class_stack.pop()
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_function(node)
        self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_function(node)
        self.generic_visit(node)
    
    def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_public = not node.name.startswith("_") or self.count_private
        is_stub = self._has_stub_decorator(node)
        
        full_name = node.name
        if self.current_class:
            full_name = f"{self.current_class}.{node.name}"
        
        func_info = FunctionInfo(
            name=node.name,
            full_name=full_name,
            is_stub=is_stub,
            is_public=is_public,
            docstring=self._get_docstring(node),
            line_number=node.lineno,
            is_method=self.current_class is not None,
            class_name=self.current_class,
            module_name=self.module_name,
            file_path=""  # 文件路径后续设置
        )
        
        if self.current_class:
            self.classes[self.current_class].append(func_info)
        else:
            self.functions.append(func_info)
    
    def _has_stub_decorator(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """检查是否有@stub装饰器"""
        for decorator in node.decorator_list:
            name = self._get_decorator_name(decorator)
            if name.endswith("stub") or name == "stub":
                return True
        return False
    
    def _get_decorator_name(self, dec: ast.AST) -> str:
        """获取装饰器名称"""
        if isinstance(dec, ast.Name):
            return dec.id
        elif isinstance(dec, ast.Attribute):
            parts = []
            cur = dec
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            parts.reverse()
            return ".".join(parts)
        elif isinstance(dec, ast.Call):
            return self._get_decorator_name(dec.func)
        return ""
    
    def _get_docstring(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[str]:
        """提取函数文档字符串"""
        if (node.body and isinstance(node.body[0], ast.Expr) and 
            isinstance(node.body[0].value, ast.Constant) and 
            isinstance(node.body[0].value.value, str)):
            return node.body[0].value.value.strip()
        return None