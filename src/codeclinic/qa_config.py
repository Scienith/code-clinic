from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


@dataclass
class ToolSection:
    paths: List[str] = field(default_factory=lambda: ["src"])  # project roots to scan
    include: List[str] = field(default_factory=lambda: ["**/*.py"])
    exclude: List[str] = field(
        default_factory=lambda: [
            "**/.venv/**",
            "**/venv/**",
            "**/__pycache__/**",
            "**/build/**",
            "**/dist/**",
        ]
    )
    output: str = "build/codeclinic"


@dataclass
class FormatterCfg:
    provider: str = "black"
    line_length: int = 88


@dataclass
class LinterCfg:
    provider: str = "ruff"
    ruleset: List[str] = field(
        default_factory=lambda: ["E", "F", "I", "B", "D"]
    )  # include I for import order
    line_length: int = 88
    unsafe_fixes: bool = False
    # Optional: docstring style convention for pydocstyle (e.g., "google", "numpy", "pep257")
    docstyle_convention: Optional[str] = None
    # Optional: Ruff ignore list (e.g., ["D415", "D205"]) from YAML
    ignore: List[str] = field(default_factory=list)


@dataclass
class TypecheckCfg:
    provider: str = "mypy"
    strict: bool = True
    config_file: Optional[str] = None
    # Patterns of modules/packages for which mypy should ignore missing imports
    # e.g., ["numpy", "pandas", "sklearn.*", "some_lib.*"]
    ignore_missing_imports: List[str] = field(default_factory=list)


@dataclass
class CoverageCfg:
    min: int = 80
    report: str = "xml"


@dataclass
class JUnitCfg:
    enabled: bool = True
    output: str = "build/codeclinic/artifacts/junit.xml"


@dataclass
class TestsCfg:
    provider: str = "pytest"
    args: List[str] = field(default_factory=lambda: ["-q"])
    coverage: CoverageCfg = field(default_factory=CoverageCfg)
    junit: JUnitCfg = field(default_factory=JUnitCfg)


@dataclass
class ComplexityCfg:
    provider: str = "radon"  # phase 2; kept for forward compat
    max_file_loc: int = 500
    cc_threshold: Optional[str] = None


@dataclass
class ImportRules:
    allow_cross_package: bool = False
    allow_upward_import: bool = False
    allow_skip_levels: bool = False
    white_list: List[str] = field(default_factory=list)
    # 扩展：矩阵规则（与主CLI保持一致的字段名）
    allow_patterns: List[tuple[str, str]] = field(default_factory=list)
    deny_patterns: List[tuple[str, str]] = field(default_factory=list)
    matrix_default: str = "deny"
    # 可选：聚合门面规则（与主CLI保持一致）
    forbid_private_modules: bool = False
    require_via_aggregator: bool = False
    allowed_external_depth: int = 0
    aggregator_whitelist: List[str] = field(default_factory=list)
    # 命名集合（schema）：如 global/public
    schema: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class DepsCfg:
    provider: str = "internal"
    import_rules: ImportRules = field(default_factory=ImportRules)


@dataclass
class StubsCfg:
    provider: str = "internal"
    decorator_names: List[str] = field(
        default_factory=lambda: ["stub"]
    )  # reserved for future


@dataclass
class ToolsSection:
    formatter: FormatterCfg = field(default_factory=FormatterCfg)
    linter: LinterCfg = field(default_factory=LinterCfg)
    typecheck: TypecheckCfg = field(default_factory=TypecheckCfg)
    tests: TestsCfg = field(default_factory=TestsCfg)
    complexity: ComplexityCfg = field(default_factory=ComplexityCfg)
    deps: DepsCfg = field(default_factory=DepsCfg)
    stubs: StubsCfg = field(default_factory=StubsCfg)


@dataclass
class VisualsCfg:
    # 是否在 Stub 热力图中用边框标识模块测试状态（绿/红）
    show_test_status_borders: bool = True


