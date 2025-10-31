"""
Dead code analysis based on static symbol-level usage graph.

Implements the rules discussed:
 - Roots: only symbols publicly exported from top-level package __init__.py under src/<top_pkg>/, plus whitelist.
 - Policy closure: exported class -> keep entire class body; optionally, exported module -> keep module-level public defs.
 - Edge types collected from AST: call, inherit, decorator, alias/import resolution, exception, isinstance/issubclass,
   property/descriptor, value-flow (defaults, return-escape minimal), selected attribute uses (self/cls/ClassName, module aliases).
 - Exclusions: mere imports without use, type annotations (incl. TYPE_CHECKING) ignored by default, dynamic/reflection ignored.

Outputs a JSON report with nodes, edges, roots, reachable and dead symbols.
Also exposes an explain-path helper that returns one root→target path
under the default path policy described in docs:
  alias* (call|value-flow|decorator|exception|isinstance|property|return-escape|descriptor)+
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import ast
import sys
import fnmatch
import os


@dataclass
class Sym:
    fqn: str
    kind: str  # module|class|function|method
    file: str
    line: int
    arity: int = -1  # number of positional args (methods exclude self/cls), -1 unknown


@dataclass
class Edge:
    src: str
    dst: str
    type: str
    file: str
    line: int


@dataclass
class ModuleInfo:
    fqn: str
    path: Path
    defs: Dict[str, str] = field(default_factory=dict)  # local name -> FQN
    classes: Dict[str, Set[str]] = field(default_factory=dict)  # class name -> set(method FQNs)
    alias: Dict[str, str] = field(default_factory=dict)  # local alias -> target FQN or module
    bases: Dict[str, List[str]] = field(default_factory=dict)  # class local name -> list of resolved base FQNs


# Global registry of function/method return types across all parsed modules
# Maps callee FQN -> list of return type FQNs (best-effort)
GLOBAL_FN_RETURN_TYPES: Dict[str, List[str]] = {}


def _collect_py_files(paths: List[str], include: List[str], exclude: List[str]) -> List[Path]:
    collected: List[Path] = []
    for root in paths:
        base = Path(root)
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            # prune excluded dirs
            dir_rel_list = list(dirnames)
            for d in dir_rel_list:
                d_path = Path(dirpath) / d
                try:
                    rel = str(d_path.relative_to(base))
                except Exception:
                    rel = str(d_path)
                if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                    dirnames.remove(d)
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                f_path = Path(dirpath) / fn
                try:
                    rel = str(f_path.relative_to(base))
                except Exception:
                    rel = str(f_path)
                if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                    continue
                if include and not any(fnmatch.fnmatch(rel, pat) for pat in include):
                    # Heuristic: if include targets Python files (e.g., **/*.py), still accept .py at top-level
                    if not rel.endswith('.py'):
                        continue
                collected.append(f_path)
    return collected


def _path_to_module_fqn(file_path: Path, roots: List[Path]) -> Optional[str]:
    for root in roots:
        try:
            rel = file_path.relative_to(root)
        except Exception:
            continue
        parts = list(rel.parts)
        if not parts:
            return None
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = Path(parts[-1]).stem
        return ".".join([p for p in parts if p])
    return None


def _find_top_packages(paths: List[str]) -> Dict[str, Path]:
    """Find top-level packages under each root (src/<top_pkg>/)."""
    tops: Dict[str, Path] = {}
    for root in paths:
        base = Path(root)
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "__init__.py").exists():
                pkg = child.name
                tops[pkg] = child
    return tops


def _parse_exports_from_init(init_path: Path) -> Set[str]:
    exported: Set[str] = set()
    try:
        src = init_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        return exported
    # __all__ = ["A", "B"] precedence
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    names: Set[str] = set()
                    val = node.value
                    if isinstance(val, (ast.List, ast.Tuple, ast.Set)):
                        for elt in val.elts:
                            if isinstance(elt, ast.Str):
                                names.add(elt.s)
                    elif isinstance(val, ast.Call) and getattr(val.func, "id", "") == "list":
                        # best-effort; skip dynamic
                        pass
                    if names:
                        exported |= names
    if exported:
        return exported
    # Fallback: from .x import Y as Z → export Z；from . import X → X
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if (node.level or 0) >= 1:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    exported.add(alias.asname or alias.name)
    # Also include top-level assignments/defs that are not private
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = getattr(node, "name", "")
            if name and not name.startswith("_"):
                exported.add(name)
    return exported


def _sym_fqn(module_fqn: str, name: str) -> str:
    return f"{module_fqn}.{name}" if module_fqn else name


class _SymVisitor(ast.NodeVisitor):
    def __init__(self, mod: ModuleInfo, defs: Dict[str, Sym], edges: List[Edge]):
        self.mod = mod
        self.defs = defs
        self.edges = edges
        self.class_stack: List[str] = []  # class FQN stack
        self.func_stack: List[str] = []   # current function/method FQN
        self.inner_defs_in_cur_func: Set[str] = set()
        # Local alias stack for function scope imports
        self.alias_stack: List[Dict[str, str]] = []
        # Learned attribute types per class: {class_fqn: {attr: type_fqn}}
        self.attr_types_by_class: Dict[str, Dict[str, str]] = {}
        # Function-scope variable types (from param annotations/returns)
        self.var_types_stack: List[Dict[str, str]] = []

    # --- helpers ---
    def _current_fqn(self) -> Optional[str]:
        if self.func_stack:
            return self.func_stack[-1]
        if self.class_stack:
            return self.class_stack[-1]
        return self.mod.fqn

    def _add_edge(self, dst_fqn: Optional[str], etype: str, node: ast.AST) -> None:
        if not dst_fqn:
            return
        src_fqn = self._current_fqn()
        if not src_fqn:
            return
        self.edges.append(
            Edge(src=src_fqn, dst=dst_fqn, type=etype, file=str(self.mod.path), line=getattr(node, "lineno", 0) or 0)
        )

    def _resolve_name(self, name: str) -> Optional[str]:
        # Local def
        if name in self.mod.defs:
            return self.mod.defs[name]
        # Alias to external or internal
        # check local alias scopes (from innermost to outermost)
        for scope in reversed(self.alias_stack):
            if name in scope:
                return scope[name]
        target = self.mod.alias.get(name)
        if target:
            return target
        # Module-level unqualified name may be attribute of module alias (handled elsewhere)
        return None

    def _resolve_attr(self, value: ast.AST, attr: str) -> Optional[str]:
        # self.attr / cls.attr — handle before generic Name case
        if isinstance(value, ast.Name) and value.id in {"self", "cls"} and self.class_stack:
            cls_fqn = self.class_stack[-1]
            return f"{cls_fqn}.{attr}"
        # self.<field>.<member> where field type is inferred from __init__
        if (
            isinstance(value, ast.Attribute)
            and isinstance(getattr(value, "value", None), ast.Name)
            and getattr(value.value, "id", None) == "self"
            and self.class_stack
        ):
            cls_fqn = self.class_stack[-1]
            field = getattr(value, "attr", "")
            tfqn = (self.attr_types_by_class.get(cls_fqn) or {}).get(field)
            if tfqn:
                return f"{tfqn}.{attr}"
        # mod.SYM or ClassName.attr within same module
        if isinstance(value, ast.Name):
            base = value.id
            # local alias stack first
            target = None
            for scope in reversed(self.alias_stack):
                if base in scope:
                    target = scope[base]
                    break
            if target is None:
                target = self.mod.alias.get(base)
            if target:
                return f"{target}.{attr}"
            # ClassName.attr within same module
            if base in self.mod.defs:
                fqn = self.mod.defs[base]
                return f"{fqn}.{attr}"
            return None
        # super().meth()
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "super":
            # Resolve to all direct bases with same member name (best-effort) → connect to each candidate
            # We'll return a special marker; caller will expand
            return f"__SUPER__.{attr}"
        return None

    # --- top-level symbol collection ---
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        fqn = _sym_fqn(self.mod.fqn, node.name)
        self.mod.defs[node.name] = fqn
        self.mod.classes.setdefault(node.name, set())
        self.defs.setdefault(fqn, Sym(fqn=fqn, kind="class", file=str(self.mod.path), line=node.lineno))
        # Ensure per-class attribute type map exists
        self.attr_types_by_class.setdefault(fqn, {})
        # into class scope (so inheritance edges originate from class)
        self.class_stack.append(fqn)
        # inherit edges
        resolved_bases: List[str] = []
        for base in node.bases:
            target = self._name_of_expr(base)
            if target:
                # resolve alias fully-qualified if possible
                dst = self._resolve_any(target)
                self._add_edge(dst, "inherit", base)
                if isinstance(dst, str):
                    resolved_bases.append(dst)
        # record resolved bases for nominal protocol checks
        self.mod.bases[getattr(node, "name", "")] = resolved_bases
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: D401
        self._handle_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_func(node)

    def _handle_func(self, node: ast.AST) -> None:
        name = getattr(node, "name", "")
        if self.class_stack:
            cls_fqn = self.class_stack[-1]
            fqn = f"{cls_fqn}.{name}"
            self.mod.classes.setdefault(cls_fqn.split(".")[-1], set()).add(fqn)
            kind = "method"
        else:
            fqn = _sym_fqn(self.mod.fqn, name)
            kind = "function"
        self.mod.defs[name] = fqn
        # compute simple arity (positional args), drop self/cls for methods
        arity = -1
        try:
            args = getattr(node, "args", None)
            if args is not None:
                pos_only = len(getattr(args, "posonlyargs", []) or [])
                pos = len(getattr(args, "args", []) or [])
                if kind == "method" and pos > 0:
                    # exclude self/cls
                    pos = max(0, pos - 1)
                arity = pos_only + pos
        except Exception:
            arity = -1
        self.defs.setdefault(
            fqn,
            Sym(
                fqn=fqn,
                kind=kind,
                file=str(self.mod.path),
                line=getattr(node, "lineno", 0) or 0,
                arity=arity,
            ),
        )

        # record return type annotation (best-effort)
        try:
            ann = getattr(node, "returns", None)
            if ann is not None:
                names = self._type_names_from_annotation(ann)
                types: List[str] = []
                for n in names:
                    if not n or n in {"None", "NoneType"}:
                        continue
                    r = self._resolve_any(n) or n
                    types.append(str(r))
                if types:
                    # store under current function FQN
                    setattr(self, "_fn_return_types_init", True)
                    # Initialize map lazily
                    if not hasattr(self, "fn_return_types"):
                        self.fn_return_types = {}
                    self.fn_return_types[fqn] = types
        except Exception:
            pass

        # decorators
        for dec in getattr(node, "decorator_list", []) or []:
            for ref in self._refs_in_decorator(dec):
                dst = self._resolve_any(ref)
                self._add_edge(dst, "decorator", dec)
        # defaults value-flow
        for d in getattr(node, "args", None).defaults or []:
            ref = self._name_of_expr(d)
            if ref:
                self._add_edge(self._resolve_any(ref), "value-flow", d)

        self.func_stack.append(fqn)
        # push local alias scope
        self.alias_stack.append({})
        # push local var types scope (initialize from parameter annotations)
        vtypes: Dict[str, str] = {}
        try:
            args = getattr(node, "args", None)
            if args is not None:
                pos = list(getattr(args, "args", []) or [])
                kwonly = list(getattr(args, "kwonlyargs", []) or [])
                params = pos + kwonly
                start = 1 if kind == "method" and pos else 0
                for idx, a in enumerate(params):
                    if idx < start:
                        continue
                    ann = getattr(a, "annotation", None)
                    if ann is not None:
                        tname = self._name_of_expr(ann)
                        if tname:
                            tfqn = self._resolve_any(tname) or tname
                            pname = getattr(a, "arg", "")
                            if pname:
                                vtypes[pname] = str(tfqn)
        except Exception:
            pass
        self.var_types_stack.append(vtypes)
        # track inner defs in this function for return-escape
        self.inner_defs_in_cur_func = set()
        for st in getattr(node, "body", []) or []:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.inner_defs_in_cur_func.add(getattr(st, "name", ""))
        # Walk body for calls/aliases/returns with additional type-based fallbacks
        for st in getattr(node, "body", []) or []:
            # leverage generic visitor for nested handling
            self.visit(st)
        # Infer return types from simple `return ClassName(...)` patterns (PEP 604/Union 之外的补充)
        try:
            for st in getattr(node, "body", []) or []:
                if isinstance(st, ast.Return):
                    rv = getattr(st, "value", None)
                    if isinstance(rv, ast.Call):
                        n = self._name_of_expr(getattr(rv, "func", None))
                        if n:
                            tfqn = self._resolve_any(n) or n
                            if isinstance(tfqn, str):
                                self.fn_return_types.setdefault(fqn, [])
                                if tfqn not in self.fn_return_types[fqn]:
                                    self.fn_return_types[fqn].append(tfqn)
                        # if func is Attribute like self.<field>.ctor, the above generic path suffices
        except Exception:
            pass
        # pop local alias scope
        _ = self.alias_stack.pop() if self.alias_stack else None
        # pop local var types scope
        _ = self.var_types_stack.pop() if self.var_types_stack else None
        # If this is __init__ of a class, infer simple `self.<attr> = <param>` types from annotations
        try:
            if kind == "method" and name == "__init__" and self.class_stack:
                cls_fqn = self.class_stack[-1]
                # map parameter name -> annotated type FQN
                param_types: Dict[str, str] = {}
                fn_args = getattr(node, "args", None)
                if fn_args is not None:
                    pos = list(getattr(fn_args, "args", []) or [])
                    kwonly = list(getattr(fn_args, "kwonlyargs", []) or [])
                    # Skip first (self) only among positional
                    params = pos[1:] + kwonly
                    for a in params:
                        ann = getattr(a, "annotation", None)
                        if ann is not None:
                            tname = self._name_of_expr(ann)
                            if tname:
                                tfqn = self._resolve_any(tname) or tname
                                pname = getattr(a, "arg", "")
                                if pname:
                                    param_types[pname] = str(tfqn)
                for st in list(getattr(node, "body", []) or []):
                    if isinstance(st, ast.Assign):
                        val = getattr(st, "value", None)
                        if isinstance(val, ast.Name) and val.id in param_types:
                            for tgt in getattr(st, "targets", []) or []:
                                if (
                                    isinstance(tgt, ast.Attribute)
                                    and isinstance(getattr(tgt, "value", None), ast.Name)
                                    and getattr(tgt.value, "id", None) == "self"
                                ):
                                    attrn = getattr(tgt, "attr", "")
                                    if attrn:
                                        self.attr_types_by_class.setdefault(cls_fqn, {})[attrn] = param_types[val.id]
        except Exception:
            pass
        self.func_stack.pop()

    def visit_Import(self, node: ast.Import) -> None:
        # Map local/module alias
        aliases = self.alias_stack[-1] if self.alias_stack else self.mod.alias
        for alias in getattr(node, "names", []) or []:
            name = getattr(alias, "name", "") or ""
            asname = getattr(alias, "asname", None) or name.split(".")[0]
            aliases[asname] = name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        aliases = self.alias_stack[-1] if self.alias_stack else self.mod.alias
        module = getattr(node, "module", "") or ""
        level = int(getattr(node, "level", 0) or 0)
        # Resolve relative import to absolute within module fqn
        if level > 0:
            cur_parts = self.mod.fqn.split(".")
            if level == 1:
                # Single dot means "current package"; for __init__.py this is the package itself
                base_parts = cur_parts
            else:
                drop = level - 1
                base_parts = cur_parts[:-drop] if drop <= len(cur_parts) else []
            module = ".".join([*base_parts, module]) if module else ".".join(base_parts)
        for alias in getattr(node, "names", []) or []:
            nm = getattr(alias, "name", "") or ""
            if nm == "*":
                continue
            asname = getattr(alias, "asname", None) or nm
            target = f"{module}.{nm}" if module else nm
            aliases[asname] = target

    def visit_Assign(self, node: ast.Assign) -> None:
        # descriptor on class body: field = Descriptor(...)
        if self.class_stack and isinstance(node.value, ast.Call):
            ref = self._name_of_expr(node.value.func)
            if ref:
                self._add_edge(self._resolve_any(ref), "descriptor", node)
        # property(...) → functions
        if isinstance(node.value, ast.Call) and self._is_name(node.value.func, "property"):
            for arg in node.value.args[:3]:
                r = self._name_of_expr(arg)
                if r:
                    self._add_edge(self._resolve_any(r), "property", arg)
        # Top-level alias assignment: Alias = Target
        if not self.class_stack and not self.func_stack:
            # Only simple Name target(s) and RHS Name/Attribute
            try:
                rhs_ref = self._name_of_expr(node.value) if hasattr(node, "value") else None
            except Exception:
                rhs_ref = None
            if rhs_ref:
                resolved = self._resolve_any(rhs_ref)
                for t in getattr(node, "targets", []) or []:
                    if isinstance(t, ast.Name):
                        # Register as module-level alias mapping
                        self.mod.alias[t.id] = resolved or rhs_ref
                        # Also record an alias edge so path engine can honor alias* prefix
                        try:
                            src = _sym_fqn(self.mod.fqn, t.id)
                            dst = self._resolve_any(rhs_ref) or rhs_ref
                            self.edges.append(
                                Edge(src=src, dst=dst, type="alias", file=str(self.mod.path), line=getattr(node, "lineno", 0) or 0)
                            )
                        except Exception:
                            pass
        # Also record call edges for RHS constructor calls and nested argument calls
        try:
            val = getattr(node, "value", None)
            if val is not None:
                self._record_callable_uses(val)
        except Exception:
            pass
        # Function-scope variable alias: svc = ClassName(...)
        try:
            if self.func_stack and isinstance(getattr(node, "value", None), ast.Call):
                callee = self._name_of_expr(getattr(node.value, "func", None))
                if callee:
                    resolved = self._resolve_any(callee) or callee
                    for t in getattr(node, "targets", []) or []:
                        if isinstance(t, ast.Name) and self.alias_stack:
                            self.alias_stack[-1][t.id] = str(resolved)
        except Exception:
            pass
        # Function-scope variable type: v = callee(...) with annotated return -> alias v to that type
        try:
            if self.func_stack and isinstance(getattr(node, "value", None), ast.Call):
                fn = getattr(node.value, "func", None)
                ref = self._name_of_expr(fn) if fn is not None else None
                if ref:
                    callee_fqn = self._resolve_any(ref) or ref
                    # Prefer local map; fallback to global map across modules
                    rts = getattr(self, "fn_return_types", {}).get(str(callee_fqn), [])
                    if not rts:
                        rts = GLOBAL_FN_RETURN_TYPES.get(str(callee_fqn), [])
                    target_type = next((t for t in rts if t and t not in {"None", "NoneType"}), None)
                    # Fallback: if callee is a class defined in current module, treat as constructor
                    if not target_type and isinstance(callee_fqn, str) and callee_fqn in self.defs and self.defs[callee_fqn].kind == "class":
                        target_type = callee_fqn
                    if target_type and self.var_types_stack:
                        for t in getattr(node, "targets", []) or []:
                            if isinstance(t, ast.Name):
                                self.var_types_stack[-1][t.id] = str(target_type)
                else:
                    # Attribute callee: v = obj.method(...), if obj has inferred type, consult its method return types
                    if (
                        isinstance(fn, ast.Attribute)
                        and isinstance(getattr(fn, "value", None), ast.Name)
                        and self.var_types_stack
                    ):
                        vname = getattr(fn.value, "id", "")
                        owner = (self.var_types_stack[-1] or {}).get(vname)
                        mname = getattr(fn, "attr", "")
                        if owner and mname:
                            callee_fqn = f"{owner}.{mname}"
                            rts = GLOBAL_FN_RETURN_TYPES.get(str(callee_fqn), [])
                            target_type = next((t for t in rts if t and t not in {"None", "NoneType"}), None)
                            if target_type:
                                for t in getattr(node, "targets", []) or []:
                                    if isinstance(t, ast.Name):
                                        self.var_types_stack[-1][t.id] = str(target_type)
        except Exception:
            pass
        # Class attribute type: self.<field> = Name -> learn from var_types
        try:
            if self.class_stack and any(isinstance(t, ast.Attribute) and isinstance(getattr(t, "value", None), ast.Name) and getattr(t.value, "id", None) == "self" for t in getattr(node, "targets", []) or []):
                cls_fqn = self.class_stack[-1]
                field_names = [getattr(t, "attr", "") for t in getattr(node, "targets", []) if isinstance(t, ast.Attribute)]
                val = getattr(node, "value", None)
                tfqn: Optional[str] = None
                if isinstance(val, ast.Name) and self.var_types_stack:
                    tfqn = (self.var_types_stack[-1] or {}).get(getattr(val, "id", ""))
                elif isinstance(val, ast.Call):
                    callee = self._name_of_expr(getattr(val, "func", None))
                    if callee:
                        tfqn = str(self._resolve_any(callee) or callee)
                if tfqn:
                    for fn in field_names:
                        if fn:
                            self.attr_types_by_class.setdefault(cls_fqn, {})[fn] = tfqn
        except Exception:
            pass
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # isinstance/issubclass
        if self._is_name(node.func, "isinstance") or self._is_name(node.func, "issubclass"):
            if len(node.args) >= 2:
                typ = node.args[1]
                for r in self._names_in_type_tuple(typ):
                    self._add_edge(self._resolve_any(r), "isinstance", node)
        # Fallback: self.<field>.method(...) → use learned field type to add direct call edge
        try:
            fn = getattr(node, "func", None)
            if (
                isinstance(fn, ast.Attribute)
                and isinstance(getattr(fn, "value", None), ast.Attribute)
                and isinstance(getattr(fn.value, "value", None), ast.Name)
                and getattr(fn.value.value, "id", None) == "self"
                and self.class_stack
            ):
                cls_fqn = self.class_stack[-1]
                field = getattr(fn.value, "attr", "")
                mname = getattr(fn, "attr", "")
                tfqn = (self.attr_types_by_class.get(cls_fqn) or {}).get(field)
                if tfqn and mname:
                    self._add_edge(f"{tfqn}.{mname}", "call", node)
            # Fallback for var.method(...) where var has inferred type
            if (
                isinstance(fn, ast.Attribute)
                and isinstance(getattr(fn, "value", None), ast.Name)
                and self.var_types_stack
            ):
                vname = getattr(fn.value, "id", "")
                mname = getattr(fn, "attr", "")
                tfqn = (self.var_types_stack[-1] or {}).get(vname)
                if tfqn and mname:
                    self._add_edge(f"{tfqn}.{mname}", "call", node)
        except Exception:
            pass
        # record callable uses recursively (call + refs in args/keywords/containers)
        self._record_callable_uses(node)
        # decorators with args handled in _handle_func
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = getattr(node, "exc", None)
        if isinstance(exc, ast.Call):
            ref = self._name_of_expr(exc.func)
            if ref:
                self._add_edge(self._resolve_any(ref), "exception", exc)
        elif isinstance(exc, (ast.Name, ast.Attribute)):
            ref = self._name_of_expr(exc)
            if ref:
                self._add_edge(self._resolve_any(ref), "exception", exc)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        for h in node.handlers:
            typ = getattr(h, "type", None)
            if typ is None:
                continue
            if isinstance(typ, ast.Tuple):
                for elt in typ.elts:
                    ref = self._name_of_expr(elt)
                    if ref:
                        self._add_edge(self._resolve_any(ref), "exception", elt)
            else:
                ref = self._name_of_expr(typ)
                if ref:
                    self._add_edge(self._resolve_any(ref), "exception", typ)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Local variable annotation: x: Type = ...
        try:
            if self.func_stack and isinstance(getattr(node, "target", None), ast.Name):
                name = getattr(node.target, "id", "")
                ann = getattr(node, "annotation", None)
                if name and ann is not None and self.var_types_stack:
                    tname = self._name_of_expr(ann)
                    if tname:
                        tfqn = self._resolve_any(tname) or tname
                        self.var_types_stack[-1][name] = str(tfqn)
        except Exception:
            pass
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        # return-escape: return inner def/class
        val = getattr(node, "value", None)
        if isinstance(val, ast.Name) and val.id in self.inner_defs_in_cur_func:
            ref = self._resolve_name(val.id)
            self._add_edge(ref, "return-escape", node)
        self.generic_visit(node)

    def visit_List(self, node: ast.List) -> None:
        # Capture constructor calls that appear inside list literals
        for elt in getattr(node, "elts", []) or []:
            self._record_callable_uses(elt)
        self.generic_visit(node)

    def _record_callable_uses(self, expr: ast.AST) -> None:
        """Recursively record 'call' edges and 'value-flow' edges for callable references.
        This captures nested constructor calls in containers and method/function references passed as parameters.
        """
        try:
            if isinstance(expr, ast.Call):
                ref = self._name_of_expr(expr.func)
                if ref:
                    self._add_edge(self._resolve_any(ref), "call", expr)
                else:
                    # Fallback for self.<field>.method(...) using learned field types
                    fn = getattr(expr, "func", None)
                    if (
                        isinstance(fn, ast.Attribute)
                        and isinstance(getattr(fn, "value", None), ast.Attribute)
                        and isinstance(getattr(fn.value, "value", None), ast.Name)
                        and getattr(fn.value.value, "id", None) == "self"
                        and self.class_stack
                    ):
                        cls_fqn = self.class_stack[-1]
                        field = getattr(fn.value, "attr", "")
                        mname = getattr(fn, "attr", "")
                        tfqn = (self.attr_types_by_class.get(cls_fqn) or {}).get(field)
                        if tfqn and mname:
                            self._add_edge(f"{tfqn}.{mname}", "call", expr)
                    # Fallback for var.method(...) where var has inferred type
                    if (
                        isinstance(fn, ast.Attribute)
                        and isinstance(getattr(fn, "value", None), ast.Name)
                        and self.var_types_stack
                    ):
                        vname = getattr(fn.value, "id", "")
                        mname = getattr(fn, "attr", "")
                        tfqn = (self.var_types_stack[-1] or {}).get(vname)
                        if tfqn and mname:
                            self._add_edge(f"{tfqn}.{mname}", "call", expr)
                    # Fallback for chained call: m1(...).m2() using return types of m1
                    if isinstance(fn, ast.Attribute) and isinstance(getattr(fn, "value", None), ast.Call):
                        base_call = fn.value
                        base_ref = self._name_of_expr(getattr(base_call, "func", None))
                        if base_ref:
                            callee_fqn = self._resolve_any(base_ref) or base_ref
                            # consult local and global return maps
                            rts = getattr(self, "fn_return_types", {}).get(str(callee_fqn), [])
                            if not rts:
                                rts = GLOBAL_FN_RETURN_TYPES.get(str(callee_fqn), [])
                            mname = getattr(fn, "attr", "")
                            for t in rts:
                                if t and t not in {"None", "NoneType"} and mname:
                                    self._add_edge(f"{t}.{mname}", "call", expr)
                # recurse into args/keywords
                for a in list(getattr(expr, "args", []) or []):
                    self._record_callable_uses(a)
                for kw in list(getattr(expr, "keywords", []) or []):
                    val = getattr(kw, "value", None)
                    if val is not None:
                        self._record_callable_uses(val)
            elif isinstance(expr, (ast.Name, ast.Attribute)):
                ref = self._name_of_expr(expr)
                if ref:
                    self._add_edge(self._resolve_any(ref), "value-flow", expr)
            elif isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
                for elt in getattr(expr, "elts", []) or []:
                    self._record_callable_uses(elt)
            elif isinstance(expr, ast.Dict):
                for v in getattr(expr, "values", []) or []:
                    self._record_callable_uses(v)
        except Exception:
            pass

    # --- utilities ---
    def _is_name(self, expr: ast.AST, id_: str) -> bool:
        return isinstance(expr, ast.Name) and expr.id == id_

    def _name_of_expr(self, expr: ast.AST) -> Optional[str]:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            base = self._resolve_attr(expr.value, expr.attr)
            return base
        return None

    def _resolve_any(self, ref: str) -> Optional[str]:
        # ref may be 'a.b' or fully qualified already
        # split head and resolve head through alias/defs
        if ref.startswith("__SUPER__."):
            return ref  # expanded by caller
        parts = ref.split(".")
        if len(parts) == 1:
            return self._resolve_name(ref)
        head, tail = parts[0], parts[1:]
        base = self._resolve_name(head) or self.mod.alias.get(head)
        if base:
            return base + ("." + ".".join(tail) if tail else "")
        return ref  # already qualified or unknown

    def _names_in_type_tuple(self, node: ast.AST) -> List[str]:
        out: List[str] = []
        if isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            n = self._name_of_expr(node)
            if n:
                out.append(n)
        elif isinstance(node, ast.Tuple):
            for e in node.elts:
                out.extend(self._names_in_type_tuple(e))
        return out

    def _refs_in_decorator(self, dec: ast.AST) -> List[str]:
        refs: List[str] = []
        def add_expr(e: ast.AST) -> None:
            n = self._name_of_expr(e)
            if n:
                refs.append(n)
        if isinstance(dec, ast.Call):
            add_expr(dec.func)
            for a in list(getattr(dec, 'args', []) or []):
                add_expr(a)
            for kw in list(getattr(dec, 'keywords', []) or []):
                add_expr(getattr(kw, 'value', None)) if getattr(kw, 'value', None) is not None else None
        else:
            add_expr(dec)
        return refs

    def _type_names_from_annotation(self, ann: ast.AST) -> List[str]:
        """Extract base type names from annotation.
        Supports Optional[T], Union[A,B], and PEP604 A|B best-effort.
        """
        out: List[str] = []
        try:
            if isinstance(ann, ast.Name):
                out.append(ann.id)
            elif isinstance(ann, ast.Attribute):
                n = self._name_of_expr(ann)
                if n:
                    out.append(n)
            elif isinstance(ann, ast.Subscript):
                base = self._name_of_expr(getattr(ann, "value", None))
                sl = getattr(ann, "slice", None)
                items: List[ast.AST] = []
                if isinstance(sl, ast.Tuple):
                    items = list(sl.elts)
                elif sl is not None:
                    items = [sl]
                base_s = base or ""
                if base_s.endswith("Optional"):
                    for it in items[:1]:
                        out.extend(self._type_names_from_annotation(it))
                elif base_s.endswith("Union"):
                    for it in items:
                        out.extend(self._type_names_from_annotation(it))
                else:
                    if base:
                        out.append(base)
            elif hasattr(ast, "BinOp") and isinstance(ann, ast.BinOp) and isinstance(getattr(ann, "op", None), ast.BitOr):
                out.extend(self._type_names_from_annotation(getattr(ann, "left", None)))
                out.extend(self._type_names_from_annotation(getattr(ann, "right", None)))
            elif isinstance(ann, ast.Constant):
                if ann.value is None:
                    out.append("None")
                elif isinstance(ann.value, str) and ann.value.strip():
                    # Forward-referenced annotation like "ExecContext"
                    out.append(str(ann.value).strip())
        except Exception:
            pass
        return out


def _parse_module(file_path: Path, module_fqn: str) -> ModuleInfo:
    mod = ModuleInfo(fqn=module_fqn, path=file_path)
    try:
        src = file_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        return mod
    # gather imports/aliases
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name  # 'a' or 'a.b'
                asname = alias.asname or name.split(".")[0]
                mod.alias[asname] = name
                # add explicit alias edge for path engine
                try:
                    src = f"{module_fqn}.{asname}"
                    dst = name
                    # leave as module/name, later alias-chain rewrite may resolve
                    pass
                finally:
                    # even if resolution fails, keep a best-effort edge
                    edges = getattr(sys.modules.get(__name__), "_tmp_edges_alias", None)  # type: ignore
                    if isinstance(edges, list):
                        edges.append(Edge(src=src, dst=dst, type="alias", file=str(file_path), line=getattr(node, "lineno", 0) or 0))  # type: ignore
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = getattr(node, "level", 0) or 0
            if level > 0:
                # relative import resolution: single dot (level==1) means current package
                cur_parts = module_fqn.split(".")
                if level == 1:
                    base = cur_parts
                else:
                    drop = level - 1
                    base = cur_parts[:-drop] if drop <= len(cur_parts) else []
                if module:
                    module = ".".join([*base, module])
                else:
                    module = ".".join(base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                asname = alias.asname or alias.name
                tgt = f"{module}.{alias.name}" if module else alias.name
                mod.alias[asname] = tgt
                # add alias edge so path engine can see alias transitions
                try:
                    src = f"{module_fqn}.{asname}"
                    dst = tgt
                finally:
                    edges = getattr(sys.modules.get(__name__), "_tmp_edges_alias", None)  # type: ignore
                    if isinstance(edges, list):
                        edges.append(Edge(src=src, dst=dst, type="alias", file=str(file_path), line=getattr(node, "lineno", 0) or 0))  # type: ignore

    # Pre-collect top-level defs so that functions can resolve calls to later-defined siblings
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            mod.defs[node.name] = f"{module_fqn}.{node.name}"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mod.defs[node.name] = f"{module_fqn}.{getattr(node, 'name', '')}"

    # collect defs + edges
    defs: Dict[str, Sym] = {}
    edges: List[Edge] = []
    # scratch pad for import/alias edges discovered before visitor runs
    import sys as _sys  # local alias to avoid pollution
    _sys.modules[__name__].__dict__["_tmp_edges_alias"] = []  # type: ignore
    vis = _SymVisitor(mod, defs, edges)
    vis.visit(tree)
    # merge function return types into global registry
    try:
        local_rt = getattr(vis, "fn_return_types", {}) or {}
        if isinstance(local_rt, dict):
            for k, v in local_rt.items():
                if not isinstance(k, str) or not isinstance(v, list):
                    continue
                cur = GLOBAL_FN_RETURN_TYPES.get(k, [])
                for t in v:
                    if t and t not in cur:
                        cur.append(t)
                GLOBAL_FN_RETURN_TYPES[k] = cur
    except Exception:
        pass
    # merge pre-collected alias edges
    try:
        pre_alias: List[Edge] = _sys.modules[__name__].__dict__.pop("_tmp_edges_alias", [])  # type: ignore
        if pre_alias:
            edges.extend(pre_alias)
    except Exception:
        pass

    # register module-level defs discovered by visitor
    for local, fqn in mod.defs.items():
        if fqn not in defs:
            # created via class/method/func handlers
            pass
    return mod, defs, edges


def _module_public_defs(defs: Dict[str, Sym], module_fqn: str) -> List[str]:
    return [s.fqn for s in defs.values() if s.fqn.startswith(module_fqn + ".") and not s.fqn.split(".")[-1].startswith("_")]


def analyze_dead_code(
    paths: List[str],
    include: List[str],
    exclude: List[str],
    allow_module_export_closure: bool = False,
    include_annotations: bool = False,  # reserved for future
    whitelist_roots: Optional[List[str]] = None,
    protocol_nominal: bool = False,
    protocol_strict_signature: bool = True,
) -> Tuple[Dict[str, Any], int]:
    # Reset global maps for a fresh analysis
    try:
        GLOBAL_FN_RETURN_TYPES.clear()
    except Exception:
        pass
    roots_base = [Path(p) for p in paths]
    files = _collect_py_files(paths, include, exclude)
    tops = _find_top_packages(paths)

    # Scan modules
    modules: Dict[str, ModuleInfo] = {}
    syms: Dict[str, Sym] = {}
    edges: List[Edge] = []
    for f in files:
        mod_fqn = _path_to_module_fqn(f, roots_base)
        if not mod_fqn:
            continue
        mi, defs, e = _parse_module(f, mod_fqn)
        modules[mod_fqn] = mi
        syms.update(defs)
        edges.extend(e)

    # Build global alias map across modules, including re-exports and top-level assignment aliases
    alias_global: Dict[str, str] = {}
    for mod_name, mi in modules.items():
        for local, target in (mi.alias or {}).items():
            if not isinstance(local, str) or not local:
                continue
            left = f"{mod_name}.{local}" if "." not in local else local
            tgt = str(target or "")
            if tgt and "." not in tgt:
                tgt = f"{mod_name}.{tgt}"
            alias_global[left] = tgt

    def _resolve_alias_chain(name: str, limit: int = 10) -> str:
        cur = name
        hops = 0
        while cur in alias_global and hops < limit:
            nxt = alias_global.get(cur)
            if not nxt or nxt == cur:
                break
            cur = nxt
            hops += 1
        return cur

    def _resolve_with_tail(name: str) -> str:
        parts = name.split(".")
        # try longest head match in alias map and preserve tail
        for i in range(len(parts), 0, -1):
            head = ".".join(parts[:i])
            tail = ".".join(parts[i:])
            resolved_head = _resolve_alias_chain(head)
            if resolved_head != head:
                return resolved_head + ("." + tail if tail else "")
        return _resolve_alias_chain(name)

    # Rewrite edge destinations through alias chain, preserving method tails
    for e in edges:
        if isinstance(e.dst, str) and e.dst not in syms:
            resolved = _resolve_with_tail(e.dst)
            if resolved in syms:
                e.dst = resolved

    # Rewrite class base references via alias chain so Protocol/Inheritance checks use canonical FQNs
    for mi in modules.values():
        for cls_local, bases in list((mi.bases or {}).items()):
            resolved_list: List[str] = []
            for b in bases or []:
                rb = _resolve_with_tail(b)
                resolved_list.append(rb)
            mi.bases[cls_local] = resolved_list

    # Roots from top-level package __init__.py exports
    root_syms: Set[str] = set()
    for top_name, top_path in tops.items():
        init_path = top_path / "__init__.py"
        if not init_path.exists():
            continue
        exported = _parse_exports_from_init(init_path)
        # map exported names to FQNs within top package modules
        for name in exported:
            # try resolve to a symbol fqn (class/function) under any module where local name matches
            candidates = [f for f in syms if f.split(".")[0] == top_name and f.split(".")[-1] == name]
            if candidates:
                root_syms.update(candidates)
            else:
                # may be module export
                if allow_module_export_closure:
                    # gather module public defs
                    for mfqn, _mi in modules.items():
                        if mfqn == f"{top_name}.{name}" or mfqn.endswith(f".{name}"):
                            root_syms.update(_module_public_defs(syms, mfqn))

    # Whitelist extra roots
    if whitelist_roots:
        for w in whitelist_roots:
            # exact fqn match or suffix match
            if w in syms:
                root_syms.add(w)
            else:
                for fqn in syms:
                    if fqn.endswith("." + w) or fqn.split(".")[-1] == w:
                        root_syms.add(fqn)

    # Build adjacency with typed edges
    adj_typed: Dict[str, List[Tuple[str, str]]] = {}
    for e in edges:
        if e.dst in syms or (isinstance(e.dst, str) and e.dst):
            adj_typed.setdefault(e.src, []).append((e.type, e.dst))

    # Constructor propagation: calling a Class implies using its __init__ if present
    for s in list(syms.values()):
        if s.kind == "class":
            init_fqn = f"{s.fqn}.__init__"
            if init_fqn in syms:
                adj_typed.setdefault(s.fqn, []).append(("constructor", init_fqn))

    # Identify classes that are directly "used" via direct usage edges (constructors/value-flow/etc.)
    DIRECT_FOR_USED = {
        "call",
        "value-flow",
        "decorator",
        "exception",
        "isinstance",
        "property",
        "return-escape",
        "descriptor",
        "constructor",
    }
    used_classes: Set[str] = set()
    for e in edges:
        if e.type in DIRECT_FOR_USED and e.dst in syms and syms[e.dst].kind == "class":
            used_classes.add(e.dst)

    # Nominal protocol propagation: Port.m -> Impl.m (only if impl class is used)
    if protocol_nominal:
        # Collect protocol classes via 'inherit -> typing.Protocol'
        prot_set: Set[str] = set(
            e.src for e in edges if e.type == "inherit" and isinstance(e.dst, str) and (
                e.dst == "typing.Protocol" or str(e.dst).endswith(".Protocol")
            )
        )
        # Map impl -> set(ports) using inherit edges
        impl_to_ports: Dict[str, Set[str]] = {}
        for e in edges:
            if e.type == "inherit" and isinstance(e.dst, str) and e.dst in prot_set:
                impl_to_ports.setdefault(e.src, set()).add(e.dst)
        # build method name map for ports
        port_methods: Dict[str, Set[str]] = {}
        for sym in syms.values():
            if sym.kind == "method":
                parts = sym.fqn.split(".")
                if len(parts) >= 2:
                    cls = ".".join(parts[:-1])
                    mname = parts[-1]
                    if cls in prot_set:
                        port_methods.setdefault(cls, set()).add(mname)
        # find used port methods (those appearing as dst of any edge)
        used_port_methods: Set[str] = set()
        dsts = {e.dst for e in edges}
        for pm_cls, mnames in port_methods.items():
            for m in mnames:
                fqn = f"{pm_cls}.{m}"
                if fqn in dsts:
                    used_port_methods.add(fqn)
        # propagate to impls by adding protocol-impl edges
        for impl, ports in impl_to_ports.items():
            for p in ports:
                for m in port_methods.get(p, set()):
                    pm_fqn = f"{p}.{m}"
                    if pm_fqn not in used_port_methods:
                        continue
                    impl_m_fqn = f"{impl}.{m}"
                    # require that impl class is directly used
                    if impl not in used_classes:
                        continue
                    if protocol_strict_signature:
                        pm = syms.get(pm_fqn)
                        im = syms.get(impl_m_fqn)
                        if pm and im and pm.arity >= 0 and im.arity >= 0:
                            if not (pm.arity == im.arity or abs(pm.arity - im.arity) == 1):
                                continue
                    if impl_m_fqn in syms:
                        edges.append(
                            Edge(src=pm_fqn, dst=impl_m_fqn, type="protocol-impl", file="", line=0)
                        )
                        adj_typed.setdefault(pm_fqn, []).append(("protocol-impl", impl_m_fqn))

    # Class inheritance override propagation (nominal): Base.m -> Derived.m when Derived overrides m
    # Build base -> derived mapping from resolved bases
    base_to_derived: Dict[str, Set[str]] = {}
    for mod_name, mi in modules.items():
        for cls_local, bases in (mi.bases or {}).items():
            derived_fqn = f"{mod_name}.{cls_local}" if mod_name else cls_local
            for b in bases or []:
                base_to_derived.setdefault(b, set()).add(derived_fqn)
    # Collect used base methods (appear as dst of any edge)
    dsts_set = {e.dst for e in edges}
    # For each base class, find methods and propagate to overrides on derived
    for sym in list(syms.values()):
        if sym.kind != "method":
            continue
        parts = sym.fqn.split(".")
        if len(parts) < 2:
            continue
        base_cls = ".".join(parts[:-1])
        mname = parts[-1]
        base_m_fqn = sym.fqn
        if base_m_fqn not in dsts_set:
            continue  # base method not used; skip
        # For each derived of this base, propagate if override exists and derived class is used
        for drv in base_to_derived.get(base_cls, set()) or []:
            drv_m = f"{drv}.{mname}"
            if drv_m not in syms:
                continue
            if drv not in used_classes:
                continue
            if protocol_strict_signature:
                bm = syms.get(base_m_fqn)
                dm = syms.get(drv_m)
                if bm and dm and bm.arity >= 0 and dm.arity >= 0:
                    if not (bm.arity == dm.arity or abs(bm.arity - dm.arity) == 1):
                        continue
            edges.append(Edge(src=base_m_fqn, dst=drv_m, type="inherit-override", file="", line=0))
            adj_typed.setdefault(base_m_fqn, []).append(("inherit-override", drv_m))

    # Traverse with simple path-policy NFA (two states):
    #   S0: only 'alias' edges allowed (alias*)
    #   S1: after first direct-usage edge, allow {usage, nominal}*
    DIRECT_USAGE = {
        "call",
        "value-flow",
        "decorator",
        "exception",
        "isinstance",
        "property",
        "return-escape",
        "descriptor",
        "constructor",
    }
    NOMINAL = {"inherit-override", "protocol-impl"}

    def _reachable_via_pattern(roots: Set[str]) -> Set[str]:
        reachable_all: Set[Tuple[str, int]] = set()
        out_nodes: Set[str] = set()
        for r in roots:
            stack: List[Tuple[str, int]] = [(r, 1)]  # roots are accepted as reachable; start in S1 for root itself
            visited: Set[Tuple[str, int]] = set()
            while stack:
                node, state = stack.pop()
                if (node, state) in visited:
                    continue
                visited.add((node, state))
                reachable_all.add((node, state))
                out_nodes.add(node)
                for et, nxt in adj_typed.get(node, []) or []:
                    if state == 0:
                        if et == "alias":
                            stack.append((nxt, 0))
                        elif et in DIRECT_USAGE:
                            stack.append((nxt, 1))
                        else:
                            continue
                    else:  # state == 1
                        if et in DIRECT_USAGE or et in NOMINAL or et == "alias":
                            # allow alias even after usage for robustness
                            stack.append((nxt, 1))
        return out_nodes

    reachable = _reachable_via_pattern(root_syms)
    direct: Set[str] = set()  # retained for compatibility if needed

    # Policy closure: exported class -> entire class body
    policy: Set[str] = set()
    exported_classes = {f for f in root_syms if syms.get(f, Sym(f, "", "", 0)).kind == "class"}
    for cls_fqn in exported_classes:
        # include all methods of this class in defs
        prefix = cls_fqn + "."
        for fqn in syms:
            if fqn.startswith(prefix):
                policy.add(fqn)

    alive = reachable | policy | root_syms
    dead = [s for s in syms if s not in alive]

    report: Dict[str, Any] = {
        "version": "1.0",
        "summary": {
            "symbols_total": len(syms),
            "roots": len(root_syms),
            "reachable": len(reachable),
            "policy": len(policy),
            "dead": len(dead),
        },
        "roots": sorted(list(root_syms)),
        "reachable": sorted(list(reachable)),
        "policy": sorted(list(policy)),
        "dead": sorted(dead),
        "nodes": [
            {"fqn": s.fqn, "kind": s.kind, "file": s.file, "line": s.line}
            for s in syms.values()
        ],
        "edges": [e.__dict__ for e in edges if isinstance(e.dst, str) and e.dst],
    }
    return report, len(dead)


def save_dead_code_report(
    paths: List[str],
    include: List[str],
    exclude: List[str],
    output_dir: Path,
    allow_module_export_closure: bool = False,
    include_annotations: bool = False,
    whitelist_roots: Optional[List[str]] = None,
    protocol_nominal: bool = False,
    protocol_strict_signature: bool = True,
) -> Tuple[int, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report, dead_count = analyze_dead_code(
        paths,
        include,
        exclude,
        allow_module_export_closure=allow_module_export_closure,
        include_annotations=include_annotations,
        whitelist_roots=whitelist_roots,
        protocol_nominal=protocol_nominal,
        protocol_strict_signature=protocol_strict_signature,
    )
    out = output_dir / "dead_code.json"
    out.write_text(
        __import__("json").dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return dead_count, out


def explain_usage_path(
    paths: List[str],
    include: List[str],
    exclude: List[str],
    target_fqn: str,
    allow_module_export_closure: bool = False,
    whitelist_roots: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return one root→target explain path under the default path policy.

    The result includes: {found: bool, target: str, root: str|None, path_edges: [Edge-like dicts]}
    """
    report, _ = analyze_dead_code(
        paths=paths,
        include=include,
        exclude=exclude,
        allow_module_export_closure=allow_module_export_closure,
        whitelist_roots=whitelist_roots,
        protocol_nominal=True,
        protocol_strict_signature=True,
    )
    # Build typed adjacency from report edges
    edges = report.get("edges", [])
    nodes = {n.get("fqn") for n in report.get("nodes", [])}
    roots = set(report.get("roots", []) or [])
    adj: Dict[str, List[Tuple[str, str, Dict[str, Any]]]] = {}
    for e in edges:
        src = e.get("src")
        dst = e.get("dst")
        et = e.get("type")
        if not src or not dst or not et:
            continue
        adj.setdefault(src, []).append((et, dst, e))

    DIRECT_USAGE = {
        "call",
        "value-flow",
        "decorator",
        "exception",
        "isinstance",
        "property",
        "return-escape",
        "descriptor",
    }
    NOMINAL = {"inherit-override", "protocol-impl"}

    target = target_fqn
    if target not in nodes:
        # best-effort: permit suffix match
        for n in nodes:
            if n.endswith("." + target) or n.split(".")[-1] == target:
                target = n
                break

    # Product-BFS over (node, state)
    from collections import deque

    for root in roots:
        q = deque()
        q.append((root, 1))  # start in accepted state at root
        prev: Dict[Tuple[str, int], Tuple[Tuple[str, int], Dict[str, Any]]] = {}
        seen: Set[Tuple[str, int]] = set()
        while q:
            node, state = q.popleft()
            if (node, state) in seen:
                continue
            seen.add((node, state))
            if node == target and state == 1:
                # reconstruct
                path_edges: List[Dict[str, Any]] = []
                cur = (node, state)
                while cur in prev:
                    parent, ed = prev[cur]
                    path_edges.append(ed)
                    cur = parent
                path_edges.reverse()
                return {
                    "found": True,
                    "root": root,
                    "target": target,
                    "path_edges": path_edges,
                }
            for et, nxt, ed in adj.get(node, []) or []:
                if state == 0:
                    if et == "alias":
                        ns = (nxt, 0)
                        if ns not in seen:
                            prev[ns] = ((node, state), ed)
                            q.append(ns)
                    elif et in DIRECT_USAGE:
                        ns = (nxt, 1)
                        if ns not in seen:
                            prev[ns] = ((node, state), ed)
                            q.append(ns)
                else:
                    if et in DIRECT_USAGE or et in NOMINAL or et == "alias":
                        ns = (nxt, 1)
                        if ns not in seen:
                            prev[ns] = ((node, state), ed)
                            q.append(ns)
    return {"found": False, "root": None, "target": target_fqn, "path_edges": []}
