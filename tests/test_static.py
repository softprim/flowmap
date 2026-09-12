import textwrap

from flowmap.static_map import build_static


def test_shop_static(static):
    names = {f["qualname"] for f in static["functions"]}
    assert {"apply_discount", "Order.add", "build_invoice", "test_line_total"} <= names
    kinds = {f["qualname"]: f["kind"] for f in static["functions"]}
    assert kinds["Order.add"] == "method" and kinds["build_invoice"] == "function"
    eps = {(e["file"], e["qualname"], e["reason"]) for e in static["entry_points"]}
    assert ("main.py", "main", "funcție main()") in eps
    assert ("main.py", "<module>", 'if __name__ == "__main__"') in eps
    assert any(q == "test_line_total" for _, q, _ in eps)
    edges = {(e["from"], e["to"]) for e in static["call_edges"]}
    assert ("shop/orders.py::build_invoice", "shop/pricing.py::apply_discount") in edges
    assert ("main.py::process", "shop/orders.py::build_invoice") in edges
    assert {m["module"] for m in static["modules"]} >= {"main", "shop.orders", "shop"}


def test_ambiguous_calls_syntax_errors_and_routes(tmp_path):
    (tmp_path / "a.py").write_text(textwrap.dedent("""
        from fastapi import FastAPI
        app = FastAPI()
        def helper(): return 1
        @app.get("/x")
        def route(): return helper()
        class C:
            def helper(self): return 2
            def m(self): return self.helper()
    """))
    (tmp_path / "b.py").write_text("def helper(): return 3\ndef use(): return helper()\n")
    (tmp_path / "broken.py").write_text("def (:\n")
    (tmp_path / "node_modules").mkdir(); (tmp_path / "node_modules" / "x.py").write_text("def skipped(): pass\n")
    s = build_static(tmp_path)
    assert any(m["file"] == "broken.py" and "error" in m for m in s["modules"])
    assert not any(f["file"].startswith("node_modules") for f in s["functions"])
    assert {(e["qualname"], e["reason"]) for e in s["entry_points"]} == {("route", "decorator @app.get")}
    # route -> helper: același fișier are două candidate (helper, C.helper) => ambiguu
    amb = [e for e in s["call_edges"] if e["from"] == "a.py::route"]
    assert {e["to"] for e in amb} == {"a.py::helper", "a.py::C.helper"} and all(e["ambiguous"] for e in amb)
    # b.use -> b.helper: preferă ținta din același fișier, neambiguu
    use = [e for e in s["call_edges"] if e["from"] == "b.py::use"]
    assert use == [{"from": "b.py::use", "to": "b.py::helper", "line": 2, "ambiguous": False}]


def test_bom_and_coding_cookie_are_parsed(tmp_path):
    """Ca interpretorul: BOM UTF-8 și `# -*- coding: latin-1 -*-` sunt acceptate; octeții invalizi nu pierd fișierul."""
    (tmp_path / "bom.py").write_bytes(b"\xef\xbb\xbfdef with_bom():\n    return 1\n")
    (tmp_path / "latin.py").write_bytes(b"# -*- coding: latin-1 -*-\nX = 'caf\xe9'\ndef latin():\n    return X\n")
    (tmp_path / "raw.py").write_bytes(b"def raw():\n    return '\xff\xfe'\n")
    s = build_static(tmp_path)
    assert not any("error" in m for m in s["modules"]), s["modules"]
    assert {f["qualname"] for f in s["functions"]} == {"with_bom", "latin", "raw"}


def test_relative_imports_are_resolved(tmp_path, static):
    edges = {(e["from"], e["to"]) for e in static["import_edges"]}
    assert {("shop.orders", "shop.catalog"), ("shop.orders", "shop.pricing"), ("main", "shop.orders")} <= edges
    pkg = tmp_path / "pkg"; sub = pkg / "sub"
    sub.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from . import a\n")
    (pkg / "a.py").write_text("def fa(): pass\n")
    (pkg / "b.py").write_text("from .a import fa\n")
    (sub / "__init__.py").write_text("")
    (sub / "c.py").write_text("from ..a import fa\nfrom .. import b\nfrom . import missing\n")
    s = build_static(tmp_path)
    assert {(e["from"], e["to"]) for e in s["import_edges"]} == {("pkg", "pkg.a"), ("pkg.b", "pkg.a"), ("pkg.sub.c", "pkg.a"), ("pkg.sub.c", "pkg.b"), ("pkg.sub.c", "pkg"), ("pkg.sub.c", "pkg.sub")}