@dataclass
class GatesSection:
    formatter_clean: bool = True
    linter_errors_max: int = 0
    mypy_errors_max: int = 0
    coverage_min: int = 80
    max_file_loc: int = 500
    import_violations_max: int = 0
    # 新增：禁止符号级私有导入（from x import _private）
    imports_forbid_private_symbols: bool = True
    # Fail-Fast 禁止（默认开启），以及行内豁免标签
    failfast_forbid_dict_get_default: bool = True
    failfast_forbid_getattr_default: bool = True
    failfast_forbid_env_default: bool = True
    failfast_forbid_import_fallback: bool = True
    # New: forbid try/except fallback for missing attributes or keys
    failfast_forbid_attr_fallback: bool = True
    failfast_forbid_key_fallback: bool = True
    # Aggressive bans (any usage, not just with default)
    failfast_forbid_dict_get_any: bool = False
    failfast_forbid_getattr_any: bool = False
    # New: forbid hasattr (treat as fallback probing) — default on
    failfast_forbid_hasattr: bool = True
    failfast_allow_comment_tags: List[str] = field(
        default_factory=lambda: ["allow fallback", "codeclinic: allow-fallback"]
    )
    # 导入环路（SCC）最大允许数量（0 表示不允许出现）
    imports_cycles_max: int = 0
    # Public 出口无副作用
    packages_public_no_side_effects: bool = True
    packages_public_side_effect_forbidden_calls: List[str] = field(
        default_factory=lambda: [
            "open",
            "subprocess.*",
            "os.system",
            "pathlib.Path.write_text",
            "pathlib.Path.write_bytes",
            "requests.*",
        ]
    )
    # 非 ABC 方法禁止 NotImplemented/pass 占位
    stubs_no_notimplemented_non_abc: bool = True
    # 红灯失败类型（错误应以断言失败为主，避免 error）
    tests_red_failures_are_assertions: bool = True
    stub_ratio_max: float = 0.25
    # 可选扩展门禁：圈复杂度等级与可维护性指数
    # 大写字母等级，A最佳、F最差。若为空或未设置，则不启用该门禁
    cc_max_rank_max: str | None = None
    # 最低可维护性指数（0–100）。若为0或未设置，则不启用该门禁
    mi_min: int | None = None
    # 新增：组件依赖无stub时，同层级tests必须全绿
    components_dep_stub_free_requires_green: bool = True
    # 新增：是否允许组件缺少同层级tests
    allow_missing_component_tests: bool = False
    # 新增：要求所有包目录存在 __init__.py
    packages_require_dunder_init: bool = True
    # 新增：按 glob 模式排除不要求存在 __init__.py 的目录（允许非包目录）
    packages_missing_init_exclude: List[str] = field(default_factory=list)
    # 新增：每个包内模块是否必须有命名规范 tests/test_<module>.py（仅对包内 .py 文件生效）
    modules_require_named_tests: bool = True
    # 新增：要求包内 __init__.py 必须定义非空 __all__
    exports_require_nonempty_all: bool = False
    # 新增：按 glob 模式排除不检查非空 __all__ 的包 __init__.py 路径
    exports_nonempty_all_exclude: List[str] = field(default_factory=list)
    # 新增：按 glob 模式排除不检查命名测试的模块列表（相对/绝对路径均可，使用 fnmatch）
    modules_named_tests_exclude: List[str] = field(default_factory=list)
    doc_contracts_missing_max: int = 0
    # 文档契约检测：要求 docstring 中包含的关键段落关键词
    doc_required_sections: List[str] = field(
        default_factory=lambda: ["功能概述", "前置条件", "后置条件", "不变量", "副作用"]
    )
    # 是否区分大小写
    doc_case_sensitive: bool = False
    fn_loc_max: int = 50
    fn_args_max: int = 5
    fn_nesting_max: int = 3
    # 是否将 Docstring 行计入函数行数统计
    fn_count_docstrings: bool = True
    exports_no_private: bool = True
    # Runtime validation (pydantic.validate_call)
    runtime_validation_require_validate_call: bool = False
    runtime_validation_require_innermost: bool = False
    runtime_validation_exclude: List[str] = field(default_factory=list)
    runtime_validation_skip_private: bool = True
    runtime_validation_skip_magic: bool = True
    runtime_validation_skip_properties: bool = True
    runtime_validation_allow_comment_tags: List[str] = field(
        default_factory=lambda: ["codeclinic: allow-no-validate-call"]
    )
    # Classes: enforce super().__init__ in subclass __init__
    classes_require_super_init: bool = False
    classes_super_init_exclude: List[str] = field(default_factory=list)
    classes_super_init_allow_comment_tags: List[str] = field(
        default_factory=lambda: ["codeclinic: allow-no-super-init"]
    )


@dataclass
class ComponentsCfg:
    scope: str = "package"  # package | module
    tests_dir_name: str = "tests"  # same-level tests dir under component
    dependency_scope: str = "transitive"  # direct | transitive
    require_self_stub_free: bool = True


@dataclass
class QAConfig:
    tool: ToolSection = field(default_factory=ToolSection)
    tools: ToolsSection = field(default_factory=ToolsSection)
    gates: GatesSection = field(default_factory=GatesSection)
    components: ComponentsCfg = field(default_factory=ComponentsCfg)
    visuals: VisualsCfg = field(default_factory=VisualsCfg)


