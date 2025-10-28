"""
新的数据模型定义，支持区分module和package
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class NodeType(Enum):
    """节点类型枚举"""

    MODULE = "module"  # 单个.py文件
    PACKAGE = "package"  # 包含__init__.py的文件夹


@dataclass
class FunctionInfo:
    """函数/方法信息"""

    name: str  # 函数名
    full_name: str  # 完整名称 (class.method 或 function)
    is_stub: bool  # 是否标记为@stub
    is_public: bool  # 是否为公共函数 (不以_开头)
    docstring: Optional[str]  # 文档字符串
    line_number: int  # 行号
    is_method: bool = False  # 是否为方法
    class_name: Optional[str] = None  # 所属类名
    module_name: str = ""  # 所属模块名（向后兼容）
    file_path: str = ""  # 文件路径（向后兼容）


@dataclass
class NodeInfo:
    """节点信息，可以是module或package"""

    name: str  # 全限定名 e.g., "codeclinic.ast_scanner"
    node_type: NodeType  # MODULE 或 PACKAGE
    file_path: str  # .py文件路径或__init__.py路径

    # 内容信息（对package来说，这是__init__.py的内容）
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: Dict[str, List[FunctionInfo]] = field(
        default_factory=dict
    )  # class_name -> methods

    # 导入信息
    imports: Set[str] = field(default_factory=set)  # 此节点导入的其他节点

    # 统计信息
    functions_total: int = 0
    functions_public: int = 0
    stubs: int = 0
    stub_ratio: float = 0.0

    # 层级信息
    parent: Optional[str] = None  # 父package名称
    children: Set[str] = field(default_factory=set)  # 子module/package名称

    # 两种深度
    package_depth: int = 0  # 包层级深度（基于目录结构）
    graph_depth: int = 0  # 依赖图深度（基于import关系的最大路径长度）

    def __post_init__(self):
        """计算衍生属性"""
        # 计算总函数数（包括所有函数和方法）
        total_functions = len(self.functions)
        total_public_functions = len([f for f in self.functions if f.is_public])
        total_stubs = len([f for f in self.functions if f.is_stub])

        # 添加类方法统计
        for methods in self.classes.values():
            total_functions += len(methods)
            total_public_functions += len([m for m in methods if m.is_public])
            total_stubs += len([m for m in methods if m.is_stub])

        self.functions_total = total_functions
        self.functions_public = total_public_functions
        self.stubs = total_stubs
        # 按要求：分母为“函数+方法总数”，不区分public
        self.stub_ratio = total_stubs / max(1, total_functions)
        self.package_depth = self.name.count(".")


@dataclass
class ImportViolation:
    """导入违规信息"""

    from_node: str  # 违规的源节点
    to_node: str  # 违规的目标节点
    violation_type: str  # 违规类型
    message: str  # 违规描述
    severity: str = "error"  # 严重程度: error, warning, info


@dataclass
class ProjectData:
    """完整的项目分析数据"""

    version: str = "1.0"
    timestamp: str = ""
    project_root: str = ""

    # 核心数据
    nodes: Dict[str, NodeInfo] = field(default_factory=dict)  # name -> NodeInfo
    import_edges: Set[Tuple[str, str]] = field(
        default_factory=set
    )  # (from, to) 导入关系
    child_edges: Set[Tuple[str, str]] = field(
        default_factory=set
    )  # (parent, child) 包含关系

    # 配置信息
    config: Dict = field(default_factory=dict)

    # 便利访问器
    @property
    def modules(self) -> Dict[str, NodeInfo]:
        """获取所有module节点"""
        return {k: v for k, v in self.nodes.items() if v.node_type == NodeType.MODULE}

    @property
    def packages(self) -> Dict[str, NodeInfo]:
        """获取所有package节点"""
        return {k: v for k, v in self.nodes.items() if v.node_type == NodeType.PACKAGE}

    @property
    def all_functions(self) -> List[FunctionInfo]:
        """获取所有函数信息"""
        functions = []
        for node in self.nodes.values():
            functions.extend(node.functions)
            for methods in node.classes.values():
                functions.extend(methods)
        return functions

    @property
    def stub_functions(self) -> List[FunctionInfo]:
        """获取所有stub函数"""
        return [f for f in self.all_functions if f.is_stub]


# 类型别名
GraphEdges = Set[Tuple[str, str]]
ChildEdges = Set[Tuple[str, str]]
Modules = Dict[str, NodeInfo]  # 保持向后兼容
StubFunctions = List[FunctionInfo]  # 保持向后兼容
