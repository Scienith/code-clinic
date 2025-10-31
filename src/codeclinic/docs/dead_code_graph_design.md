Dead Code Analysis: Graph + Path Query Design

Status: proposal (implemented partially)

Goals
- Unify all “usage” into a single symbol graph built from AST.
- Decide “is used?” by reachability from roots under edge-type constraints (a path pattern), not hardcoded heuristics.
- Keep dynamic behavior off by default; recover common patterns via pluggable extractors (registry constructor, dispatch tables, etc.).

Symbols and Edges
- Node: { fqn, kind [module|class|function|method|alias], file, line }
- Edge (typed):
  - call: f(), Cls(), obj.m()
  - value-flow: passing a callable reference as an argument/default/factory; references inside containers
  - decorator: wrapper -> dec, wrapper -> dec-arg
  - exception: raise/except/assert -> Error
  - isinstance: isinstance/issubclass -> Type
  - property/descriptor: property(fget,fset,fdel); Class.field = Descriptor(...)
  - return-escape: returning inner def/class
  - inherit-override: Base.m -> Derived.m when method overridden (nominal)
  - protocol-impl: Port.m -> Impl.m (typing.Protocol nominal only; strict arity)
  - alias: Alias -> Target (top-level assign + import re-export; includes function-scope imports)
  - (optional) class-member / module-member: structural closure edges (policy)

Roots and Reachability
- Roots = top-level package __init__.__all__ exports + whitelist.
- Used iff reachable from any root by a path matching an allowed edge pattern.
- Default pattern: alias* followed by one or more direct-usage edges
  - Direct usage edges = {call, value-flow, decorator, exception, isinstance, property, return-escape}
  - Policy edges are restricted to the start (class/module member closure), configurable.

Path Pattern Engine
- Define edge-type regex-like DSL, e.g.: `alias* (call|value-flow|decorator|exception|isinstance|property|return-escape)+`
- Compile to NFA; perform product-BFS over (GraphNode, NFAState) to answer reachability and extract the first explain path.
- This keeps the core simple, extensible, and testable.

Extractors (plugins)
- Implement each edge family as an extractor over AST nodes:
  - Calls + nested constructors in containers (list/tuple/dict)
  - Function-scope Import/ImportFrom → local alias map
  - Re-export alias (recursive) + relative import `level` semantics (single dot = current package)
  - Attribute resolution priority: local alias > module alias > explicit ClassName > self/cls (current class) > super()
  - Registry constructor (e.g., NodeExecutorRegistry([...])): optional plugin that treats the list items as used
  - Dispatch tables (literal dict): optional plugin that treats values as used call targets

Nominal Propagation
- Inherit-override: Base.m used → Derived.m used if overridden (strict arity, ignore self/cls).
- Protocol-impl: Port.m used → Impl.m used for nominal implementers only (strict arity), no structural matching.

Dynamic Behavior
- We do not chase dynamic imports/strings by default.
- Provide whitelist and inline allow tags as safety valves.
- Optional typed hints integration (future): consume mypy JSON for limited receiver type hints to reduce false negatives.

NetworkX (optional)
- Keep the core BFS bespoke. NetworkX can be used for explain/SCC/exports:
  - shortest_path for path explanation (if installed); export GEXF/GraphML for external tools.
  - strongly_connected_components for mutual-keep clusters.

CLI/QA Outputs
- Artifacts: dead_code.json {summary, roots, reachable, policy, dead, nodes, edges}
- summary.json (minimal): only enabled + failed gates with detail paths
- Explain path (future): `codeclinic qa run --explain <fqn>` returns one root→fqn path

Roadmap
1) Solidify current extractors (done/ongoing):
   - Function-scope import aliases, recursive nested constructor detection, alias chain resolution
   - Value-flow for callable references
   - Nominal protocol/override propagation
2) Add registry constructor & dispatch-table plugins; add explain path
3) Optional typed hints integration (mypy JSON) for receiver resolution

Non-goals
- Full dynamic resolution (importlib/eval/complex reflection).
- Structural Protocol matching by default.

