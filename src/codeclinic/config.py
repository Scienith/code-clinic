from __future__ import annotations
import os
import pathlib
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict

try:  # py3.11+
    import tomllib as tomli  # type: ignore
except Exception:  # pragma: no cover
    import tomli  # type: ignore


@dataclass
class Config:
    paths: List[str] = field(default_factory=lambda: ["src", "."])
    include: List[str] = field(default_factory=lambda: ["**/*.py"])
    exclude: List[str] = field(default_factory=lambda: [
        "**/tests/**", "**/.venv/**", "**/venv/**", "**/__pycache__/**", "**/build/**", "**/dist/**"
    ])
    aggregate: str = "module"  # or "package"
    format: str = "svg"
    output: str = "codeclinic_graph"
    count_private: bool = False

    @classmethod
    def from_files(cls, cwd: str) -> "Config":
        cfg = cls()
        # 1) pyproject.toml
        pp = pathlib.Path(cwd) / "pyproject.toml"
        if pp.exists():
            with pp.open("rb") as f:
                data = tomli.load(f)
            tool = data.get("tool", {}).get("codeclinic", {})
            cfg = _merge_cfg(cfg, tool)
        # 2) codeclinic.toml
        alt = pathlib.Path(cwd) / "codeclinic.toml"
        if alt.exists():
            with alt.open("rb") as f:
                data2 = tomli.load(f)
            cfg = _merge_cfg(cfg, data2)
        return cfg


def _merge_cfg(cfg: Config, data: Dict[str, Any]) -> Config:
    for k, v in data.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg
