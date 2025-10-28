"""
配置初始化模块 - 生成和显示配置文件
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except ImportError:
    yaml = None

import importlib
import importlib.resources as ir

from .config_loader import ExtendedConfig, load_config


def _load_packaged_strict_yaml() -> str | None:
    """优先从打包资源读取配置模板（codeclinic.yaml）。若不可用返回 None。"""
    # Try importlib.resources (py>=3.9)
    try:
        pkg = "codeclinic"
        # New API
        try:
            base = ir.files(pkg) / "templates"
            pref = base / "codeclinic.yaml"
            if pref.exists():
                return pref.read_text(encoding="utf-8")
        except Exception:
            pass
        # Fallback to legacy API
        try:
            return ir.read_text(pkg + ".templates", "codeclinic.yaml", encoding="utf-8")
        except Exception:
            pass
    except Exception:
        pass
    return None


def init_config(output_path: Optional[Path] = None, force: bool = False) -> Path:
    """
    初始化配置文件

    Args:
        output_path: 输出路径，默认为当前目录下的 codeclinic.yaml
        force: 是否强制覆盖已存在的配置文件

    Returns:
        Path: 生成的配置文件路径
    """
    if output_path is None:
        output_path = Path("codeclinic.yaml")

    # 检查文件是否已存在
    if output_path.exists() and not force:
        print(f"⚠️  配置文件已存在: {output_path}")
        response = input("是否覆盖? (y/N): ").strip().lower()
        if response not in ["y", "yes"]:
            print("❌ 取消操作")
            return output_path

    # 仅支持复制严格配置（打包资源）；若未找到则报错退出
    strict_text = _load_packaged_strict_yaml()
    if not strict_text:
        print("❌ 未找到打包的基线模板: codeclinic/templates/codeclinic.yaml")
        print(
            "   请升级 CodeClinic 版本或联系维护者补充模板；当前行为仅支持复制该严格配置，不再生成示例模板。"
        )
        raise FileNotFoundError("codeclinic.yaml template resource missing")
    config_content = strict_text

    # 写入文件
    output_path.write_text(config_content, encoding="utf-8")

    print(f"✅ 配置文件已生成: {output_path}")
    print("\n📋 生成的配置内容:")
    print("━" * 50)
    print(config_content)
    print("━" * 50)

    print("\n💡 下一步操作:")
    print("1. 已复制严格基线配置（矩阵白名单）；按需补充 allow_patterns")
    print("2. 在 rules.allow_patterns 中列出允许的导入边（严格白名单）")
    print("3. 根据需要开启 forbid_private_modules")
    print(f"4. 运行 'codeclinic --path your_project' 进行分析")

    return output_path


def show_config() -> None:
    """显示当前生效的配置"""
    try:
        config = load_config()
        print("📋 当前生效配置:")
        print("━" * 60)

        # 基础设置
        print("🔧 基础设置:")
        print(f"  📂 扫描路径: {', '.join(config.paths)}")
        print(f"  📄 输出格式: {config.format}")
        print(f"  📁 输出目录: {config.output}")
        print(f"  🔢 聚合层级: {config.aggregate}")
        print(f"  👁️  计算私有函数: {'是' if config.count_private else '否'}")

        # 文件过滤
        print("\n📁 文件过滤:")
        print(f"  ✅ 包含: {', '.join(config.include)}")
        print(
            f"  ❌ 排除: {', '.join(config.exclude[:3])}{'...' if len(config.exclude) > 3 else ''}"
        )

        # 导入规则（仅矩阵白名单）
        print("\n🔒 导入规则:")
        rules = config.import_rules
        print(f"  🧩 matrix_default: {getattr(rules, 'matrix_default', 'deny')}")
        ap = getattr(rules, "allow_patterns", []) or []
        dp = getattr(rules, "deny_patterns", []) or []
        print(f"  🔗 allow_patterns: {len(ap)} 条  | deny_patterns: {len(dp)} 条")
        print(
            f"  ⛔ forbid_private_modules: {'开启' if getattr(rules, 'forbid_private_modules', False) else '关闭'}"
        )

        # schema 摘要（如有）
        schema = getattr(rules, "schema", {}) or {}
        if schema:
            print("  📚 命名集合(schema):")
            for k, v in list(schema.items())[:3]:
                print(f"    • {k}: {len(v)} 条模式")

        print("\n━" * 60)
        print("💡 提示:")
        print("  • 使用 'codeclinic --init' 生成新的配置文件")
        print("  • 配置文件优先级: codeclinic.yaml > pyproject.toml")

    except Exception as e:
        print(f"❌ 配置加载失败: {e}")


def create_example_yaml() -> str:
    """创建示例 YAML 配置文件内容"""
    return """# CodeClinic 配置文件（矩阵白名单版）