def default_yaml() -> str:
    # Provide a human-friendly YAML matching the spec
    return """tool:
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
    ruleset: ["E","F","I","B","D"]
    line_length: 88
    unsafe_fixes: false
    # docstyle_convention: "google"   # 可选：启用 Ruff pydocstyle 的风格约定（google/numpy/pep257）
  typecheck:
    provider: mypy
    strict: true
    # config_file: "mypy.ini"   # optional
  tests:
    provider: pytest
    args: ["-q"]
    coverage:
      min: 80
      report: "xml"
    junit:
      enabled: true
      output: "build/codeclinic/artifacts/junit.xml"
  complexity:
    provider: radon
    max_file_loc: 500
    # cc_threshold: "B"
  deps:
    provider: internal
    import_rules:
      matrix_default: deny
      forbid_private_modules: true
      allow_patterns: []
gates:
  # 符号级私有导入禁止（from x import _private）
  imports_forbid_private_symbols: true
  # Fail-Fast 禁止与行内豁免
  failfast_forbid_dict_get_default: true
  failfast_forbid_getattr_default: true
  failfast_forbid_env_default: true
  failfast_forbid_import_fallback: true
  failfast_allow_comment_tags: ["allow fallback", "codeclinic: allow-fallback"]
  # 导入环路不允许出现
  imports_cycles_max: 0
  # Public 出口无副作用
  packages_public_no_side_effects: true
  packages_public_side_effect_forbidden_calls: ["open", "subprocess.*", "os.system", "pathlib.Path.write_text", "pathlib.Path.write_bytes", "requests.*"]
  # 非ABC方法禁止 NotImplementedError/pass
  stubs_no_notimplemented_non_abc: true
  # 红灯阶段失败类型约束（尽量以断言失败为主）
  tests_red_failures_are_assertions: true
gates:
  # 符号级私有导入禁止（from x import _private）
  imports_forbid_private_symbols: true
  stubs:
    provider: internal
    decorator_names: ["stub"]
visuals:
  # 是否在 Stub 热力图中用边框标识模块测试状态（绿/红）
  show_test_status_borders: true

gates:
  formatter_clean: true
  linter_errors_max: 0
  mypy_errors_max: 0
  coverage_min: 80
  max_file_loc: 500
  import_violations_max: 0
  # cc_max_rank_max: "C"   # 可选：不允许出现比该等级更差的圈复杂度（A最好、F最差）
  # mi_min: 70             # 可选：不允许文件MI低于该值（0-100）
  components_dep_stub_free_requires_green: true
  allow_missing_component_tests: false
  packages_require_dunder_init: true
  modules_require_named_tests: true
  # __init__.py 必须定义非空 __all__（可配合 excludes）
  exports_require_nonempty_all: false
  exports_nonempty_all_exclude: []
  # 可选：对某些模块跳过“命名测试文件存在性”检查（glob 模式列表）
  modules_named_tests_exclude: []

components:
  scope: package                # package | module
  tests_dir_name: tests         # same-level tests dir under component
  dependency_scope: transitive  # direct | transitive
  require_self_stub_free: false
"""


