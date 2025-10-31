"""
Pydantic-based schema validation for QA configuration (codeclinic.yaml).

The validator is optional: if pydantic is not installed in the runtime
environment, callers should gracefully skip strict validation.

Goals
- Catch unknown or misspelled keys early (top-level, tool, tools, docs/dead_code gates)
- Enforce proper types for commonly used fields
- Keep compatibility by allowing extra fields for legacy sections we don't model fully
"""
from __future__ import annotations

from typing import Any, List, Optional


def validate_qa_yaml(data: dict) -> None:
    """Validate loaded YAML config using Pydantic models.

    Raises:
        ValidationError (from pydantic) if validation fails.
        ImportError if pydantic is not available (caller should catch and ignore).
    """
    try:
        # Pydantic v2 preferred; v1 fallback
        try:  # v2
            from pydantic import BaseModel, Field
            from pydantic import ConfigDict  # type: ignore

            class ToolModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                paths: list[str] = Field(default_factory=list)
                include: list[str] = Field(default_factory=list)
                exclude: list[str] = Field(default_factory=list)
                output: Optional[str] = None
                autofix_on_run: bool = False

            class FormatterModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                provider: str = "black"
                line_length: int = 88

            class LinterModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                provider: str = "ruff"
                ruleset: list[str] = Field(default_factory=list)
                line_length: int = 88
                unsafe_fixes: bool = False
                docstyle_convention: Optional[str] = None
                ignore: list[str] = Field(default_factory=list)

            class TypecheckModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                provider: str = "mypy"
                strict: bool = True
                config_file: Optional[str] = None
                ignore_missing_imports: list[str] = Field(default_factory=list)

            class CoverageModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                min: int = 80
                report: str = "xml"

            class JUnitModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                enabled: bool = True
                output: Optional[str] = None

            class TestsModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                provider: str = "pytest"
                args: list[str] = Field(default_factory=list)
                coverage: CoverageModel = CoverageModel()
                junit: JUnitModel = JUnitModel()

            class ComplexityModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                provider: str = "radon"
                max_file_loc: int = 500
                cc_threshold: Optional[str] = None

            class ImportRulesModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                matrix_default: Optional[str] = None
                forbid_private_modules: Optional[bool] = None
                allow_patterns: list[list[str]] | list[tuple[str, str]] = Field(
                    default_factory=list
                )

            class DepsModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                provider: str = "internal"
                import_rules: ImportRulesModel = ImportRulesModel()

            class ToolsModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                formatter: Optional[FormatterModel] = None
                linter: Optional[LinterModel] = None
                typecheck: Optional[TypecheckModel] = None
                tests: Optional[TestsModel] = None
                complexity: Optional[ComplexityModel] = None
                deps: Optional[DepsModel] = None

            class DocsGateModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                contracts_missing_max: int = 0
                mode: str = "rst_or_keywords"
                required_sections: list[str] = Field(default_factory=list)
                required_rst_fields: list[str] = Field(default_factory=list)
                case_sensitive: Optional[bool] = False

            class DeadCodeGateModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                enabled: bool = False
                max: int = 0
                include_type_annotations: bool = False
                allow_module_export_closure: bool = False
                whitelist: list[str] = Field(default_factory=list)
                exclude_globs: list[str] = Field(default_factory=list)
                protocol_nominal: Optional[bool] = None
                protocol_strict_signature: Optional[bool] = None

            class VisualsModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                show_test_status_borders: Optional[bool] = None

            class ImportsGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                forbid_private_symbols: Optional[bool] = None
                cycles_max: Optional[int] = None
                violations_max: Optional[int] = None
                matrix: Optional[dict] = None

            class FormatterGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                clean: Optional[bool] = None
                line_length: Optional[int] = None

            class LinterGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                errors_max: Optional[int] = None
                ruleset: Optional[list[str]] = None
                line_length: Optional[int] = None
                docstyle_convention: Optional[str] = None
                ignore: Optional[list[str]] = None

            class TypecheckGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                strict: Optional[bool] = None
                errors_max: Optional[int] = None
                config_file: Optional[str] = None
                ignore_missing_imports: Optional[list[str]] = None

            class TestsGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                coverage_min: Optional[int] = None
                allow_missing_component_tests: Optional[bool] = None
                components_dep_stub_free_requires_green: Optional[bool] = None
                red_failures_are_assertions: Optional[bool] = None

            class ComplexityGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                max_file_loc: Optional[int] = None
                cc_max_rank_max: Optional[str] = None
                mi_min: Optional[int] = None

            class FunctionsGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                loc_max: Optional[int] = None
                args_max: Optional[int] = None
                nesting_max: Optional[int] = None
                count_docstrings: Optional[bool] = None

            class ExportsGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                no_private: Optional[bool] = None
                require_nonempty_all: Optional[bool] = None
                nonempty_all_exclude: Optional[list[str]] = None
                all_symbols_resolved: Optional[bool] = None
                all_symbols_exclude: Optional[list[str]] = None

            class PackagesGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                require_dunder_init: Optional[bool] = None
                missing_init_exclude: Optional[list[str]] = None
                public_no_side_effects: Optional[bool] = None
                public_side_effect_forbidden_calls: Optional[list[str]] = None
                exports: Optional[ExportsGateModel] = None

            class TestsPresenceGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                modules_require_named_tests: Optional[bool] = None
                modules_named_tests_exclude: Optional[list[str]] = None

            class FailfastGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                forbid_dict_get_any: Optional[bool] = None
                forbid_getattr_any: Optional[bool] = None
                forbid_dict_get_default: Optional[bool] = None
                forbid_getattr_default: Optional[bool] = None
                forbid_hasattr: Optional[bool] = None
                forbid_env_default: Optional[bool] = None
                forbid_import_fallback: Optional[bool] = None
                forbid_attr_fallback: Optional[bool] = None
                forbid_key_fallback: Optional[bool] = None
                allow_comment_tags: Optional[list[str]] = None

            class RuntimeValidationGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                require_validate_call: Optional[bool] = None
                require_innermost: Optional[bool] = None
                exclude: Optional[list[str]] = None
                skip_private: Optional[bool] = None
                skip_magic: Optional[bool] = None
                skip_properties: Optional[bool] = None
                allow_comment_tags: Optional[list[str]] = None

            class ClassesGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                require_super_init: Optional[bool] = None
                exclude: Optional[list[str]] = None
                allow_comment_tags: Optional[list[str]] = None

            class ProjectGateModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                src_single_package: Optional[bool] = None
                src_dir_name: Optional[str] = None
                src_ignore_dirs: Optional[list[str]] = None

            class GatesModel(BaseModel):
                model_config = ConfigDict(extra="allow")
                imports: Optional[ImportsGateModel] = None
                formatter: Optional[FormatterGateModel] = None
                linter: Optional[LinterGateModel] = None
                typecheck: Optional[TypecheckGateModel] = None
                tests: Optional[TestsGateModel] = None
                complexity: Optional[ComplexityGateModel] = None
                functions: Optional[FunctionsGateModel] = None
                docs: Optional[DocsGateModel] = None
                packages: Optional[PackagesGateModel] = None
                tests_presence: Optional[TestsPresenceGateModel] = None
                failfast: Optional[FailfastGateModel] = None
                runtime_validation: Optional[RuntimeValidationGateModel] = None
                classes: Optional[ClassesGateModel] = None
                project: Optional[ProjectGateModel] = None
                # top-level flags
                stubs_no_notimplemented_non_abc: Optional[bool] = None
                forbid_cast: Optional[bool] = None
                cast_allow_comment_tags: Optional[list[str]] = None
                forbid_lambda: Optional[bool] = None
                lambda_allow_comment_tags: Optional[list[str]] = None
                # newly added analyzer
                dead_code: Optional[DeadCodeGateModel] = None

            class RootModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                tool: Optional[ToolModel] = None
                tools: Optional[ToolsModel] = None
                gates: Optional[GatesModel] = None
                visuals: Optional[VisualsModel] = None

            # Validate
            _ = RootModel.model_validate(data)
            return

        except Exception:  # v1 fallback
            from pydantic import BaseModel, Field, ValidationError  # type: ignore

            class ToolModel(BaseModel):
                class Config:
                    extra = "forbid"

                paths: List[str] = Field(default_factory=list)
                include: List[str] = Field(default_factory=list)
                exclude: List[str] = Field(default_factory=list)
                output: Optional[str] = None
                autofix_on_run: bool = False

            class FormatterModel(BaseModel):
                class Config:
                    extra = "forbid"

                provider: str = "black"
                line_length: int = 88

            class LinterModel(BaseModel):
                class Config:
                    extra = "forbid"

                provider: str = "ruff"
                ruleset: List[str] = Field(default_factory=list)
                line_length: int = 88
                unsafe_fixes: bool = False
                docstyle_convention: Optional[str] = None
                ignore: List[str] = Field(default_factory=list)

            class TypecheckModel(BaseModel):
                class Config:
                    extra = "forbid"

                provider: str = "mypy"
                strict: bool = True
                config_file: Optional[str] = None
                ignore_missing_imports: List[str] = Field(default_factory=list)

            class CoverageModel(BaseModel):
                class Config:
                    extra = "forbid"

                min: int = 80
                report: str = "xml"

            class JUnitModel(BaseModel):
                class Config:
                    extra = "forbid"

                enabled: bool = True
                output: Optional[str] = None

            class TestsModel(BaseModel):
                class Config:
                    extra = "forbid"

                provider: str = "pytest"
                args: List[str] = Field(default_factory=list)
                coverage: CoverageModel = CoverageModel()
                junit: JUnitModel = JUnitModel()

            class ComplexityModel(BaseModel):
                class Config:
                    extra = "allow"

                provider: str = "radon"
                max_file_loc: int = 500
                cc_threshold: Optional[str] = None

            class ImportRulesModel(BaseModel):
                class Config:
                    extra = "allow"

                matrix_default: Optional[str] = None
                forbid_private_modules: Optional[bool] = None
                allow_patterns: List[List[str]] = Field(default_factory=list)

            class DepsModel(BaseModel):
                class Config:
                    extra = "forbid"

                provider: str = "internal"
                import_rules: ImportRulesModel = ImportRulesModel()

            class ToolsModel(BaseModel):
                class Config:
                    extra = "allow"

                formatter: Optional[FormatterModel] = None
                linter: Optional[LinterModel] = None
                typecheck: Optional[TypecheckModel] = None
                tests: Optional[TestsModel] = None
                complexity: Optional[ComplexityModel] = None
                deps: Optional[DepsModel] = None

            class DocsGateModel(BaseModel):
                class Config:
                    extra = "forbid"

                contracts_missing_max: int = 0
                mode: str = "rst_or_keywords"
                required_sections: List[str] = Field(default_factory=list)
                required_rst_fields: List[str] = Field(default_factory=list)
                case_sensitive: Optional[bool] = False

            class DeadCodeGateModel(BaseModel):
                class Config:
                    extra = "forbid"

                enabled: bool = False
                max: int = 0
                include_type_annotations: bool = False
                allow_module_export_closure: bool = False
                whitelist: List[str] = Field(default_factory=list)
                exclude_globs: List[str] = Field(default_factory=list)
                protocol_nominal: Optional[bool] = None
                protocol_strict_signature: Optional[bool] = None

            class VisualsModel(BaseModel):
                class Config:
                    extra = "allow"

                show_test_status_borders: Optional[bool] = None

            class ImportsGateModel(BaseModel):
                class Config:
                    extra = "allow"

                forbid_private_symbols: Optional[bool] = None
                cycles_max: Optional[int] = None
                violations_max: Optional[int] = None
                matrix: Optional[dict] = None

            class FormatterGateModel(BaseModel):
                class Config:
                    extra = "allow"

                clean: Optional[bool] = None
                line_length: Optional[int] = None

            class LinterGateModel(BaseModel):
                class Config:
                    extra = "allow"

                errors_max: Optional[int] = None
                ruleset: Optional[List[str]] = None
                line_length: Optional[int] = None
                docstyle_convention: Optional[str] = None
                ignore: Optional[List[str]] = None

            class TypecheckGateModel(BaseModel):
                class Config:
                    extra = "allow"

                strict: Optional[bool] = None
                errors_max: Optional[int] = None
                config_file: Optional[str] = None
                ignore_missing_imports: Optional[List[str]] = None

            class TestsGateModel(BaseModel):
                class Config:
                    extra = "allow"

                coverage_min: Optional[int] = None
                allow_missing_component_tests: Optional[bool] = None
                components_dep_stub_free_requires_green: Optional[bool] = None
                red_failures_are_assertions: Optional[bool] = None

            class ComplexityGateModel(BaseModel):
                class Config:
                    extra = "allow"

                max_file_loc: Optional[int] = None
                cc_max_rank_max: Optional[str] = None
                mi_min: Optional[int] = None

            class FunctionsGateModel(BaseModel):
                class Config:
                    extra = "allow"

                loc_max: Optional[int] = None
                args_max: Optional[int] = None
                nesting_max: Optional[int] = None
                count_docstrings: Optional[bool] = None

            class ExportsGateModel(BaseModel):
                class Config:
                    extra = "allow"

                no_private: Optional[bool] = None
                require_nonempty_all: Optional[bool] = None
                nonempty_all_exclude: Optional[List[str]] = None
                all_symbols_resolved: Optional[bool] = None
                all_symbols_exclude: Optional[List[str]] = None

            class PackagesGateModel(BaseModel):
                class Config:
                    extra = "allow"

                require_dunder_init: Optional[bool] = None
                missing_init_exclude: Optional[List[str]] = None
                public_no_side_effects: Optional[bool] = None
                public_side_effect_forbidden_calls: Optional[List[str]] = None
                exports: Optional[ExportsGateModel] = None

            class TestsPresenceGateModel(BaseModel):
                class Config:
                    extra = "allow"

                modules_require_named_tests: Optional[bool] = None
                modules_named_tests_exclude: Optional[List[str]] = None

            class FailfastGateModel(BaseModel):
                class Config:
                    extra = "allow"

                forbid_dict_get_any: Optional[bool] = None
                forbid_getattr_any: Optional[bool] = None
                forbid_dict_get_default: Optional[bool] = None
                forbid_getattr_default: Optional[bool] = None
                forbid_hasattr: Optional[bool] = None
                forbid_env_default: Optional[bool] = None
                forbid_import_fallback: Optional[bool] = None
                forbid_attr_fallback: Optional[bool] = None
                forbid_key_fallback: Optional[bool] = None
                allow_comment_tags: Optional[List[str]] = None

            class RuntimeValidationGateModel(BaseModel):
                class Config:
                    extra = "allow"

                require_validate_call: Optional[bool] = None
                require_innermost: Optional[bool] = None
                exclude: Optional[List[str]] = None
                skip_private: Optional[bool] = None
                skip_magic: Optional[bool] = None
                skip_properties: Optional[bool] = None
                allow_comment_tags: Optional[List[str]] = None

            class ClassesGateModel(BaseModel):
                class Config:
                    extra = "allow"

                require_super_init: Optional[bool] = None
                exclude: Optional[List[str]] = None
                allow_comment_tags: Optional[List[str]] = None

            class ProjectGateModel(BaseModel):
                class Config:
                    extra = "allow"

                src_single_package: Optional[bool] = None
                src_dir_name: Optional[str] = None
                src_ignore_dirs: Optional[List[str]] = None

            class GatesModel(BaseModel):
                class Config:
                    extra = "allow"

                imports: Optional[ImportsGateModel] = None
                formatter: Optional[FormatterGateModel] = None
                linter: Optional[LinterGateModel] = None
                typecheck: Optional[TypecheckGateModel] = None
                tests: Optional[TestsGateModel] = None
                complexity: Optional[ComplexityGateModel] = None
                functions: Optional[FunctionsGateModel] = None
                docs: Optional[DocsGateModel] = None
                packages: Optional[PackagesGateModel] = None
                tests_presence: Optional[TestsPresenceGateModel] = None
                failfast: Optional[FailfastGateModel] = None
                runtime_validation: Optional[RuntimeValidationGateModel] = None
                classes: Optional[ClassesGateModel] = None
                project: Optional[ProjectGateModel] = None
                stubs_no_notimplemented_non_abc: Optional[bool] = None
                forbid_cast: Optional[bool] = None
                cast_allow_comment_tags: Optional[List[str]] = None
                forbid_lambda: Optional[bool] = None
                lambda_allow_comment_tags: Optional[List[str]] = None
                dead_code: Optional[DeadCodeGateModel] = None

            class RootModel(BaseModel):
                class Config:
                    extra = "forbid"

                tool: Optional[ToolModel] = None
                tools: Optional[ToolsModel] = None
                gates: Optional[GatesModel] = None
                visuals: Optional[VisualsModel] = None

            _ = RootModel.parse_obj(data)
            return
    except ImportError:
        # Pydantic not available in runtime; caller may skip strict validation
        raise
