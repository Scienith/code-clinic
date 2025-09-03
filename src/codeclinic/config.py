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
class ImportRulesConfig:
    """导入规则配置 - 向后兼容版本"""
    white_list: List[str] = field(default_factory=list)
    allow_cross_package: bool = False
    allow_upward_import: bool = False
    allow_skip_levels: bool = False


@dataclass
class Config:
    """
    传统配置类，增加了导入规则支持
    保持向后兼容性，同时支持新功能
    """
    paths: List[str] = field(default_factory=lambda: ["src", "."])
    include: List[str] = field(default_factory=lambda: ["**/*.py"])
    exclude: List[str] = field(default_factory=lambda: [
        "**/tests/**", "**/.venv/**", "**/venv/**", "**/__pycache__/**", "**/build/**", "**/dist/**"
    ])
    aggregate: str = "module"  # or "package"
    format: str = "svg"
    output: str = "codeclinic_results"
    count_private: bool = False
    
    # 新增：导入规则配置
    import_rules: ImportRulesConfig = field(default_factory=ImportRulesConfig)

    @classmethod
    def from_files(cls, cwd: str) -> "Config":
        cfg = cls()
        
        # 1) 尝试使用新版配置加载器
        try:
            from .config_loader import load_legacy_config
            return load_legacy_config(cwd)
        except ImportError:
            # 如果新版加载器不可用，使用传统方法
            pass
        
        # 2) 传统配置加载方法
        # pyproject.toml
        pp = pathlib.Path(cwd) / "pyproject.toml"
        if pp.exists():
            with pp.open("rb") as f:
                data = tomli.load(f)
            tool = data.get("tool", {}).get("codeclinic", {})
            cfg = _merge_cfg(cfg, tool)
        
        # codeclinic.toml
        alt = pathlib.Path(cwd) / "codeclinic.toml"
        if alt.exists():
            with alt.open("rb") as f:
                data2 = tomli.load(f)
            cfg = _merge_cfg(cfg, data2)
        
        return cfg


def _merge_cfg(cfg: Config, data: Dict[str, Any]) -> Config:
    """合并配置数据到Config对象"""
    for k, v in data.items():
        if k == "import_rules" and isinstance(v, dict):
            # 特殊处理导入规则配置
            import_rules = ImportRulesConfig()
            
            # 基本规则
            if "white_list" in v:
                import_rules.white_list = v["white_list"]
            if "allow_cross_package" in v:
                import_rules.allow_cross_package = v["allow_cross_package"]
            if "allow_upward_import" in v:
                import_rules.allow_upward_import = v["allow_upward_import"]
            if "allow_skip_levels" in v:
                import_rules.allow_skip_levels = v["allow_skip_levels"]
            
            # 支持嵌套的rules结构
            if "rules" in v:
                rules = v["rules"]
                if "allow_cross_package" in rules:
                    import_rules.allow_cross_package = rules["allow_cross_package"]
                if "allow_upward_import" in rules:
                    import_rules.allow_upward_import = rules["allow_upward_import"]
                if "allow_skip_levels" in rules:
                    import_rules.allow_skip_levels = rules["allow_skip_levels"]
            
            cfg.import_rules = import_rules
        elif hasattr(cfg, k):
            setattr(cfg, k, v)
    
    return cfg


def create_example_legacy_config() -> str:
    """创建示例配置文件（TOML格式）"""
    return '''# CodeClinic 配置文件
[tool.codeclinic]
paths = ["src"]
output = "codeclinic_results"
format = "svg"
count_private = false

# 导入规则配置
[tool.codeclinic.import_rules]
white_list = [
    "myproject.types",
    "myproject.utils",
    "myproject.constants"
]

[tool.codeclinic.import_rules.rules]
allow_cross_package = false
allow_upward_import = false
allow_skip_levels = false
'''