def load_qa_config(path: str | Path) -> QAConfig:
    cfg = QAConfig()
    p = Path(path)
    if not p.exists():
        return cfg
    if yaml is None:
        raise ImportError("需要安装PyYAML读取QA配置: pip install pyyaml")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    # Shallow merge with defaults
    tool = data.get("tool") or {}
    cfg.tool.paths = tool.get("paths", cfg.tool.paths)
    cfg.tool.include = tool.get("include", cfg.tool.include)
    cfg.tool.exclude = tool.get("exclude", cfg.tool.exclude)
    cfg.tool.output = tool.get("output", cfg.tool.output)

    tools = data.get("tools") or {}
    fmt = tools.get("formatter") or {}
    cfg.tools.formatter.provider = fmt.get("provider", cfg.tools.formatter.provider)
    cfg.tools.formatter.line_length = int(
        fmt.get("line_length", cfg.tools.formatter.line_length)
    )

    lin = tools.get("linter") or {}
    cfg.tools.linter.provider = lin.get("provider", cfg.tools.linter.provider)
    cfg.tools.linter.ruleset = list(lin.get("ruleset", cfg.tools.linter.ruleset))
    cfg.tools.linter.line_length = int(
        lin.get("line_length", cfg.tools.linter.line_length)
    )
    cfg.tools.linter.unsafe_fixes = bool(
        lin.get("unsafe_fixes", cfg.tools.linter.unsafe_fixes)
    )
    cfg.tools.linter.docstyle_convention = lin.get(
        "docstyle_convention", cfg.tools.linter.docstyle_convention
    )
    ig = lin.get("ignore") if isinstance(lin, dict) else None
    if isinstance(ig, list):
        cfg.tools.linter.ignore = [str(x) for x in ig]

    tc = tools.get("typecheck") or {}
    cfg.tools.typecheck.provider = tc.get("provider", cfg.tools.typecheck.provider)
    cfg.tools.typecheck.strict = bool(tc.get("strict", cfg.tools.typecheck.strict))
    cfg.tools.typecheck.config_file = tc.get(
        "config_file", cfg.tools.typecheck.config_file
    )
    ign = tc.get("ignore_missing_imports") if isinstance(tc, dict) else None
    if isinstance(ign, list):
        cfg.tools.typecheck.ignore_missing_imports = [str(x) for x in ign]

    tst = tools.get("tests") or {}
    cfg.tools.tests.provider = tst.get("provider", cfg.tools.tests.provider)
    cfg.tools.tests.args = list(tst.get("args", cfg.tools.tests.args))
    cov = tst.get("coverage") or {}
    cfg.tools.tests.coverage.min = int(cov.get("min", cfg.tools.tests.coverage.min))
    cfg.tools.tests.coverage.report = cov.get("report", cfg.tools.tests.coverage.report)
    junit = tst.get("junit") or {}
    cfg.tools.tests.junit.enabled = bool(
        junit.get("enabled", cfg.tools.tests.junit.enabled)
    )
    cfg.tools.tests.junit.output = junit.get("output", cfg.tools.tests.junit.output)

    # visuals
    visuals = data.get("visuals") or {}
    if isinstance(visuals, dict):
        cfg.visuals.show_test_status_borders = bool(
            visuals.get(
                "show_test_status_borders", cfg.visuals.show_test_status_borders
            )
        )

    cpx = tools.get("complexity") or {}
    cfg.tools.complexity.provider = cpx.get("provider", cfg.tools.complexity.provider)
    cfg.tools.complexity.max_file_loc = int(
        cpx.get("max_file_loc", cfg.tools.complexity.max_file_loc)
    )
    cfg.tools.complexity.cc_threshold = cpx.get(
        "cc_threshold", cfg.tools.complexity.cc_threshold
    )

    deps = tools.get("deps") or {}
    cfg.tools.deps.provider = deps.get("provider", cfg.tools.deps.provider)
    ir = deps.get("import_rules") or {}
    cfg.tools.deps.import_rules.allow_cross_package = bool(
        ir.get("allow_cross_package", cfg.tools.deps.import_rules.allow_cross_package)
    )
    cfg.tools.deps.import_rules.allow_upward_import = bool(
        ir.get("allow_upward_import", cfg.tools.deps.import_rules.allow_upward_import)
    )
    cfg.tools.deps.import_rules.allow_skip_levels = bool(
        ir.get("allow_skip_levels", cfg.tools.deps.import_rules.allow_skip_levels)
    )
    cfg.tools.deps.import_rules.white_list = list(
        ir.get("white_list", cfg.tools.deps.import_rules.white_list)
    )

    # 矩阵规则（允许/禁止）
    def _parse_pairs(val: Any) -> List[tuple[str, str]]:
        out: List[tuple[str, str]] = []
        if isinstance(val, list):
            for item in val:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    s, t = str(item[0]).strip(), str(item[1]).strip()
                    out.append((s, t))
        return out

    ap = ir.get("allow_patterns") or ir.get("allowed_patterns")
    dp = ir.get("deny_patterns") or ir.get("denied_patterns")
    cfg.tools.deps.import_rules.allow_patterns = _parse_pairs(ap)
    cfg.tools.deps.import_rules.deny_patterns = _parse_pairs(dp)
    md = ir.get("matrix_default")
    if isinstance(md, str) and md.strip().lower() in {"deny", "allow"}:
        cfg.tools.deps.import_rules.matrix_default = md.strip().lower()
    # 聚合门面与私有路径段
    cfg.tools.deps.import_rules.forbid_private_modules = bool(
        ir.get(
            "forbid_private_modules", cfg.tools.deps.import_rules.forbid_private_modules
        )
    )
    cfg.tools.deps.import_rules.require_via_aggregator = bool(
        ir.get(
            "require_via_aggregator", cfg.tools.deps.import_rules.require_via_aggregator
        )
    )
    try:
        aed = ir.get(
            "allowed_external_depth", cfg.tools.deps.import_rules.allowed_external_depth
        )
        cfg.tools.deps.import_rules.allowed_external_depth = int(aed)
    except Exception:
        pass
    cfg.tools.deps.import_rules.aggregator_whitelist = list(
        ir.get("aggregator_whitelist", cfg.tools.deps.import_rules.aggregator_whitelist)
    )
    # schema 命名集合
    schema = ir.get("schema") or {}
    if isinstance(schema, dict):
        parsed: Dict[str, List[str]] = {}
        for k, v in schema.items():
            if isinstance(v, list):
                parsed[str(k)] = [str(x) for x in v]
        cfg.tools.deps.import_rules.schema = parsed

    stubs = tools.get("stubs") or {}
    cfg.tools.stubs.provider = stubs.get("provider", cfg.tools.stubs.provider)
    cfg.tools.stubs.decorator_names = list(
        stubs.get("decorator_names", cfg.tools.stubs.decorator_names)
    )

    gates = data.get("gates") or {}
    cfg.gates.formatter_clean = bool(
        gates.get("formatter_clean", cfg.gates.formatter_clean)
    )
    cfg.gates.linter_errors_max = int(
        gates.get("linter_errors_max", cfg.gates.linter_errors_max)
    )
    cfg.gates.mypy_errors_max = int(
        gates.get("mypy_errors_max", cfg.gates.mypy_errors_max)
    )
    cfg.gates.coverage_min = int(gates.get("coverage_min", cfg.gates.coverage_min))
    cfg.gates.max_file_loc = int(gates.get("max_file_loc", cfg.gates.max_file_loc))
    cfg.gates.import_violations_max = int(
        gates.get("import_violations_max", cfg.gates.import_violations_max)
    )
    # 按要求：移除 stub 比例门禁的实际使用；保留字段以兼容旧配置
    try:
        _ = float(gates.get("stub_ratio_max", cfg.gates.stub_ratio_max))
    except Exception:
        pass
    # 可选CC/MI门禁
    cc_rank = gates.get("cc_max_rank_max", None)
    if isinstance(cc_rank, str) and cc_rank.strip():
        cfg.gates.cc_max_rank_max = cc_rank.strip().upper()
    mi_min = gates.get("mi_min", None)
    if mi_min is not None:
        try:
            cfg.gates.mi_min = int(mi_min)
        except Exception:
            cfg.gates.mi_min = None
    # 新增/扩展门禁
    cfg.gates.components_dep_stub_free_requires_green = bool(
        gates.get(
            "components_dep_stub_free_requires_green",
            cfg.gates.components_dep_stub_free_requires_green,
        )
    )
    cfg.gates.allow_missing_component_tests = bool(
        gates.get(
            "allow_missing_component_tests", cfg.gates.allow_missing_component_tests
        )
    )
    cfg.gates.packages_require_dunder_init = bool(
        gates.get(
            "packages_require_dunder_init", cfg.gates.packages_require_dunder_init
        )
    )
    cfg.gates.modules_require_named_tests = bool(
        gates.get("modules_require_named_tests", cfg.gates.modules_require_named_tests)
    )
    # __all__ 非空门禁
    cfg.gates.exports_require_nonempty_all = bool(
        gates.get(
            "exports_require_nonempty_all", cfg.gates.exports_require_nonempty_all
        )
    )
    ex_all = gates.get(
        "exports_nonempty_all_exclude", cfg.gates.exports_nonempty_all_exclude
    )
    if isinstance(ex_all, list):
        cfg.gates.exports_nonempty_all_exclude = [str(x) for x in ex_all]
    # 解析排除列表
    mte = gates.get(
        "modules_named_tests_exclude", cfg.gates.modules_named_tests_exclude
    )
    if isinstance(mte, list):
        cfg.gates.modules_named_tests_exclude = [str(x) for x in mte]
    # 函数度量：是否统计 Docstring 行数（默认 True）。
    fcd = gates.get("fn_count_docstrings", cfg.gates.fn_count_docstrings)
    cfg.gates.fn_count_docstrings = bool(fcd)

    # 组件配置
    comp = data.get("components") or {}
    cfg.components.scope = comp.get("scope", cfg.components.scope)
    cfg.components.tests_dir_name = comp.get(
        "tests_dir_name", cfg.components.tests_dir_name
    )
    cfg.components.dependency_scope = comp.get(
        "dependency_scope", cfg.components.dependency_scope
    )
    cfg.components.require_self_stub_free = bool(
        comp.get("require_self_stub_free", cfg.components.require_self_stub_free)
    )

    # 支持 gates 下按检测类型的配置（不暴露具体工具），将其映射到内部 tools.* 配置
    # 同时支持 linter 行宽从 formatter 行宽继承（若未显式设置）。
    try:
        g_fmt = (
            gates.get("formatter", {})
            if isinstance(gates.get("formatter", {}), dict)
            else {}
        )
        g_lin = (
            gates.get("linter", {}) if isinstance(gates.get("linter", {}), dict) else {}
        )
        # formatter: line_length
        fmt_ll_set = False
        if "line_length" in g_fmt:
            cfg.tools.formatter.line_length = int(g_fmt.get("line_length"))
            fmt_ll_set = True
        # linter: ruleset / line_length / docstyle / ignore
        rs = g_lin.get("ruleset")
        if isinstance(rs, list):
            cfg.tools.linter.ruleset = [str(x) for x in rs]
        lin_ll_set = False
        if "line_length" in g_lin:
            cfg.tools.linter.line_length = int(g_lin.get("line_length"))
            lin_ll_set = True
        if "docstyle_convention" in g_lin:
            cfg.tools.linter.docstyle_convention = g_lin.get("docstyle_convention")
        # Map gates.linter.ignore -> tools.linter.ignore (support YAML that nests under gates)
        ig_list = g_lin.get("ignore")
        if isinstance(ig_list, list):
            cfg.tools.linter.ignore = [str(x) for x in ig_list]
        # 继承：若 linter 未设置行宽而 formatter 已设置，则使用 formatter 的行宽
        if (not lin_ll_set) and fmt_ll_set:
            cfg.tools.linter.line_length = cfg.tools.formatter.line_length
    except Exception:
        pass
    # gates.typecheck.strict -> tools.typecheck.strict
    try:
        g_tc = (
            gates.get("typecheck", {})
            if isinstance(gates.get("typecheck", {}), dict)
            else {}
        )
        if "strict" in g_tc:
            cfg.tools.typecheck.strict = bool(g_tc.get("strict"))
        # typecheck.errors_max -> mypy_errors_max
        if "errors_max" in g_tc:
            cfg.gates.mypy_errors_max = int(g_tc.get("errors_max"))
    except Exception:
        pass

    # gates.imports.* -> tools.deps.import_rules
    try:
        g_imp = (
            gates.get("imports", {})
            if isinstance(gates.get("imports", {}), dict)
            else {}
        )
        # Accept either flattened keys under imports or a nested 'matrix' rule
        matrix = (
            g_imp.get("matrix", g_imp.get("rules", {}))
            if isinstance(g_imp, dict)
            else {}
        )
        # matrix default 强制为 deny（严格白名单，固定不可配置）
        cfg.tools.deps.import_rules.matrix_default = "deny"
        # forbid private modules
        fpm = matrix.get(
            "forbid_private_modules", g_imp.get("forbid_private_modules", None)
        )
        if isinstance(fpm, bool):
            cfg.tools.deps.import_rules.forbid_private_modules = fpm
        # allow patterns
        ap = matrix.get("allow_patterns", g_imp.get("allow_patterns", None))
        if isinstance(ap, list):
            tmp: list[tuple[str, str]] = []
            for it in ap:
                if isinstance(it, (list, tuple)) and len(it) == 2:
                    tmp.append((str(it[0]), str(it[1])))
            cfg.tools.deps.import_rules.allow_patterns = tmp
        # aggregator rule (optional)
        agg = (
            g_imp.get("aggregator", {})
            if isinstance(g_imp.get("aggregator", {}), dict)
            else {}
        )
        rva = agg.get(
            "require_via_aggregator", g_imp.get("require_via_aggregator", None)
        )
        if isinstance(rva, bool):
            cfg.tools.deps.import_rules.require_via_aggregator = rva
        try:
            aed = agg.get(
                "allowed_external_depth", g_imp.get("allowed_external_depth", None)
            )
            if aed is not None:
                cfg.tools.deps.import_rules.allowed_external_depth = int(aed)
        except Exception:
            pass
        awl = agg.get("whitelist", g_imp.get("aggregator_whitelist", None))
        if isinstance(awl, list):
            cfg.tools.deps.import_rules.aggregator_whitelist = [str(x) for x in awl]
        # forbid_private_symbols -> imports_forbid_private_symbols (gate-level)
        fps = g_imp.get("forbid_private_symbols", None)
        if isinstance(fps, bool):
            cfg.gates.imports_forbid_private_symbols = fps
        # cycles_max -> imports_cycles_max
        try:
            cyc = g_imp.get("cycles_max", None)
            if cyc is not None:
                cfg.gates.imports_cycles_max = int(cyc)
        except Exception:
            pass
        # violations_max -> import_violations_max
        if "violations_max" in g_imp:
            cfg.gates.import_violations_max = int(g_imp.get("violations_max"))
    except Exception:
        pass

    # gates.formatter.clean -> formatter_clean
    try:
        g_fmt = (
            gates.get("formatter", {})
            if isinstance(gates.get("formatter", {}), dict)
            else {}
        )
        if "clean" in g_fmt:
            cfg.gates.formatter_clean = bool(g_fmt.get("clean"))
    except Exception:
        pass

    # gates.linter.errors_max -> linter_errors_max
    try:
        g_lin = (
            gates.get("linter", {}) if isinstance(gates.get("linter", {}), dict) else {}
        )
        if "errors_max" in g_lin:
            cfg.gates.linter_errors_max = int(g_lin.get("errors_max"))
    except Exception:
        pass

    # gates.tests.coverage_min / allow_missing_component_tests / components_dep_stub_free_requires_green
    try:
        g_tests = (
            gates.get("tests", {}) if isinstance(gates.get("tests", {}), dict) else {}
        )
        if "coverage_min" in g_tests:
            cfg.gates.coverage_min = int(g_tests.get("coverage_min"))
        if "allow_missing_component_tests" in g_tests:
            cfg.gates.allow_missing_component_tests = bool(
                g_tests.get("allow_missing_component_tests")
            )
        if "components_dep_stub_free_requires_green" in g_tests:
            cfg.gates.components_dep_stub_free_requires_green = bool(
                g_tests.get("components_dep_stub_free_requires_green")
            )
        if "red_failures_are_assertions" in g_tests:
            cfg.gates.tests_red_failures_are_assertions = bool(
                g_tests.get("red_failures_are_assertions")
            )
    except Exception:
        pass

    # gates.complexity.{max_file_loc, cc_max_rank_max, mi_min}
    try:
        g_cpx = (
            gates.get("complexity", {})
            if isinstance(gates.get("complexity", {}), dict)
            else {}
        )
        if "max_file_loc" in g_cpx:
            cfg.gates.max_file_loc = int(g_cpx.get("max_file_loc"))
        if "cc_max_rank_max" in g_cpx:
            val = g_cpx.get("cc_max_rank_max")
            if isinstance(val, str) and val.strip():
                cfg.gates.cc_max_rank_max = val.strip().upper()
        if "mi_min" in g_cpx:
            try:
                cfg.gates.mi_min = int(g_cpx.get("mi_min"))
            except Exception:
                cfg.gates.mi_min = None
    except Exception:
        pass

    # gates.functions
    try:
        g_fn = (
            gates.get("functions", {})
            if isinstance(gates.get("functions", {}), dict)
            else {}
        )
        if "loc_max" in g_fn:
            cfg.gates.fn_loc_max = int(g_fn.get("loc_max"))
        if "args_max" in g_fn:
            cfg.gates.fn_args_max = int(g_fn.get("args_max"))
        if "nesting_max" in g_fn:
            cfg.gates.fn_nesting_max = int(g_fn.get("nesting_max"))
        if "count_docstrings" in g_fn:
            cfg.gates.fn_count_docstrings = bool(g_fn.get("count_docstrings"))
    except Exception:
        pass

    # gates.docs
    try:
        g_docs = (
            gates.get("docs", {}) if isinstance(gates.get("docs", {}), dict) else {}
        )
        if "contracts_missing_max" in g_docs:
            cfg.gates.doc_contracts_missing_max = int(
                g_docs.get("contracts_missing_max")
            )
        reqs = g_docs.get("required_sections", None)
        if isinstance(reqs, list):
            cfg.gates.doc_required_sections = [str(x) for x in reqs]
        if "case_sensitive" in g_docs:
            cfg.gates.doc_case_sensitive = bool(g_docs.get("case_sensitive"))
    except Exception:
        pass

    # gates.packages and nested exports
    try:
        g_pkg = (
            gates.get("packages", {})
            if isinstance(gates.get("packages", {}), dict)
            else {}
        )
        if "require_dunder_init" in g_pkg:
            cfg.gates.packages_require_dunder_init = bool(
                g_pkg.get("require_dunder_init")
            )
        mie = g_pkg.get("missing_init_exclude", None)
        if isinstance(mie, list):
            cfg.gates.packages_missing_init_exclude = [str(x) for x in mie]
        # public no side effects
        if "public_no_side_effects" in g_pkg:
            cfg.gates.packages_public_no_side_effects = bool(
                g_pkg.get("public_no_side_effects")
            )
        calls = g_pkg.get("public_side_effect_forbidden_calls", None)
        if isinstance(calls, list):
            cfg.gates.packages_public_side_effect_forbidden_calls = [
                str(x) for x in calls
            ]
        g_exp = (
            g_pkg.get("exports", {})
            if isinstance(g_pkg.get("exports", {}), dict)
            else {}
        )
        if "no_private" in g_exp:
            cfg.gates.exports_no_private = bool(g_exp.get("no_private"))
        if "require_nonempty_all" in g_exp:
            cfg.gates.exports_require_nonempty_all = bool(
                g_exp.get("require_nonempty_all")
            )
        ex_all = g_exp.get("nonempty_all_exclude", None)
        if isinstance(ex_all, list):
            cfg.gates.exports_nonempty_all_exclude = [str(x) for x in ex_all]
    except Exception:
        pass

    # gates.tests_presence
    try:
        g_tp = (
            gates.get("tests_presence", {})
            if isinstance(gates.get("tests_presence", {}), dict)
            else {}
        )
        if "modules_require_named_tests" in g_tp:
            cfg.gates.modules_require_named_tests = bool(
                g_tp.get("modules_require_named_tests")
            )
        mte = g_tp.get("modules_named_tests_exclude", None)
        if isinstance(mte, list):
            cfg.gates.modules_named_tests_exclude = [str(x) for x in mte]
    except Exception:
        pass

    # gates.failfast
    try:
        g_ff = (
            gates.get("failfast", {})
            if isinstance(gates.get("failfast", {}), dict)
            else {}
        )
        if "forbid_dict_get_default" in g_ff:
            cfg.gates.failfast_forbid_dict_get_default = bool(
                g_ff.get("forbid_dict_get_default")
            )
        if "forbid_getattr_default" in g_ff:
            cfg.gates.failfast_forbid_getattr_default = bool(
                g_ff.get("forbid_getattr_default")
            )
        if "forbid_env_default" in g_ff:
            cfg.gates.failfast_forbid_env_default = bool(g_ff.get("forbid_env_default"))
        if "forbid_import_fallback" in g_ff:
            cfg.gates.failfast_forbid_import_fallback = bool(
                g_ff.get("forbid_import_fallback")
            )
        if "forbid_attr_fallback" in g_ff:
            cfg.gates.failfast_forbid_attr_fallback = bool(
                g_ff.get("forbid_attr_fallback")
            )
        if "forbid_key_fallback" in g_ff:
            cfg.gates.failfast_forbid_key_fallback = bool(
                g_ff.get("forbid_key_fallback")
            )
        if "forbid_hasattr" in g_ff:
            cfg.gates.failfast_forbid_hasattr = bool(g_ff.get("forbid_hasattr"))
        if "forbid_dict_get_any" in g_ff:
            cfg.gates.failfast_forbid_dict_get_any = bool(
                g_ff.get("forbid_dict_get_any")
            )
        if "forbid_getattr_any" in g_ff:
            cfg.gates.failfast_forbid_getattr_any = bool(g_ff.get("forbid_getattr_any"))
        tags = g_ff.get("allow_comment_tags", None)
        if isinstance(tags, list):
            cfg.gates.failfast_allow_comment_tags = [str(x) for x in tags]
    except Exception:
        pass

    # gates.classes
    try:
        gates = data.get("gates") or {}
        g_cls = (
            gates.get("classes", {})
            if isinstance(gates.get("classes", {}), dict)
            else {}
        )
        if "require_super_init" in g_cls:
            cfg.gates.classes_require_super_init = bool(
                g_cls.get("require_super_init")
            )
        ex = g_cls.get("exclude", None)
        if isinstance(ex, list):
            cfg.gates.classes_super_init_exclude = [str(x) for x in ex]
        tags = g_cls.get("allow_comment_tags", None)
        if isinstance(tags, list):
            cfg.gates.classes_super_init_allow_comment_tags = [str(x) for x in tags]
    except Exception:
        pass
    # gates.runtime_validation
    try:
        gates = data.get("gates") or {}
        g_rv = (
            gates.get("runtime_validation", {})
            if isinstance(gates.get("runtime_validation", {}), dict)
            else {}
        )
        if "require_validate_call" in g_rv:
            cfg.gates.runtime_validation_require_validate_call = bool(
                g_rv.get("require_validate_call")
            )
        if "require_innermost" in g_rv:
            cfg.gates.runtime_validation_require_innermost = bool(
                g_rv.get("require_innermost")
            )
        ex = g_rv.get("exclude")
        if isinstance(ex, list):
            cfg.gates.runtime_validation_exclude = [str(x) for x in ex]
        if "skip_private" in g_rv:
            cfg.gates.runtime_validation_skip_private = bool(
                g_rv.get("skip_private")
            )
        if "skip_magic" in g_rv:
            cfg.gates.runtime_validation_skip_magic = bool(g_rv.get("skip_magic"))
        if "skip_properties" in g_rv:
            cfg.gates.runtime_validation_skip_properties = bool(
                g_rv.get("skip_properties")
            )
        tags = g_rv.get("allow_comment_tags")
        if isinstance(tags, list):
            cfg.gates.runtime_validation_allow_comment_tags = [str(x) for x in tags]
    except Exception:
        pass
    return cfg


def write_qa_config(path: str | Path, force: bool = False) -> Path:
    p = Path(path)
    if p.exists() and not force:
        # Do not overwrite; write example alongside
        example = p.with_name(p.stem + ".qa.example.yaml")
        example.write_text(_strict_template_or_default(), encoding="utf-8")
        return example
    p.write_text(_strict_template_or_default(), encoding="utf-8")
    return p


def _strict_template_or_default() -> str:
    """Load the packaged template (codeclinic.yaml) if available; otherwise use programmatic defaults."""
    # Prefer importlib.resources for packaged access
    try:
        try:
            from importlib.resources import files  # type: ignore
        except Exception:
            files = None  # type: ignore
        if files is not None:
            try:
                pkg_root = files(__package__)  # codeclinic
                pref = pkg_root / "templates" / "codeclinic.yaml"
                return pref.read_text(encoding="utf-8")
            except Exception:
                pass
    except Exception:
        pass
    # Fallback to file-system path relative to this module
    try:
        root = Path(__file__).parent / "templates"
        pref = root / "codeclinic.yaml"
        if pref.exists():
            return pref.read_text(encoding="utf-8")
    except Exception:
        pass
    # Final fallback to programmatic defaults
    return default_yaml()
