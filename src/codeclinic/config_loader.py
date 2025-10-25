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
    # 新增：禁止私有模块导入（路径段以下划线开头）
    forbid_private_modules: bool = False
    # 新增：要求跨包导入必须通过聚合门面（PACKAGE/__init__.py）
    require_via_aggregator: bool = False
    # 允许外部导入的聚合门面最大子层级深度（0=仅顶层包，1=允许一级子包的 __init__，依此类推）
    allowed_external_depth: int = 0
    # 聚合门面白名单（允许直连的门面模块前缀或完整名）
    aggregator_whitelist: List[str] = field(default_factory=list)
    # 新增：基于矩阵的允许/禁止规则（source, target），支持宏 <ancestor>
    allow_patterns: List[tuple[str, str]] = field(default_factory=list)
    deny_patterns: List[tuple[str, str]] = field(default_factory=list)
    # 新增：矩阵默认策略：deny|allow（当 allow_patterns 非空但未匹配时如何处理）
    matrix_default: str = "deny"
    # 命名集合（schema），如 global/public，可在模式中用 <global>/<public> 宏展开
    schema: Dict[str, List[str]] = field(default_factory=dict)


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
        if 'aggregator_whitelist' in rules_data:
            import_rules.aggregator_whitelist = rules_data['aggregator_whitelist']
        
        # 规则开关
        if 'rules' in rules_data:
            rule_switches = rules_data['rules']
            if 'allow_cross_package' in rule_switches:
                import_rules.allow_cross_package = rule_switches['allow_cross_package']
            if 'allow_upward_import' in rule_switches:
                import_rules.allow_upward_import = rule_switches['allow_upward_import']
            if 'allow_skip_levels' in rule_switches:
                import_rules.allow_skip_levels = rule_switches['allow_skip_levels']
            if 'forbid_private_modules' in rule_switches:
                import_rules.forbid_private_modules = rule_switches['forbid_private_modules']
            if 'require_via_aggregator' in rule_switches:
                import_rules.require_via_aggregator = rule_switches['require_via_aggregator']
            if 'allowed_external_depth' in rule_switches:
                try:
                    import_rules.allowed_external_depth = int(rule_switches['allowed_external_depth'])
                except Exception:
                    import_rules.allowed_external_depth = 0
            # 新增：矩阵与默认策略
            allow_patterns = rule_switches.get('allow_patterns') or rule_switches.get('allowed_patterns')
            if isinstance(allow_patterns, list):
                parsed: list[tuple[str, str]] = []
                for item in allow_patterns:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        src, dst = str(item[0]).strip(), str(item[1]).strip()
                        parsed.append((src, dst))
                import_rules.allow_patterns = parsed
            deny_patterns = rule_switches.get('deny_patterns') or rule_switches.get('denied_patterns')
            if isinstance(deny_patterns, list):
                parsed_d: list[tuple[str, str]] = []
                for item in deny_patterns:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        src, dst = str(item[0]).strip(), str(item[1]).strip()
                        parsed_d.append((src, dst))
                import_rules.deny_patterns = parsed_d
            if 'matrix_default' in rule_switches:
                val = str(rule_switches['matrix_default']).strip().lower()
                if val in {"deny", "allow"}:
                    import_rules.matrix_default = val
            # schema 命名集合
            schema = rule_switches.get('schema')
            if isinstance(schema, dict):
                parsed_schema: Dict[str, List[str]] = {}
                for k, v in schema.items():
                    if isinstance(v, list):
                        parsed_schema[str(k)] = [str(x) for x in v]
                import_rules.schema = parsed_schema
        
        # 支持旧版格式（直接在import_rules下）
        if 'allow_cross_package' in rules_data:
            import_rules.allow_cross_package = rules_data['allow_cross_package']
        if 'allow_upward_import' in rules_data:
            import_rules.allow_upward_import = rules_data['allow_upward_import']
        if 'allow_skip_levels' in rules_data:
            import_rules.allow_skip_levels = rules_data['allow_skip_levels']
        if 'forbid_private_modules' in rules_data:
            import_rules.forbid_private_modules = rules_data['forbid_private_modules']
        if 'require_via_aggregator' in rules_data:
            import_rules.require_via_aggregator = rules_data['require_via_aggregator']
        if 'allowed_external_depth' in rules_data:
            try:
                import_rules.allowed_external_depth = int(rules_data['allowed_external_depth'])
            except Exception:
                import_rules.allowed_external_depth = 0
        if 'aggregator_whitelist' in rules_data:
            import_rules.aggregator_whitelist = rules_data['aggregator_whitelist']
        # schema 可直接在 import_rules 下声明
        schema2 = rules_data.get('schema')
        if isinstance(schema2, dict):
            parsed_schema2: Dict[str, List[str]] = {}
            for k, v in schema2.items():
                if isinstance(v, list):
                    parsed_schema2[str(k)] = [str(x) for x in v]
            import_rules.schema = parsed_schema2
        # 旧版兼容：允许直接在 import_rules 下声明矩阵
        allow_patterns2 = rules_data.get('allow_patterns') or rules_data.get('allowed_patterns')
        if isinstance(allow_patterns2, list):
            parsed2: list[tuple[str, str]] = []
            for item in allow_patterns2:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    src, dst = str(item[0]).strip(), str(item[1]).strip()
                    parsed2.append((src, dst))
            import_rules.allow_patterns = parsed2
        deny_patterns2 = rules_data.get('deny_patterns') or rules_data.get('denied_patterns')
        if isinstance(deny_patterns2, list):
            parsed2d: list[tuple[str, str]] = []
            for item in deny_patterns2:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    src, dst = str(item[0]).strip(), str(item[1]).strip()
                    parsed2d.append((src, dst))
            import_rules.deny_patterns = parsed2d
        if 'matrix_default' in rules_data:
            val2 = str(rules_data['matrix_default']).strip().lower()
            if val2 in {"deny", "allow"}:
                import_rules.matrix_default = val2
        
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
  # 聚合门面白名单（可选）：允许直连这些聚合门面
  aggregator_whitelist:
    - "myproject.api"
    
  # 规则开关
  rules:
    allow_cross_package: false    # 禁止跨包导入
    allow_upward_import: false    # 禁止子模块导入父模块
    allow_skip_levels: false      # 禁止跳级导入
    forbid_private_modules: true  # 禁止导入路径包含私有段（以_开头）
    require_via_aggregator: false # 若允许跨包导入，则要求目标为聚合门面（PACKAGE/__init__.py）
    allowed_external_depth: 0     # 仅允许顶层包作为门面（0）；>0 允许子包作为聚合门面
    
    # 命名集合（schema）：可在规则中使用 <global> 与 <public>
    schema:
      global: ["utils", "utils.**", "types", "types.**", "common", "common.**"]
      public: ["*.public", "*.public.**"]
    
    # 可选：基于矩阵的允许/禁止规则（source=导入方，target=被导入）
    # 语义：
    #   - pattern         精确匹配该模块
    #   - pattern.*       仅直接子模块
    #   - pattern.**      任意后代（不含自身）
    #   - <self>          导入方自身（用于 target 如 <self>.* 代表“导入方的直接子模块”）
    #   - <ancestor>      导入方的严格祖先包（存在于项目且为PACKAGE）
    #   - <global>/<public> 来自 schema 命名集合
    #   - 其他 * 或 ?     使用 fnmatch 语义
    # 示例：
    # allow_patterns:
    #   # 邻接层：api -> services, services -> selectors, selectors -> models
    #   - ["apps.*.api*", "apps.*.services*"]
    #   - ["apps.*.services*", "apps.*.selectors*"]
    #   - ["apps.*.selectors*", "apps.*.models*"]
    #   # 同域 Contracts（任意子模块 -> 本域 contracts）
    #   - ["*", "<ancestor>.schemas*"]
    #   - ["*", "<ancestor>.types*"]
    #   # 跨域仅允许 public 出口
    #   - ["apps.*.*", "apps.*.public.*"]
    #   # Global 直连（utils/types/common）
    #   - ["*", "utils*"]
    #   - ["*", "types*"]
    #   - ["*", "common*"]
    # deny_patterns:
    #   # 显式禁止跳层（例如 api 直达 models）
    #   - ["apps.*.api*", "apps.*.models*"]
    # matrix_default: deny  # 当存在 allow_patterns 但未匹配时：deny|allow
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
    print("🔒 导入规则（矩阵白名单）:")
    print("  🧩 matrix_default: deny")
    print("  🔗 allow_patterns: 0 条（未配置即全拒）")
    print("  ⛔ forbid_private_modules: 可开启")
    print()
    print("💡 提示:")
    print("  • 生成配置: 'codeclinic --init'")
    print("  • 查看配置: 'codeclinic --show-config'")
    print("  • 编辑配置: 修改 codeclinic.yaml")
