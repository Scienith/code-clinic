# 实施闭环（implementationLoop）可程序化检测项梳理

来源：`/Users/junjiecai/Desktop/projects/scientith_projects/supervisor/scienith_supervisor/src/apps/core/template_sops/sop3/Implementing/implementationLoop/config.json`

本文将规则按“可自动检测 / 部分可自动检测 / 需人工评审”为主线梳理，并给出在 CodeClinic 中的落位建议（gates 与报表）。

## 一、可自动检测

- 禁止 Fallback 机制（Fail‑Fast）
  - 检查点：`dict.get(key, default)`、`getattr(obj, 'x', default)`、`os.getenv('X', default)`/`os.environ.get`、`try/except ImportError` 后备分支（含空实现/替代导入）。
  - 输出：列出命中位置，计入门禁。
  - 建议 gates：`fallbacks_forbidden: true`。

  需要。我希望默认禁止dict.get, getattr的使用。但是如果使用的行默认有 # allow fallback的标注，则允许。是否可行

- Stub 文档契约（Docstring）
  - 检查点：函数/方法 docstring 必含“功能概述、前置条件、后置条件、不变量、副作用”。
  - 输出：缺失/不完整清单（`doc_contracts.json`）。
  - 建议 gates：`docs.contracts_missing_max: 0`（可配 `docs.required_sections`、`docs.case_sensitive`）。

  支持，默认配置 功能概述、前置条件、后置条件、不变量、副作用

- 包内环路（SCC）
  - 检查点：构建 import 图，检测强连通分量（循环依赖）。
  - 输出：`artifacts/import_violations/violations_graph.{dot,svg}`。
  - 建议 gates：`imports.cycles_max: 0`。

需要支持

- 包内测试布局（按 module 命名）
  - 检查点：对每个模块存在 `tests/test_<module>.py`；跳过 `__init__.py`；允许排除名单。
  - 输出：缺失对应测试的模块列表。
  - 建议 gates：`modules_require_named_tests: true` + `modules_named_tests_exclude: ["**/exceptions.py", "**/constants.py", "**/schema.py", "**/types.py"]`。

  目前不支持吗？再检查一下

- 私有成员与内部接口约定（_ 前缀）
  - 检查点：禁止跨模块 `from x import _private`；禁止在 `__all__` 导出以下划线开头符号。
  - 输出：违规清单。
  - 建议 gates：`imports.forbid_private_modules: true` + `exports_no_private: true`。

  这个目前不支持吗？再检查下

- Public 出口与副作用约束
  - 检查点：`pkg/__init__.py`、`pkg/public/__init__.py` 仅允许 re-export；禁止顶层副作用（如 `open/subprocess/requests/pathlib.Path(...).write_text()`、环境写、网络/文件 IO 等）。
  - 输出：命中的顶层调用/上下文列表。
  - 建议 gates：`packages.public_no_side_effects: true`。

  __init__.py只允许re-import，以及 __all__ = 的定义，不能有其他代码

- 安装/执行完整性（存在性检查）
  - 检查点：`codeclinic.yaml`、脚本入口（如 `scripts/codeclinic.sh`）、关键产物（`summary.json`、`artifacts/junit.xml`）。
 - 输出：缺失项报告（建议作为健康检查，不参与门禁分数）。

 不考虑

## 二、部分可自动检测（启发式/依赖上下文）

- utils/common 行为边界
  - 检查点：`utils/**` 限制为纯函数（禁止 IO/框架客户端/进程级副作用）；`common/**` 不反向依赖业务实现。
  - 实现：基于“目录前缀 + 禁止导入与调用清单”启发式静态扫描。
  - 输出：告警清单（建议默认非硬门禁，可按项目收紧）。
不考虑

- 包路径规范（单层）
  - 检查点：`types.py` 与 `schemas.py` 建议配对、公共 API 聚合至包根出口、关键子域具名测试等。
  - 输出：偏差清单（建议不默认作为硬门禁）。
- 不考虑

- Stub 装饰器与占位返回（红灯阶段）
  - 检查点：`@stub` 装饰器、占位返回（常量占位或 `raise NotImplementedError`）。
  - 输出：统计与清单（是否作为门禁视流程需要）。
不考虑

- Stub 阶段测试约束（pytest）
  - 检查点：基于 JUnit 将失败类型区分为 FAIL（断言）与 ERROR（异常）；红灯阶段应以 FAIL 驱动。
  - 备注：需要流程态标识辅助，建议仅报表提示。
  不考虑

- 目标 Stub 选择/处理策略
  - 检查点：读取 `stub_summary.json`，提示 `graph_depth` 最深优先；策略属流程辅助，非硬门禁。
