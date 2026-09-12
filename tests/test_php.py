"""Suport PHP: schelet static (php/static.php) și tracer prin instrumentare la include (php/runtime.php).
Necesită `php` 8+ în PATH; altfel testele se sar."""
import json
import os
import shutil
import subprocess
import textwrap

import pytest

from tests.conftest import REPO, run_cli

SHOP_PHP = REPO / "examples" / "shop-php"
PHP = shutil.which("php")
_ver = int(subprocess.run([PHP, "-r", "echo PHP_VERSION_ID;"], capture_output=True, text=True).stdout or 0) if PHP else 0
pytestmark = pytest.mark.skipif(_ver < 80000, reason="php 8+ indisponibil")


def by_func(trace, name):
    return [c for c in trace["calls"] if c["func"] == name]


@pytest.fixture(scope="module")
def shop_php(tmp_path_factory):
    dst = tmp_path_factory.mktemp("shop-php")
    shutil.copytree(SHOP_PHP, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".flowmap*"))
    r = run_cli("--root", str(dst), "static"); assert r.returncode == 0, r.stderr
    r = run_cli("--root", str(dst), "run", "main.php"); assert r.returncode == 0, r.stderr
    assert "32 apeluri" in r.stderr and "FAIL Bogdan: DomainException" in r.stdout
    return dst