# 版本: v0.1.3b1
# 文档: https://github.com/Scienith/code-clinic

version: "1.0"

# ==== 基础设置 ====
# 要扫描的项目路径
paths:
  - "src"
  # - "."  # 当前目录
  # - "myproject"  # 指定项目目录

# 输出设置
output: "codeclinic_results"  # 输出目录
format: "svg"                 # 输出格式: svg, png, pdf, json, dot
aggregate: "module"           # 聚合级别: module, package
count_private: false          # 是否统计私有函数

# ==== 文件过滤 ====
include:
  - "**/*.py"

exclude:
  - "**/tests/**"
  - "**/.venv/**" 
  - "**/venv/**"
  - "**/__pycache__/**"
  - "**/build/**"
  - "**/dist/**"

# ==== 导入规则配置（仅使用矩阵白名单）====
import_rules:
  rules:
    matrix_default: deny
    forbid_private_modules: true
    # 仅允许以下导入边；未命中一律违规
    allow_patterns:
      # 示例：同域邻接层（api -> services -> selectors -> models）
      - ["<ancestor>.api", "<ancestor>.services"]
      - ["<ancestor>.services", "<ancestor>.selectors"]
      - ["<ancestor>.selectors", "<ancestor>.models"]
      # 示例：同域 contracts（只开放根，不开放子模块）
      - ["*", "<ancestor>.schemas"]
      - ["*", "<ancestor>.types"]
      # 示例：跨域仅 public（按需列出具体域；或用通配）
      # - ["apps.users.**", "apps.users.public"]
      # - ["apps.users.**", "apps.users.public.**"]

# ==== 提示信息 ====
# 1. 修改 white_list 添加项目的公共模块
# 2. 根据项目架构调整 rules 设置
# 3. 运行 'codeclinic --show-config' 查看当前配置
# 4. 运行 'codeclinic --path your_project' 开始分析
"""


def format_config_display(config: ExtendedConfig) -> str:
    """格式化配置显示"""
    lines = []

    lines.append("📋 当前配置:")
    lines.append("━" * 50)

    # 基础配置
    lines.append("🔧 基础设置:")
    lines.append(f"  📂 扫描路径: {', '.join(config.paths)}")
    lines.append(f"  📄 输出格式: {config.format}")
    lines.append(f"  📁 输出目录: {config.output}")

    # 导入规则（矩阵白名单概要）
    lines.append("\n🔒 导入规则:")
    rules = config.import_rules
    ap = getattr(rules, "allow_patterns", []) or []
    dp = getattr(rules, "deny_patterns", []) or []
    lines.append(f"  🧩 matrix_default: {getattr(rules, 'matrix_default', 'deny')}")
    lines.append(f"  🔗 allow_patterns: {len(ap)} | deny_patterns: {len(dp)}")
    lines.append(
        f"  ⛔ forbid_private_modules: {'开启' if getattr(rules, 'forbid_private_modules', False) else '关闭'}"
    )

    return "\n".join(lines)


def show_default_config_hint() -> None:
    """显示默认配置提示"""
    print("📋 使用默认配置:")
    print("━" * 40)
    print("🔒 导入规则（矩阵白名单）:")
    print("  🧩 matrix_default: deny")
    print("  🔗 allow_patterns: 0 条（未配置即全拒）")
    print("  ⛔ forbid_private_modules: 可开启")
    print()
    print("💡 提示: 运行 'codeclinic --init' 生成自定义配置文件")
    print("💡 查看配置: 运行 'codeclinic --show-config'")
