"""
配置加载器 - 支持YAML格式配置文件
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    yaml = None

try:  # py3.11+
    import tomllib as tomli
except ImportError:
    try:
        import tomli
    except ImportError:
        tomli = None


@dataclass
class ImportRulesConfig:
    """导入规则配置"""
    white_list: List[str] = field(default_factory=list)
    allow_cross_package: bool = False
    allow_upward_import: bool = False
    allow_skip_levels: bool = False


@dataclass 
class ExtendedConfig:
    """扩展配置，包含导入规则"""
    # 基础配置
    paths: List[str] = field(default_factory=lambda: ["src", "."])
    include: List[str] = field(default_factory=lambda: ["**/*.py"])
    exclude: List[str] = field(default_factory=lambda: [
        "**/tests/**", "**/.venv/**", "**/venv/**", "**/__pycache__/**", 
        "**/build/**", "**/dist/**"
    ])
    aggregate: str = "module"  # or "package"
    format: str = "svg"
    output: str = "codeclinic_results"
    count_private: bool = False
    
    # 导入规则配置
    import_rules: ImportRulesConfig = field(default_factory=ImportRulesConfig)
    
    def to_legacy_config(self):
        """转换为旧版Config对象，保持向后兼容"""
        from .config import Config
        return Config(
            paths=self.paths,
            include=self.include,
            exclude=self.exclude,
            aggregate=self.aggregate,
            format=self.format,
            output=self.output,
            count_private=self.count_private
        )


def load_config(config_path: Optional[Path] = None) -> ExtendedConfig:
    """
    加载配置文件
    
    Args:
        config_path: 指定配置文件路径，如果为None则自动查找
    
    Returns:
        ExtendedConfig: 加载的配置
    """
    if config_path:
        return _load_config_file(config_path)
    
    # 自动查找配置文件
    found_config = find_config_file()
    if found_config:
        print(f"找到配置文件: {found_config}")
        return _load_config_file(found_config)
    
    # 使用默认配置时显示详细提示
    _show_default_config_info()
    return ExtendedConfig()


def find_config_file() -> Optional[Path]:
    """
    按优先级查找配置文件
    
    Returns:
        Path: 找到的配置文件路径，如果没找到返回None
    """
    candidates = [
        Path('codeclinic.yaml'),
        Path('codeclinic.yml'),
        Path('.codeclinic.yaml'),
        Path('.codeclinic.yml'),
        Path('pyproject.toml'),  # 检查 [tool.codeclinic]
    ]
    
    for candidate in candidates:
        if candidate.exists():
            # 对于pyproject.toml，检查是否有[tool.codeclinic]配置
            if candidate.name == 'pyproject.toml':
                if _has_codeclinic_config(candidate):
                    return candidate
                continue
            return candidate
    
    return None


def _load_config_file(config_path: Path) -> ExtendedConfig:
    """加载指定的配置文件"""
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    suffix = config_path.suffix.lower()
    
    if suffix in ['.yaml', '.yml']:
        return _load_yaml_config(config_path)
    elif suffix == '.toml':
        return _load_toml_config(config_path)
    else:
        raise ValueError(f"不支持的配置文件格式: {suffix}")


def _load_yaml_config(config_path: Path) -> ExtendedConfig:
    """加载YAML配置文件"""
    if yaml is None:
        raise ImportError("需要安装PyYAML才能读取YAML配置文件: pip install pyyaml")
    
    with config_path.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    if not data:
        return ExtendedConfig()
    
    return _parse_config_data(data)


def _load_toml_config(config_path: Path) -> ExtendedConfig:
    """加载TOML配置文件"""
    if tomli is None:
        raise ImportError("需要安装tomli才能读取TOML配置文件: pip install tomli")
    
    with config_path.open('rb') as f:
        data = tomli.load(f)
    
    # 检查是否是pyproject.toml格式
    if 'tool' in data and 'codeclinic' in data['tool']:
        config_data = data['tool']['codeclinic']
    else:
        config_data = data
    
    return _parse_config_data(config_data)


def _has_codeclinic_config(pyproject_path: Path) -> bool:
    """检查pyproject.toml是否包含codeclinic配置"""
    if tomli is None:
        return False
    
    try:
        with pyproject_path.open('rb') as f:
            data = tomli.load(f)
        return 'tool' in data and 'codeclinic' in data['tool']
    except Exception:
        return False


def _parse_config_data(data: Dict[str, Any]) -> ExtendedConfig:
    """解析配置数据"""
    config = ExtendedConfig()
    
    # 基础配置
    if 'paths' in data:
        config.paths = data['paths']
    if 'include' in data:
        config.include = data['include']
    if 'exclude' in data:
        config.exclude = data['exclude']
    if 'aggregate' in data:
        config.aggregate = data['aggregate']
    if 'format' in data:
        config.format = data['format']
    if 'output' in data:
        config.output = data['output']
    if 'count_private' in data:
        config.count_private = data['count_private']
    
    # 导入规则配置
    if 'import_rules' in data:
        rules_data = data['import_rules']
        import_rules = ImportRulesConfig()
        
        if 'white_list' in rules_data:
            import_rules.white_list = rules_data['white_list']
        
        # 规则开关
        if 'rules' in rules_data:
            rule_switches = rules_data['rules']
            if 'allow_cross_package' in rule_switches:
                import_rules.allow_cross_package = rule_switches['allow_cross_package']
            if 'allow_upward_import' in rule_switches:
                import_rules.allow_upward_import = rule_switches['allow_upward_import']
            if 'allow_skip_levels' in rule_switches:
                import_rules.allow_skip_levels = rule_switches['allow_skip_levels']
        
        # 支持旧版格式（直接在import_rules下）
        if 'allow_cross_package' in rules_data:
            import_rules.allow_cross_package = rules_data['allow_cross_package']
        if 'allow_upward_import' in rules_data:
            import_rules.allow_upward_import = rules_data['allow_upward_import']
        if 'allow_skip_levels' in rules_data:
            import_rules.allow_skip_levels = rules_data['allow_skip_levels']
        
        config.import_rules = import_rules
    
    return config


def create_example_config() -> str:
    """创建示例配置文件内容"""
    return """# CodeClinic配置文件
