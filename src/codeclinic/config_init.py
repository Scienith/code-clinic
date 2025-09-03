"""
配置初始化模块 - 生成和显示配置文件
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import asdict

try:
    import yaml
except ImportError:
    yaml = None

from .config_loader import ExtendedConfig, load_config


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
        if response not in ['y', 'yes']:
            print("❌ 取消操作")
            return output_path
    
    # 生成配置文件内容
    config_content = create_example_yaml()
    
    # 写入文件
    output_path.write_text(config_content, encoding='utf-8')
    
    print(f"✅ 配置文件已生成: {output_path}")
    print("\n📋 生成的配置内容:")
    print("━" * 50)
    print(config_content)
    print("━" * 50)
    
    print("\n💡 下一步操作:")
    print("1. 编辑配置文件以满足您的需求")
    print("2. 将白名单模块添加到 white_list 中")
    print("3. 根据需要调整规则开关")
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
        print(f"  ❌ 排除: {', '.join(config.exclude[:3])}{'...' if len(config.exclude) > 3 else ''}")
        
        # 导入规则
        print("\n🔒 导入规则:")
        rules = config.import_rules
        
        cross_icon = "✅" if rules.allow_cross_package else "❌"
        upward_icon = "✅" if rules.allow_upward_import else "❌"
        skip_icon = "✅" if rules.allow_skip_levels else "❌"
        
        print(f"  {cross_icon} 跨包导入: {'允许' if rules.allow_cross_package else '禁止'}")
        print(f"  {upward_icon} 向上导入: {'允许' if rules.allow_upward_import else '禁止'}")
        print(f"  {skip_icon} 跳级导入: {'允许' if rules.allow_skip_levels else '禁止'}")
        
        if rules.white_list:
            print(f"  📝 白名单模块 ({len(rules.white_list)} 个):")
            for module in rules.white_list[:5]:  # 只显示前5个
                print(f"    • {module}")
            if len(rules.white_list) > 5:
                print(f"    ... 还有 {len(rules.white_list) - 5} 个")
        else:
            print("  📝 白名单: 无")
        
        print("\n━" * 60)
        print("💡 提示:")
        print("  • 使用 'codeclinic --init' 生成新的配置文件")
        print("  • 配置文件优先级: codeclinic.yaml > pyproject.toml")
        
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")


def create_example_yaml() -> str:
    """创建示例 YAML 配置文件内容"""
    return '''# CodeClinic 配置文件
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

# ==== 导入规则配置 ====
import_rules:
  # 白名单：这些模块可以被任何地方导入，不受规则限制
  white_list:
    # 常见的白名单模块示例（请根据项目修改）:
    # - "myproject.utils"        # 工具函数模块
    # - "myproject.constants"    # 常量定义模块  
    # - "myproject.types"        # 类型定义模块
    # - "myproject.exceptions"   # 异常定义模块
    # - "myproject.config"       # 配置模块
    
  # 规则开关
  rules:
    # 是否允许跨包导入
    # false: A包不能导入B包的模块（除了白名单）
    allow_cross_package: false
    
    # 是否允许向上导入  
    # false: 子模块不能导入父模块（防止循环依赖）
    allow_upward_import: false
    
    # 是否允许跳级导入
    # false: 必须通过中间层级导入，如 A.B.C 不能直接导入 A.B.C.D.E
    allow_skip_levels: false

# ==== 提示信息 ====
# 1. 修改 white_list 添加项目的公共模块
# 2. 根据项目架构调整 rules 设置
# 3. 运行 'codeclinic --show-config' 查看当前配置
# 4. 运行 'codeclinic --path your_project' 开始分析
'''


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
    
    # 导入规则
    lines.append("\n🔒 导入规则:")
    rules = config.import_rules
    
    cross_status = "允许" if rules.allow_cross_package else "禁止"
    upward_status = "允许" if rules.allow_upward_import else "禁止"
    skip_status = "允许" if rules.allow_skip_levels else "禁止"
    
    lines.append(f"  {'✅' if rules.allow_cross_package else '❌'} 跨包导入: {cross_status}")
    lines.append(f"  {'✅' if rules.allow_upward_import else '❌'} 向上导入: {upward_status}")
    lines.append(f"  {'✅' if rules.allow_skip_levels else '❌'} 跳级导入: {skip_status}")
    
    if rules.white_list:
        lines.append(f"  📝 白名单 ({len(rules.white_list)} 个): {', '.join(rules.white_list[:3])}")
        if len(rules.white_list) > 3:
            lines.append("      ...")
    else:
        lines.append("  📝 白名单: 无")
    
    return "\n".join(lines)


def show_default_config_hint() -> None:
    """显示默认配置提示"""
    print("📋 使用默认配置:")
    print("━" * 40)
    print("🔒 导入规则:")
    print("  ❌ 跨包导入 (禁止)")
    print("  ❌ 向上导入 (禁止)")
    print("  ❌ 跳级导入 (禁止)")
    print("  📝 白名单: 无")
    print()
    print("💡 提示: 运行 'codeclinic --init' 生成自定义配置文件")
    print("💡 查看配置: 运行 'codeclinic --show-config'")