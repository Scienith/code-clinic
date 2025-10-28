from __future__ import annotations

from dataclasses import dataclass, field, asdict
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
    exclude: List[str] = field(default_factory=lambda: [
        "**/.venv/**", "**/venv/**", "**/__pycache__/**", "**/build/**", "**/dist/**"
    ])
    output: str = "build/codeclinic"


@dataclass
class FormatterCfg:
    provider: str = "black"
    line_length: int = 88


@dataclass
class LinterCfg:
    provider: str = "ruff"
    ruleset: List[str] = field(default_factory=lambda: ["E", "F", "I", "B", "D"])  # include I for import order
    line_length: int = 88
    unsafe_fixes: bool = False
    # Optional: docstring style convention for pydocstyle (e.g., "google", "numpy", "pep257")
    docstyle_convention: Optional[str] = None


@dataclass
class TypecheckCfg:
    provider: str = "mypy"
    strict: bool = True
    config_file: Optional[str] = None


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
    decorator_names: List[str] = field(default_factory=lambda: ["stub"])  # reserved for future


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
    # 新增：每个包内模块是否必须有命名规范 tests/test_<module>.py（仅对包内 .py 文件生效）
    modules_require_named_tests: bool = True
    # 新增：按 glob 模式排除不检查命名测试的模块列表（相对/绝对路径均可，使用 fnmatch）
    modules_named_tests_exclude: List[str] = field(default_factory=list)
    doc_contracts_missing_max: int = 0
    fn_loc_max: int = 50
    fn_args_max: int = 5
    fn_nesting_max: int = 3
    # 是否将 Docstring 行计入函数行数统计
    fn_count_docstrings: bool = True
    exports_no_private: bool = True