version: "1.0"

# 基础配置
paths:
  - "src"
output: "codeclinic_results"
format: "svg"
count_private: false

# 包含/排除模式
include:
  - "**/*.py"
exclude:
  - "**/tests/**"
  - "**/.venv/**"
  - "**/venv/**"
  - "**/__pycache__/**"
  - "**/build/**"
  - "**/dist/**"

# 导入规则配置
import_rules:
  # 白名单：这些模块可以被任何地方导入
  white_list:
    - "myproject.types"      # 类型定义
    - "myproject.utils"      # 工具函数
    - "myproject.constants"  # 常量定义
    
  # 规则开关
  rules:
    allow_cross_package: false    # 禁止跨包导入
    allow_upward_import: false    # 禁止子模块导入父模块
    allow_skip_levels: false      # 禁止跳级导入
"""


def save_example_config(output_path: Path = None) -> Path:
    """保存示例配置文件"""
    if output_path is None:
        output_path = Path("codeclinic.yaml")
    
    content = create_example_config()
    output_path.write_text(content, encoding='utf-8')
    
    return output_path


# 向后兼容的函数
def load_legacy_config(cwd: str = None):
    """加载旧版配置格式，保持向后兼容"""
    if cwd is None:
        cwd = os.getcwd()
    
    config_path = find_config_file()
    if config_path:
        extended_config = load_config(config_path)
        # 将扩展配置转换为旧版Config
        legacy_config = extended_config.to_legacy_config()
        # 添加import_rules信息到旧版配置
        setattr(legacy_config, 'import_rules', extended_config.import_rules)
        return legacy_config
    
    # 如果没有找到新配置，尝试加载旧版配置
    from .config import Config
    return Config.from_files(cwd)


def _show_default_config_info() -> None:
    """显示默认配置信息"""
    print("📋 使用默认配置:")
    print("━" * 40)
    print("🔒 导入规则:")
    print("  ❌ 跨包导入 (禁止)")
    print("  ❌ 向上导入 (禁止)")
    print("  ❌ 跳级导入 (禁止)")
    print("  📝 白名单: 无")
    print()
    print("💡 提示:")
    print("  • 生成配置: 'codeclinic --init'")
    print("  • 查看配置: 'codeclinic --show-config'")
    print("  • 编辑配置: 修改 codeclinic.yaml")