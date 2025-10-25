import os
import sys
from pathlib import Path
import pytest

# Ensure repo_root/src is on sys.path (work with any pytest cwd)
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

from codeclinic.import_rules import ImportRuleChecker
from codeclinic.node_types import NodeInfo, NodeType, ProjectData
from codeclinic.config_loader import ImportRulesConfig
from codeclinic import data_collector as dc


def _pkg(name: str) -> NodeInfo:
    return NodeInfo(name=name, node_type=NodeType.PACKAGE, file_path=f"/tmp/{name.replace('.', '/')}/__init__.py")


def _mod(name: str) -> NodeInfo:
    return NodeInfo(name=name, node_type=NodeType.MODULE, file_path=f"/tmp/{name.replace('.', '/')}.py")


def _project(nodes: list[NodeInfo], edges: list[tuple[str, str]]) -> ProjectData:
    pd = ProjectData()
    pd.nodes = {n.name: n for n in nodes}
    pd.import_edges = set(edges)
    return pd


def test_allow_ancestor_packages_with_descendants():
    # apps.orders.api.** -> apps.orders.services.** should be allowed
    nodes = [
        _pkg("apps"),
        _pkg("apps.orders"),
        _pkg("apps.orders.api"),
        _pkg("apps.orders.services"),
        _mod("apps.orders.api.views"),
        _mod("apps.orders.services.repo"),
        _mod("apps.orders.models"),
    ]
    edges = [
        ("apps.orders.api.views", "apps.orders.services.repo"),  # allowed by matrix
        ("apps.orders.api.views", "apps.orders.models"),         # not allowed (default deny)
    ]
    cfg = ImportRulesConfig(
        allow_patterns=[["<ancestor>.api.**", "<ancestor>.services.**"]],
        deny_patterns=[],
        matrix_default="deny",
    )
    checker = ImportRuleChecker(cfg)
    pd = _project(nodes, edges)
    viols = checker.check_violations(pd)
    # exactly 1 violation: api.views -> models (not allowed)
    assert len(viols) == 1
    assert viols[0].from_node == "apps.orders.api.views"
    assert viols[0].to_node == "apps.orders.models"
    assert viols[0].violation_type == "pattern_matrix"


def test_types_root_only_allowed_disallow_children():
    # allow only <ancestor>.types (root), but disallow <ancestor>.types.*
    nodes = [
        _pkg("apps"),
        _pkg("apps.orders"),
        _mod("apps.orders.types"),
        _mod("apps.orders.types.x"),
        _mod("apps.orders.api.handlers"),
    ]
    edges = [
        ("apps.orders.api.handlers", "apps.orders.types"),
        ("apps.orders.api.handlers", "apps.orders.types.x"),
    ]
    # 严格白名单：仅允许根 <ancestor>.types；未列出的（子模块）默认拒
    cfg = ImportRulesConfig(
        allow_patterns=[["*", "<ancestor>.types"]],
        deny_patterns=[],
        matrix_default="deny",
    )
    checker = ImportRuleChecker(cfg)
    pd = _project(nodes, edges)
    viols = checker.check_violations(pd)
    # Only the child import should violate
    assert len(viols) == 1
    assert viols[0].to_node == "apps.orders.types.x"
    assert viols[0].violation_type == "pattern_matrix"


def test_direct_child_vs_descendants_patterns():
    # dest pattern pkg.* allows only direct children, not grandchildren
    nodes = [
        _pkg("pkg"),
        _mod("pkg.child"),
        _mod("pkg.child.grand"),
        _mod("src.mod"),
    ]
    edges = [
        ("src.mod", "pkg.child"),          # should be allowed
        ("src.mod", "pkg.child.grand"),     # should be denied by default
    ]
    cfg = ImportRulesConfig(
        allow_patterns=[["src.mod", "pkg.*"]],
        deny_patterns=[],
        matrix_default="deny",
    )
    checker = ImportRuleChecker(cfg)
    pd = _project(nodes, edges)
    viols = checker.check_violations(pd)
    assert len(viols) == 1
    assert viols[0].to_node == "pkg.child.grand"
    assert viols[0].violation_type == "pattern_matrix"


def test_forbid_private_module_segments():
    # even with wide allow, private path segment triggers violation
    nodes = [
        _pkg("apps"),
        _pkg("apps.orders"),
        _pkg("apps.orders.api"),
        _mod("apps.orders.api._impl"),
        _mod("apps.orders.api.views"),
    ]
    edges = [
        ("apps.orders.api.views", "apps.orders.api._impl"),
    ]
    cfg = ImportRulesConfig(
        allow_patterns=[["*.**", "*.**"]],  # would normally allow everything
        deny_patterns=[],
        matrix_default="allow",
        forbid_private_modules=True,
    )
    checker = ImportRuleChecker(cfg)
    pd = _project(nodes, edges)
    viols = checker.check_violations(pd)
    assert len(viols) == 1
    assert viols[0].violation_type == "private_module_import"


def test_external_imports_are_ignored(tmp_path):
    # Create a temp python file that imports a third-party package
    p = tmp_path / "views.py"
    p.write_text("""
import pandas
from pandas import DataFrame
""", encoding="utf-8")

    node = _mod("apps.orders.api.views")
    node.file_path = str(p)
    nodes = {
        "apps": _pkg("apps"),
        "apps.orders": _pkg("apps.orders"),
        "apps.orders.api": _pkg("apps.orders.api"),
        node.name: node,
    }

    # Analyze imports; third-party should not be resolved/added
    dc._analyze_node_imports(node, nodes)
    assert not node.imports, "third-party imports must not create internal edges"

    # With strict white-list (empty allow), no violations since no edges
    pd = _project(list(nodes.values()), [])
    cfg = ImportRulesConfig(allow_patterns=[], deny_patterns=[], matrix_default="deny")
    checker = ImportRuleChecker(cfg)
    viols = checker.check_violations(pd)
    assert len(viols) == 0