@dataclass
class ComponentsCfg:
    scope: str = "package"                 # package | module
    tests_dir_name: str = "tests"          # same-level tests dir under component
    dependency_scope: str = "transitive"   # direct | transitive
    require_self_stub_free: bool = False


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
  stub_ratio_max: 0.25
  # cc_max_rank_max: "C"   # 可选：不允许出现比该等级更差的圈复杂度（A最好、F最差）
  # mi_min: 70             # 可选：不允许文件MI低于该值（0-100）
  components_dep_stub_free_requires_green: true
  allow_missing_component_tests: false
  packages_require_dunder_init: true
  modules_require_named_tests: true
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
    cfg.tools.formatter.line_length = int(fmt.get("line_length", cfg.tools.formatter.line_length))

    lin = tools.get("linter") or {}
    cfg.tools.linter.provider = lin.get("provider", cfg.tools.linter.provider)
    cfg.tools.linter.ruleset = list(lin.get("ruleset", cfg.tools.linter.ruleset))
    cfg.tools.linter.line_length = int(lin.get("line_length", cfg.tools.linter.line_length))
    cfg.tools.linter.unsafe_fixes = bool(lin.get("unsafe_fixes", cfg.tools.linter.unsafe_fixes))
    cfg.tools.linter.docstyle_convention = lin.get("docstyle_convention", cfg.tools.linter.docstyle_convention)

    tc = tools.get("typecheck") or {}
    cfg.tools.typecheck.provider = tc.get("provider", cfg.tools.typecheck.provider)
    cfg.tools.typecheck.strict = bool(tc.get("strict", cfg.tools.typecheck.strict))
    cfg.tools.typecheck.config_file = tc.get("config_file", cfg.tools.typecheck.config_file)

    tst = tools.get("tests") or {}
    cfg.tools.tests.provider = tst.get("provider", cfg.tools.tests.provider)
    cfg.tools.tests.args = list(tst.get("args", cfg.tools.tests.args))
    cov = (tst.get("coverage") or {})
    cfg.tools.tests.coverage.min = int(cov.get("min", cfg.tools.tests.coverage.min))
    cfg.tools.tests.coverage.report = cov.get("report", cfg.tools.tests.coverage.report)
    junit = (tst.get("junit") or {})
    cfg.tools.tests.junit.enabled = bool(junit.get("enabled", cfg.tools.tests.junit.enabled))
    cfg.tools.tests.junit.output = junit.get("output", cfg.tools.tests.junit.output)

    # visuals
    visuals = data.get("visuals") or {}
    if isinstance(visuals, dict):
        cfg.visuals.show_test_status_borders = bool(visuals.get("show_test_status_borders", cfg.visuals.show_test_status_borders))

    cpx = tools.get("complexity") or {}
    cfg.tools.complexity.provider = cpx.get("provider", cfg.tools.complexity.provider)
    cfg.tools.complexity.max_file_loc = int(cpx.get("max_file_loc", cfg.tools.complexity.max_file_loc))
    cfg.tools.complexity.cc_threshold = cpx.get("cc_threshold", cfg.tools.complexity.cc_threshold)

    deps = tools.get("deps") or {}
    cfg.tools.deps.provider = deps.get("provider", cfg.tools.deps.provider)
    ir = (deps.get("import_rules") or {})
    cfg.tools.deps.import_rules.allow_cross_package = bool(ir.get("allow_cross_package", cfg.tools.deps.import_rules.allow_cross_package))
    cfg.tools.deps.import_rules.allow_upward_import = bool(ir.get("allow_upward_import", cfg.tools.deps.import_rules.allow_upward_import))
    cfg.tools.deps.import_rules.allow_skip_levels = bool(ir.get("allow_skip_levels", cfg.tools.deps.import_rules.allow_skip_levels))
    cfg.tools.deps.import_rules.white_list = list(ir.get("white_list", cfg.tools.deps.import_rules.white_list))
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
    cfg.tools.deps.import_rules.forbid_private_modules = bool(ir.get("forbid_private_modules", cfg.tools.deps.import_rules.forbid_private_modules))
    cfg.tools.deps.import_rules.require_via_aggregator = bool(ir.get("require_via_aggregator", cfg.tools.deps.import_rules.require_via_aggregator))
    try:
        aed = ir.get("allowed_external_depth", cfg.tools.deps.import_rules.allowed_external_depth)
        cfg.tools.deps.import_rules.allowed_external_depth = int(aed)
    except Exception:
        pass
    cfg.tools.deps.import_rules.aggregator_whitelist = list(ir.get("aggregator_whitelist", cfg.tools.deps.import_rules.aggregator_whitelist))
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
    cfg.tools.stubs.decorator_names = list(stubs.get("decorator_names", cfg.tools.stubs.decorator_names))

    gates = data.get("gates") or {}
    cfg.gates.formatter_clean = bool(gates.get("formatter_clean", cfg.gates.formatter_clean))
    cfg.gates.linter_errors_max = int(gates.get("linter_errors_max", cfg.gates.linter_errors_max))
    cfg.gates.mypy_errors_max = int(gates.get("mypy_errors_max", cfg.gates.mypy_errors_max))
    cfg.gates.coverage_min = int(gates.get("coverage_min", cfg.gates.coverage_min))
    cfg.gates.max_file_loc = int(gates.get("max_file_loc", cfg.gates.max_file_loc))
    cfg.gates.import_violations_max = int(gates.get("import_violations_max", cfg.gates.import_violations_max))
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
        gates.get("components_dep_stub_free_requires_green", cfg.gates.components_dep_stub_free_requires_green)
    )
    cfg.gates.allow_missing_component_tests = bool(
        gates.get("allow_missing_component_tests", cfg.gates.allow_missing_component_tests)
    )
    cfg.gates.packages_require_dunder_init = bool(
        gates.get("packages_require_dunder_init", cfg.gates.packages_require_dunder_init)
    )
    cfg.gates.modules_require_named_tests = bool(
        gates.get("modules_require_named_tests", cfg.gates.modules_require_named_tests)
    )
    # 解析排除列表
    mte = gates.get("modules_named_tests_exclude", cfg.gates.modules_named_tests_exclude)
    if isinstance(mte, list):
        cfg.gates.modules_named_tests_exclude = [str(x) for x in mte]
    # 函数度量：是否统计 Docstring 行数（默认 True）。
    fcd = gates.get("fn_count_docstrings", cfg.gates.fn_count_docstrings)
    cfg.gates.fn_count_docstrings = bool(fcd)

    # 组件配置
    comp = data.get("components") or {}
    cfg.components.scope = comp.get("scope", cfg.components.scope)
    cfg.components.tests_dir_name = comp.get("tests_dir_name", cfg.components.tests_dir_name)
    cfg.components.dependency_scope = comp.get("dependency_scope", cfg.components.dependency_scope)
    cfg.components.require_self_stub_free = bool(comp.get("require_self_stub_free", cfg.components.require_self_stub_free))
    return cfg


def write_qa_config(path: str | Path, force: bool = False) -> Path:
    p = Path(path)
    if p.exists() and not force:
        # Do not overwrite; write example alongside
        example = p.with_name(p.stem + ".qa.example.yaml")
        example.write_text(default_yaml(), encoding="utf-8")
        return example
    p.write_text(default_yaml(), encoding="utf-8")
    return p
