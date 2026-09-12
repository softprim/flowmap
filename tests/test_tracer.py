import json
import sys
import textwrap
from pathlib import Path

import pytest

from flowmap.tracer import Tracer, _fingerprint, _safe_repr, run_traced

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring")


def by_func(trace, name):
    return [c for c in trace["calls"] if c["func"] == name]


# ---------- demo project ----------
def test_call_tree_and_values(trace):
    calls = trace["calls"]
    assert trace["version"] == 1 and trace["overflow"] is False
    assert calls[0]["func"] == "main" and calls[0]["parent"] is None
    procs = by_func(trace, "process")
    assert len(procs) == 3 and all(p["parent"] == 0 for p in procs)
    disc = by_func(trace, "apply_discount")
    assert [d["ret"] for d in disc] == ["69.75", "-31.5"]
    assert disc[0]["args"] == {"total": "77.5", "code": "'WELCOME10'"}
    assert all(c["t1"] is not None and c["t1"] >= c["t0"] for c in calls)


def test_exception_origin_propagation_handled(trace):
    v = by_func(trace, "validate_invoice")[1]
    assert v["exc"] == {"type": "AssertionError", "msg": _safe_repr("total negativ pe factură: -37.48"), "origin": True}
    p = by_func(trace, "process")[1]
    assert p["exc"]["origin"] is False and p["exc"]["handled"] is True
    add = [c for c in by_func(trace, "Order.add") if c["exc"]]
    assert len(add) == 1 and add[0]["exc"]["type"] == "RuntimeError" and add[0]["exc"]["origin"]


def test_data_edges_follow_returned_values(trace):
    calls = trace["calls"]
    chain = [(calls[e["from"]]["func"], calls[e["to"]]["func"], e["via"]) for e in trace["data_edges"]]
    assert ("Order.subtotal", "apply_discount", "total") in chain
    assert ("apply_discount", "add_vat", "total") in chain
    assert ("build_invoice", "validate_invoice", "invoice") in chain
    assert ("get_product", "in_stock", "product") in chain
    # nu apar muchii părinte -> copil deghizate în date
    assert all(calls[e["to"]]["parent"] != e["from"] for e in trace["data_edges"])


def test_self_is_not_repr_ed(trace):
    init = by_func(trace, "Order.__init__")[0]
    assert init["args"]["self"] == "<Order>"


# ---------- unit ----------
def test_fingerprint_rules():
    assert _fingerprint(None) is None and _fingerprint(True) is None
    assert _fingerprint(5) is None and _fingerprint(5000) == "i:5000"
    assert _fingerprint("abc") is None and _fingerprint("abcd") == _fingerprint("abcd")
    assert _fingerprint(1.0) is None and _fingerprint(2.5) == "f:2.5"
    lst = [1, 2]
    assert _fingerprint(lst) == f"o:{id(lst)}" and _fingerprint([1, 2]) != _fingerprint(lst)
    assert _fingerprint((1, [2])).startswith("o:")  # tuple nehashabil


def test_safe_repr_survives_broken_repr():
    class Bad:
        def __repr__(self):
            raise RuntimeError("nope")
    assert _safe_repr(Bad()) == "<Bad>"
    assert len(_safe_repr("x" * 1000)) == 120


def _project(tmp_path: Path, src: str) -> Path:
    (tmp_path / "app.py").write_text(textwrap.dedent(src), encoding="utf-8")
    return tmp_path


def _run(root: Path, max_calls=200_000):
    out = root / ".flowmap" / "trace.json"
    code = run_traced(root, "app.py", [], False, out, max_calls=max_calls)
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_generators_async_recursion_balanced(tmp_path):
    root = _project(tmp_path, """
        import asyncio
        def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)
        def gen(n):
            for i in range(n):
                if i == 3: raise ValueError("boom")
                yield i
        def consume():
            try:
                return list(gen(5))
            except ValueError:
                return []
        async def work(x):
            await asyncio.sleep(0); return x + 1
        async def amain(): return await asyncio.gather(*(work(i) for i in range(3)))
        fib(10); consume(); asyncio.run(amain())
    """)
    code, t = _run(root)
    assert code == 0
    assert all(c["t1"] is not None for c in t["calls"])
    assert len([c for c in t["calls"] if c["func"] == "fib"]) == 177
    gens = [c for c in t["calls"] if c["func"] == "gen"]
    assert gens and gens[-1]["exc"]["origin"] is True
    assert not any(c["exc"] and c["exc"]["type"] == "StopIteration" for c in t["calls"])
    assert {c["func"] for c in t["calls"]} >= {"work", "amain", "consume"}


def test_threads_have_independent_stacks(tmp_path):
    root = _project(tmp_path, """
        import threading
        def leaf(x): return x * 2
        def worker(i):
            for _ in range(50): leaf(i)
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        [t.start() for t in ts]; [t.join() for t in ts]
    """)
    code, t = _run(root)
    assert code == 0
    workers = [c for c in t["calls"] if c["func"] == "worker"]
    assert len(workers) == 4 and all(w["parent"] is None for w in workers)
    for leaf in (c for c in t["calls"] if c["func"] == "leaf"):
        assert t["calls"][leaf["parent"]]["thread"] == leaf["thread"]


def test_overflow_stops_cleanly(tmp_path):
    root = _project(tmp_path, """
        def f(i): return i
        for i in range(500): f(i)
        print("done")
    """)
    code, t = _run(root, max_calls=100)
    assert code == 0 and t["overflow"] is True and len(t["calls"]) == 100
    assert all(c["t1"] is not None for c in t["calls"])


def test_varargs_and_kwargs_captured(tmp_path):
    root = _project(tmp_path, """
        def f(a, *rest, **opts): return a
        f(1, 2, 3, x=4)
    """)
    _, t = _run(root)
    assert t["calls"][0]["args"] == {"a": "1", "rest": "(2, 3)", "opts": "{'x': 4}"}


def test_uncaught_exception_still_saves_trace(tmp_path):
    root = _project(tmp_path, """
        def boom(): raise KeyError("k")
        boom()
    """)
    code, t = _run(root)
    assert code == 1 and t["calls"][0]["exc"]["type"] == "KeyError" and t["calls"][0]["exc"]["origin"]


def test_library_and_venv_code_is_excluded(tmp_path):
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "vendored.py").write_text("def hidden(): return 1\n")
    root = _project(tmp_path, """
        import json, sys
        sys.path.insert(0, ".venv/lib")
        from vendored import hidden
        def visible(): return json.dumps({"a": hidden()})
        visible()
    """)
    _, t = _run(root)
    assert {c["func"] for c in t["calls"]} == {"visible"}


def test_tracer_context_manager_and_tool_id_reuse(tmp_path):
    def f(): return 1
    with Tracer(tmp_path) as tr:
        f()
    with Tracer(tmp_path) as tr2:  # al doilea start nu trebuie să dea "tool id in use"
        f()
    assert tr._tool_id is None and tr2._tool_id is None


def test_sibling_directory_with_same_prefix_is_excluded(tmp_path):
    root = tmp_path / "proj"; sib = tmp_path / "proj2"
    root.mkdir(); sib.mkdir()
    (sib / "other.py").write_text("def outside(): return 1\n")
    _project(root, """
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "proj2"))
        from other import outside
        def inside(): return outside()
        inside()
    """)
    _, t = _run(root)
    assert {c["func"] for c in t["calls"]} == {"inside"}
