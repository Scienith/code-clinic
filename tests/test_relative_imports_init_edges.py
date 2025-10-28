from __future__ import annotations

from pathlib import Path

from codeclinic.data_collector import collect_project_data


def _w(p: Path, rel: str, content: str) -> None:
    f = p / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_package_init_relative_import_edges(tmp_path: Path) -> None:
    # Build a minimal src layout with package + subpackage + module
    src = tmp_path / "src"
    pkg = src / "pkg"
    sub = pkg / "subpkg"

    # Files
    _w(src, "pkg/__init__.py", "from .subpkg import mod1\nfrom .subpkg.mod1 import Foo\n")
    _w(src, "pkg/subpkg/__init__.py", "from . import mod1\n")
    _w(src, "pkg/subpkg/mod1.py", "class Foo: ...\n")

    # Collect
    project = collect_project_data(paths=[str(src)], include=["**/*.py"], exclude=["**/tests/**"], count_private=False, config={})

    # Expect nodes exist
    assert "pkg" in project.packages
    assert "pkg.subpkg" in project.packages
    assert "pkg.subpkg.mod1" in project.modules

    # Edges: from package __init__ to subpackage (via from .subpkg import mod1)
    edges = project.import_edges
    assert ("pkg", "pkg.subpkg") in edges

    # Edges: from package __init__ to submodule (via from .subpkg.mod1 import Foo)
    assert ("pkg", "pkg.subpkg.mod1") in edges


def test_require_via_aggregator_gate_flags_deep_module(tmp_path: Path) -> None:
    # Same layout
    src = tmp_path / "src"
    _w(src, "pkg/__init__.py", "from .subpkg.mod1 import Foo\n")
    _w(src, "pkg/subpkg/__init__.py", "from . import mod1\n")
    _w(src, "pkg/subpkg/mod1.py", "class Foo: ...\n")

    cfg = {
        "import_rules": {
            "matrix_default": "allow",
            "forbid_private_modules": False,
            "require_via_aggregator": True,
            "allowed_external_depth": 0,
            "aggregator_whitelist": [],
        }
    }
    project = collect_project_data(paths=[str(src)], include=["**/*.py"], exclude=["**/tests/**"], count_private=False, config=cfg)

    # Build violations through engine
    from codeclinic.import_rules import check_import_violations

    violations = check_import_violations(project)
    kinds = {v.violation_type for v in violations}
    pairs = {(v.from_node, v.to_node) for v in violations}
    assert "require_via_aggregator" in kinds
    assert ("pkg", "pkg.subpkg.mod1") in pairs

