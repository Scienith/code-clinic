from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Set, Tuple, List, Optional

@dataclass
class ModuleStats:
    name: str
    file: str
    functions_total: int = 0
    functions_public: int = 0
    stubs: int = 0

    @property
    def stub_ratio(self) -> float:
        if self.functions_public == 0:
            return 0.0
        return self.stubs / max(1, self.functions_public)

@dataclass
class StubFunction:
    """Information about a function/method marked with @stub decorator."""
    module_name: str
    file_path: str
    function_name: str
    full_name: str  # className.method_name or just function_name
    docstring: Optional[str]
    line_number: int
    is_method: bool
    class_name: Optional[str] = None

GraphEdges = Set[Tuple[str, str]]
ChildEdges = Set[Tuple[str, str]]  # Parent -> Child relationships
Modules = Dict[str, ModuleStats]
StubFunctions = List[StubFunction]