@pytest.fixture(scope="module")
def ptrace(shop_php):
    return json.loads((shop_php / ".flowmap" / "trace.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pstatic(shop_php):
    return json.loads((shop_php / ".flowmap" / "static.json").read_text(encoding="utf-8"))


def _project(tmp_path, files: dict[str, str]):
    for name, src in files.items():
        p = tmp_path / name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<?php\n" + textwrap.dedent(src), encoding="utf-8")
    return tmp_path


def _run(root, script="app.php", *args, extra=()):
    r = run_cli("--root", str(root), *extra, "run", script, *args)
    tf = root / ".flowmap" / "trace.json"
    return r, (json.loads(tf.read_text(encoding="utf-8")) if tf.exists() else None)


# ---------- schelet static ----------
def test_php_static_skeleton(pstatic):
    fns = {f["qualname"]: f for f in pstatic["functions"]}
    assert {"process", "main", "Shop\\Order::add", "Shop\\Order::__construct", "Shop\\applyDiscount", "Shop\\getProduct"} <= set(fns)
    assert fns["Shop\\Order::add"]["kind"] == "method" and fns["Shop\\Order::add"]["args"] == ["sku", "qty"]
    assert fns["Shop\\applyDiscount"]["kind"] == "function" and fns["Shop\\applyDiscount"]["end_line"] > fns["Shop\\applyDiscount"]["line"]
    assert [c["qualname"] for c in pstatic["classes"]] == ["Shop\\Order"]
    edges = {(e["from"], e["to"]) for e in pstatic["call_edges"]}
    assert ("main.php::process", "src/Order.php::Shop\\Order::__construct") in edges       # new Order(...)
    assert ("main.php::process", "src/Order.php::Shop\\Order::add") in edges
    assert ("src/Order.php::Shop\\buildInvoice", "src/Pricing.php::Shop\\applyDiscount") in edges
    assert ("main.php::<module>", "main.php::main") in edges
    assert {(e["from"], e["to"]) for e in pstatic["import_edges"]} == {("main", "src.Order"), ("src.Order", "src.Catalog"), ("src.Order", "src.Pricing")}
    assert {(e["qualname"], e["reason"]) for e in pstatic["entry_points"]} == {("main", "funcție main()"), ("<module>", "cod la nivel de fișier")}
    assert all("error" not in m for m in pstatic["modules"])


def test_php_static_routes_tests_syntax_errors_and_vendor(tmp_path):
    _project(tmp_path, {
        "src/Api.php": """
            namespace App;
            use Symfony\\Component\\Routing\\Attribute\\Route;
            class Api extends Base implements \\JsonSerializable {
                #[Route('/x', methods: ['GET'])]
                public function show(int $id): array { return $this->helper($id); }
                private function helper($x) { return [$x]; }
                public static function make(): static { return new static(); }
                abstract public function nothing();
            }
            interface Base { public function show(int $id): array; }
        """,
        "tests/ApiTest.php": "namespace Tests;\nclass ApiTest extends \\PHPUnit\\Framework\\TestCase {\n    public function testShow(): void { }\n}\n",
        "broken.php": "function (:\n",
        "vendor/lib/x.php": "function vendored() {}\n",
    })
    s = json.loads(run_cli("--root", str(tmp_path), "static").stdout or (tmp_path / ".flowmap" / "static.json").read_text(encoding="utf-8"))
    assert any(m["file"] == "broken.php" and "error" in m for m in s["modules"])
    assert not any(f["file"].startswith("vendor") for f in s["functions"])
    assert {(e["qualname"], e["reason"]) for e in s["entry_points"]} == {("App\\Api::show", "atribut #[Route]"), ("Tests\\ApiTest::testShow", "test PHPUnit")}
    cls = {c["qualname"]: c for c in s["classes"]}
    assert cls["App\\Api"]["bases"] == ["Base", "JsonSerializable"]
    show = [e for e in s["call_edges"] if e["from"] == "src/Api.php::App\\Api::show"]
    assert [e["to"] for e in show] == ["src/Api.php::App\\Api::helper"] and not show[0]["ambiguous"]
    assert {f["qualname"] for f in s["functions"] if f["file"] == "src/Api.php"} == {"App\\Api::show", "App\\Api::helper", "App\\Api::make", "App\\Api::nothing", "App\\Base::show"}


# ---------- tracer ----------
def test_php_call_tree_values_and_exceptions(ptrace):
    calls = ptrace["calls"]
    assert ptrace["version"] == 1 and ptrace["overflow"] is False and ptrace.get("language") == "php"
    assert calls[0]["func"] == "main" and calls[0]["parent"] is None and calls[0]["args"] == {} and calls[0]["ret"] == "null"
    procs = by_func(ptrace, "process")
    assert len(procs) == 3 and all(p["parent"] == 0 for p in procs)
    assert procs[0]["args"] == {"customer": "'Ana'", "items": "[['SKU-100', 3], ['SKU-200', 1]]", "code": "'WELCOME10'"}
    assert [d["ret"] for d in by_func(ptrace, "Shop\\applyDiscount")] == ["69.75", "-31.5"]
    assert by_func(ptrace, "Shop\\addVat")[0]["args"] == {"total": "69.75"}          # parametrul cu valoare implicită neprimit nu apare
    assert "self" not in by_func(ptrace, "Shop\\Order::add")[0]["args"] and "this" not in by_func(ptrace, "Shop\\Order::add")[0]["args"]
    assert all(c["t1"] is not None and c["t1"] >= c["t0"] for c in calls)
    v = by_func(ptrace, "Shop\\validateInvoice")[1]
    assert v["exc"] == {"type": "DomainException", "msg": "'total negativ pe factură: -37.49'", "origin": True}
    p = procs[1]
    assert p["exc"]["type"] == "DomainException" and p["exc"]["origin"] is False and p["exc"]["handled"] is True
    add = [c for c in by_func(ptrace, "Shop\\Order::add") if c["exc"]]
    assert len(add) == 1 and add[0]["exc"]["type"] == "RuntimeException" and add[0]["exc"]["origin"] is True
    assert by_func(ptrace, "Shop\\buildInvoice")[0]["args"]["order"] == "<Shop\\Order>"


def test_php_data_edges_follow_returned_values(ptrace):
    calls = ptrace["calls"]
    chain = {(calls[e["from"]]["func"], calls[e["to"]]["func"], e["via"]) for e in ptrace["data_edges"]}
    assert {("Shop\\Order::subtotal", "Shop\\applyDiscount", "total"), ("Shop\\applyDiscount", "Shop\\addVat", "total"),
            ("Shop\\buildInvoice", "Shop\\validateInvoice", "invoice"), ("Shop\\getProduct", "Shop\\inStock", "product")} <= chain
    assert all(calls[e["to"]]["parent"] != e["from"] for e in ptrace["data_edges"])


def test_php_slice_cli(shop_php):
    r = run_cli("--root", str(shop_php), "slice", "26", "--direction", "backward")
    assert r.returncode == 0, r.stderr
    assert "Shop\\applyDiscount(total=18.5, code='FIX50') -> -31.5" in r.stdout and "!! DomainException" in r.stdout
    assert "Shop\\Order::add" not in r.stdout


def test_php_instrumenter_edge_cases(tmp_path):
    root = _project(tmp_path, {"app.php": """
        function void_return(int $x): void { if ($x > 0) { return; } echo "x"; }
        function &by_ref(array &$a) { $a[] = 1; return $a; }
        function with_closure(array $a): array {
            $f = function ($x) { return $x * 2; };
            return array_map(fn($y) => $f($y) + 1, array_map(function ($v) { return $v; }, $a));
        }
        function gen(int $n): Generator { for ($i = 0; $i < $n; $i++) { yield $i; } return "done"; }
        function interp(string $name, ...$rest): string { $x = ['k' => 'v']; return "hi {$x['k']} $name " . count($rest); }
        class C {
            public static function make(int $n = 5): static { return new static(); }
            public function m(): int { return 7; }
        }
        function vendored_user() { require_once __DIR__ . '/vendor/lib.php'; return vendored(3); }
        void_return(1);
        $arr = [0]; by_ref($arr);
        with_closure([1, 2]);
        foreach (gen(3) as $v) {}
        interp('ana', 1, 2, 3);
        C::make()->m();
        vendored_user();
        echo "ARGV:" . implode(",", array_slice($argv, 1)) . "\\n";
    """, "vendor/lib.php": "function vendored($x) { return $x + 1; }\n"})
    r, t = _run(root, "app.php", "a", "b")
    assert r.returncode == 0, r.stderr
    assert "ARGV:a,b" in r.stdout                                              # argumentele scriptului ajung în $argv
    funcs = [c["func"] for c in t["calls"]]
    assert "{closure}" not in " ".join(funcs) and "vendored" not in funcs      # închiderile și vendor/ nu se trasează
    f = {c["func"]: c for c in t["calls"]}
    assert f["void_return"]["ret"] == "null" and f["void_return"]["args"] == {"x": "1"}
    assert "by_ref" not in f          # funcțiile cu return prin referință nu se trasează, dar rulează neschimbate
    assert f["with_closure"]["ret"] == "[3, 5]"                                 # return-urile din închideri au rămas ale lor
    assert f["gen"]["ret"] == "'done'" and funcs.count("gen") == 1             # generatorul: un singur apel
    assert f["interp"]["ret"] == "'hi v ana 3'" and f["interp"]["args"] == {"name": "'ana'", "rest": "[1, 2, 3]"}
    assert f["C::make"]["ret"] == "<C>" and f["C::make"]["args"] == {} and f["C::m"]["ret"] == "7"
    assert f["vendored_user"]["ret"] == "4"
    assert f["C::m"]["parent"] is None and all(c["t1"] is not None for c in t["calls"])


def test_php_uncaught_exception_and_overflow(tmp_path):
    root = _project(tmp_path, {"app.php": """
        function inner() { throw new LogicException("boom"); }
        function outer() { return inner(); }
        for ($i = 0; $i < 50; $i++) { strlen("x"); }
        outer();
    """})
    r, t = _run(root)
    assert r.returncode != 0 and t is not None                                  # trace-ul se scrie și la excepție netratată
    assert [(c["func"], c["exc"]["type"], c["exc"]["origin"]) for c in t["calls"]] == [("outer", "LogicException", False), ("inner", "LogicException", True)]
    root2 = _project(tmp_path / "two", {"app.php": "function f($i) { return $i; }\nfor ($i = 0; $i < 500; $i++) { f($i); }\necho 'done';\n"})
    r, t = _run(root2, "app.php", extra=("--out", ".flowmap"))
    r = run_cli("--root", str(root2), "run", "--max-calls", "100", "app.php")
    t = json.loads((root2 / ".flowmap" / "trace.json").read_text(encoding="utf-8"))
    assert r.returncode == 0 and "done" in r.stdout and t["overflow"] is True and len(t["calls"]) == 100


def test_php_missing_binary_is_reported(tmp_path):
    (tmp_path / "a.php").write_text("<?php function f() {}\n", encoding="utf-8")
    env = {**os.environ, "FLOWMAP_PHP": str(tmp_path / "nu-exista-php")}
    r = subprocess.run([__import__("sys").executable, "-m", "flowmap", "--root", str(tmp_path), "run", "a.php"], capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "nu pot rula" in r.stderr
    r = subprocess.run([__import__("sys").executable, "-m", "flowmap", "--root", str(tmp_path), "static"], capture_output=True, text=True, env=env)
    assert r.returncode == 0
    s = json.loads((tmp_path / ".flowmap" / "static.json").read_text(encoding="utf-8"))
    assert s["modules"][0]["file"] == "a.php" and "error" in s["modules"][0]


def test_mixed_python_and_php_project(tmp_path):
    (tmp_path / "tool.py").write_text("def helper(): return 1\n", encoding="utf-8")
    (tmp_path / "web.php").write_text("<?php function helper() { return 2; }\nfunction page() { return helper(); }\n", encoding="utf-8")
    assert run_cli("--root", str(tmp_path), "static").returncode == 0
    s = json.loads((tmp_path / ".flowmap" / "static.json").read_text(encoding="utf-8"))
    assert {(f["file"], f["qualname"]) for f in s["functions"]} == {("tool.py", "helper"), ("web.php", "helper"), ("web.php", "page")}
    page = [e for e in s["call_edges"] if e["from"] == "web.php::page"]
    assert page == [{"from": "web.php::page", "to": "web.php::helper", "line": 2, "ambiguous": False}]   # preferă același fișier
