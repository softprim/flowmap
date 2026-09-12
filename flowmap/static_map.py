"""
Schelet structural determinist, extras cu modulul `ast` din biblioteca standard.

Produce:
  - noduri: module (fișiere), clase, funcții/metode (cu qualname)
  - muchii "calls": apeluri rezolvate euristic după nume (x() / self.x() / mod.x())
  - muchii "imports": modul -> modul importat din proiect
  - puncte de intrare candidate: `if __name__ == "__main__"`, main(), test_*,
    funcții decorate cu rute web (@app.route, @router.get, @app.get ...)
"""
from __future__ import annotations

import ast
import json
import time
from pathlib import Path
from typing import Any

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".flowmap", "site-packages", ".tox", "build", "dist"}
ROUTE_DECORATORS = {"route", "get", "post", "put", "delete", "patch", "command", "task", "api_view", "websocket"}


def _iter_py_files(root: Path):
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


class _Collector(ast.NodeVisitor):
    def __init__(self, rel: str, module: str):
        self.rel = rel
        self.module = module
        self.scope: list[str] = []
        self.kinds: list[str] = []   # "class" / "function", paralel cu scope
        self.functions: list[dict[str, Any]] = []
        self.classes: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, int]] = []   # (caller qualname, callee name, line)
        self.imports: list[str] = []
        self.entry_points: list[dict[str, Any]] = []

    def _qual(self, name: str) -> str:
        return ".".join([*self.scope, name])

    def visit_Import(self, node):
        for a in node.names:
            self.imports.append(a.name)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.append(("." * node.level) + node.module)

    def visit_ClassDef(self, node):
        q = self._qual(node.name)
        self.classes.append({"qualname": q, "line": node.lineno, "bases": [ast.unparse(b) for b in node.bases]})
        self.scope.append(node.name); self.kinds.append("class")
        self.generic_visit(node)
        self.scope.pop(); self.kinds.pop()

    def _func(self, node):
        q = self._qual(node.name)
        decorators = [ast.unparse(d) for d in node.decorator_list]
        kind = "method" if self.kinds and self.kinds[-1] == "class" else "function"
        self.functions.append({
            "qualname": q, "line": node.lineno, "end_line": node.end_lineno,
            "args": [a.arg for a in node.args.args if a.arg not in ("self", "cls")],
            "kind": kind, "async": isinstance(node, ast.AsyncFunctionDef), "decorators": decorators,
        })
        for d in decorators:
            tail = d.split("(")[0].rsplit(".", 1)[-1]
            if tail in ROUTE_DECORATORS:
                self.entry_points.append({"qualname": q, "reason": f"decorator @{d.split('(')[0]}"})
        if node.name == "main" and not self.scope:
            self.entry_points.append({"qualname": q, "reason": "funcție main()"})
        if node.name.startswith("test_"):
            self.entry_points.append({"qualname": q, "reason": "test pytest"})
        self.scope.append(node.name); self.kinds.append("function")
        self.generic_visit(node)
        self.scope.pop(); self.kinds.pop()

    visit_FunctionDef = _func
    visit_AsyncFunctionDef = _func

    def visit_Call(self, node):
        name = None
        f = node.func
        if isinstance(f, ast.Name):
            name = f.id
        elif isinstance(f, ast.Attribute):
            name = f.attr
        if name:
            caller = ".".join(self.scope) if self.scope else "<module>"
            self.calls.append((caller, name, node.lineno))
        self.generic_visit(node)

    def visit_If(self, node):
        src = ast.unparse(node.test).replace("'", '"')
        if src in ('__name__ == "__main__"', '"__main__" == __name__'):
            self.entry_points.append({"qualname": "<module>", "reason": 'if __name__ == "__main__"'})
        self.generic_visit(node)


def build_static(root: Path) -> dict[str, Any]:
    root = root.resolve()
    modules: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    raw_calls: list[dict[str, Any]] = []
    entry_points: list[dict[str, Any]] = []
    imports: list[dict[str, str]] = []

    for path in _iter_py_files(root):
        rel = str(path.relative_to(root))
        rel = rel.replace("\\", "/")
        modname = rel[:-3].replace("/", ".").removesuffix(".__init__")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=rel)
        except (SyntaxError, UnicodeDecodeError) as e:
            modules.append({"file": rel, "module": modname, "error": str(e)})
            continue
        c = _Collector(rel, modname)
        c.visit(tree)
        modules.append({"file": rel, "module": modname, "lines": len(tree.body)})
        for fn in c.functions:
            functions.append({**fn, "file": rel, "module": modname})
        for cl in c.classes:
            classes.append({**cl, "file": rel, "module": modname})
        for caller, callee, line in c.calls:
            raw_calls.append({"file": rel, "caller": caller, "callee": callee, "line": line})
        for ep in c.entry_points:
            entry_points.append({**ep, "file": rel})
        for imp in c.imports:
            imports.append({"from": modname, "to": imp})

    # rezoluție euristică a apelurilor după numele simplu al funcției
    by_name: dict[str, list[str]] = {}
    for fn in functions:
        by_name.setdefault(fn["qualname"].rsplit(".", 1)[-1], []).append(f'{fn["file"]}::{fn["qualname"]}')
    call_edges: list[dict[str, Any]] = []
    seen = set()
    for rc in raw_calls:
        targets = by_name.get(rc["callee"], [])
        if not targets:
            continue
        # preferă ținta din același fișier, altfel toate candidatele (ambiguu)
        same = [t for t in targets if t.startswith(rc["file"] + "::")]
        for t in same or targets:
            key = (rc["file"], rc["caller"], t)
            if key in seen:
                continue
            seen.add(key)
            call_edges.append({"from": f'{rc["file"]}::{rc["caller"]}', "to": t, "line": rc["line"], "ambiguous": len(same or targets) > 1})

    project_mods = {m["module"] for m in modules}
    import_edges = [e for e in imports if e["to"].lstrip(".") in project_mods or any(e["to"].lstrip(".").startswith(m + ".") for m in project_mods)]

    return {
        "version": 1,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "modules": modules,
        "classes": classes,
        "functions": functions,
        "call_edges": call_edges,
        "import_edges": import_edges,
        "entry_points": entry_points,
    }


def save_static(root: Path, out: Path):
    data = build_static(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data
