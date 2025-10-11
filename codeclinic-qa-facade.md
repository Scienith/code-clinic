# CodeClinic QA Facade 需求说明（统一质量门禁入口）

本说明书定义将 CodeClinic 扩展为“统一对外 Facade”的需求：用单一命令统一执行格式化、Lint、类型检查、测试/覆盖率、复杂度/规模、依赖与 Stub 成熟度检查，并以一致的产物和门禁结果输出。

## 目标与原则
- 单一入口：开发者与 CI 仅调用 `codeclinic`，无需直接接触 black/ruff/mypy/pytest/radon 等底层工具。
- 每类问题只选一个 Provider：坚持“可靠单选”，避免工具叠加（除非功能缺口）。
- 完全向后兼容：现有 `codeclinic --path/--out/--format`、`deps`、`stubs` 等命令与产物不变；新增 QA 子命名空间按需启用。
- 严格区分 check 与 fix：`qa run` 仅检查；`qa fix` 仅做可自动修复的步骤。

## Provider 选型（统一接入）
- 格式化：black（模式：check 或 fix）
- Lint：ruff（模式：check；可选导入顺序 I 规则；不引入 isort）
- 类型检查：mypy（默认严格或团队设定）
- 测试与覆盖率：pytest + coverage.py（覆盖率阈值纳入 gates）
- 复杂度/规模：radon（圈复杂度/MI/LOC；至少提供单文件 LOC 门禁）
- 依赖规则与可视化：CodeClinic 内建（AST 导入图、跨包/向上/跳级 + 白名单）
- Stub 成熟度：CodeClinic 内建（识别以 stub 结尾的装饰器；提供 `codeclinic.stub`）
- 安全扫描：本期不纳入

## 新增 CLI（QA 子命名空间）
- `codeclinic qa init`
  - 生成 `codeclinic.yaml`（或 `pyproject.tool.codeclinic`），可选生成 pre-commit、GitHub Actions、Makefile。
- `codeclinic qa run`（仅检查，不修复）
  - 顺序执行 Provider：black --check → ruff check → mypy → pytest（覆盖率）→ radon（规模/复杂度）→ 内建 deps 与 stubs。
  - 产出统一 `summary.json` 与标准化日志，按 gates 统一退出码（0=通过，>0=失败）。
- `codeclinic qa fix`（仅修复，可自动修复项）
  - 执行 black（格式化）、ruff --fix（导入顺序/可自动修复规则）；不跑 mypy/pytest/radon。
- 现有命令保持：`codeclinic --path ...`、`codeclinic deps`、`codeclinic stubs`、`--legacy`。

## 统一配置（codeclinic.yaml 示例）
```yaml
tool:
  paths: ["src"]
  include: ["**/*.py"]
  exclude: ["**/.venv/**", "**/migrations/**", "**/tests/**"]
  output: "build/codeclinic"

tools:
  formatter:
    provider: black
    line_length: 88
  linter:
    provider: ruff
    ruleset: ["E","F","I","B"]
    line_length: 88
    unsafe_fixes: false
  typecheck:
    provider: mypy
    strict: true
    config_file: "mypy.ini"   # 可选
  tests:
    provider: pytest
    args: ["-q"]
    coverage:
      min: 80
      report: "xml"
  complexity:
    provider: radon
    max_file_loc: 500          # 单文件 LOC 门禁
    cc_threshold: "B"          # 可选（圈复杂度）
  deps:
    provider: internal
    import_rules:
      allow_cross_package: false
      allow_upward_import: false
      allow_skip_levels: false
      white_list: []
  stubs:
    provider: internal
    decorator_names: ["stub"]

gates:
  formatter_clean: true         # black --check 必须通过
  linter_errors_max: 0          # ruff 无错误
  mypy_errors_max: 0            # mypy 无错误
  coverage_min: 80              # 覆盖率阈值
  max_file_loc: 500             # 文件规模上限
  import_violations_max: 0      # 导入违规阈值
  stub_ratio_max: 0.25          # 公共函数维度的 stub 占比上限
```

## mypy 严格默认集（建议）
- disallow_untyped_defs, disallow_incomplete_defs
- disallow_untyped_calls, disallow_untyped_decorated_calls
- disallow_any_generics, no_implicit_optional
- warn_return_any, warn_unused_ignores, warn_redundant_casts, warn_no_return, warn_unreachable
- strict_equality；启用 error codes：`truthy-iterable`, `redundant-cast`, `override`, `call-arg`, `assignment`, `return-value`, `attr-defined`
- 团队可在 `mypy.ini` 局部降级（按模块/路径）

## 执行与产物
- 输出目录：`build/codeclinic/`
  - `summary.json`（统一汇总：总体状态、失败 gates、关键指标、构件路径）
  - `logs/<provider>.log`（标准化日志）
  - `artifacts/`（沿用/兼容现有结构）
    - `dependency_graph.(dot|svg)`、`import_violations/violations.json`
    - `stub_completeness/stub_summary.json`
    - `coverage.xml`
    - `complexity.json`（radon 汇总）
- 退出码：0=全部 gates 通过；>0=失败（`summary.json` 列出触发 gates）

## 兼容性与依赖
- 完全向后兼容：不改变现有命令与默认输出；QA 子系统仅在显式调用时生效。
- Provider 依赖按需：未启用的 Provider 不要求安装；缺失时给出清晰提示，但不影响非 QA 命令。

## 实现建议（开发者视角）
- Runner：解析配置→执行 Providers→标准化结果→评估 gates→生成 `summary.json` 与退出码。
- Provider 接口：`run(config) -> {status, metrics, artifacts}`；内置 deps/stubs 复用现有实现；black/ruff/mypy/pytest/radon 可通过模块入口或子进程调用。
- 聚合策略：deps/stubs 内部在需要时自动以 module 与 package 两种聚合跑两次，保证产出逐函数 stub 与包级概要。

## 阶段性计划
- Phase 1：新增 `qa init/run/fix`、接入 black/ruff/mypy/pytest、内建 deps/stubs、产出 `summary.json`。
- Phase 2：接入 radon Provider（LOC/CC/MI 汇总）、HTML 报告、profiles（pre-commit 与 CI 预设）。
- Phase 3：插件接口扩展（如安全扫描等，按需再议）。

---
（备注）本需求说明用于提交给 CodeClinic 开发者，作为将 CodeClinic 升级为“一站式质量门禁 Facade”的功能规范参考。
