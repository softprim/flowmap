"""
Tracer de runtime bazat pe sys.monitoring (Python 3.12+).

Interceptează, doar pentru fișierele din proiect:
  - intrarea într-o funcție (argumentele efective)
  - ieșirea din funcție (valoarea returnată)
  - excepțiile ridicate (origine) și propagate (unwind), plus dacă au fost tratate

Pentru fiecare valoare se calculează o "amprentă" (fingerprint). Dacă valoarea
returnată de apelul A apare ulterior ca argument al apelului B, se deduce o
muchie de date A -> B. Asta este baza felierii dinamice.

Formatul trace-ului (versiunea 1):
  {"version": 1, "root": str, "generated_at": str, "overflow": bool,
   "calls": [ {id, parent, thread, func, file, line, t0, t1, args, ret, exc} ],
   "data_edges": [ {from, to, via} ]}
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

TRACE_VERSION = 1
# legat la import: programul trasat poate șterge sys._getframe (attrs are un test care face exact asta)
_getframe = sys._getframe
_PKG_DIR = str(Path(__file__).resolve().parent)
MAX_REPR = 120
DEFAULT_MAX_CALLS = 200_000    # protecție împotriva exploziei de trace
_CONTROL_FLOW_EXC = (StopIteration, StopAsyncIteration, GeneratorExit)
_SKIP_PARTS = {"site-packages", "dist-packages", ".venv", "venv", "__pycache__", ".flowmap", "node_modules"}


def _safe_repr(value: Any) -> str:
    try:
        r = repr(value)
    except Exception:  # noqa: BLE001  (repr-ul utilizatorului poate arunca orice)
        r = f"<{type(value).__name__}>"
    if len(r) > MAX_REPR:
        r = r[: MAX_REPR - 1] + "…"
    return r


_IMMUTABLE = (int, float, str, bytes, bool, type(None), tuple, frozenset)


def _fingerprint(value: Any) -> str | None:
    """Amprentă stabilă pentru urmărirea unei valori între apeluri.

    - obiectele mutabile (liste, dict-uri, instanțe) se urmăresc după identitate
    - valorile imutabile se urmăresc după tip + conținut, dar nu cele triviale
      (None, bool, întregi mici, șiruri scurte) care ar produce legături false
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"i:{value}" if abs(value) > 100 else None
    if isinstance(value, float):
        return f"f:{value!r}" if value not in (0.0, 1.0) else None
    if isinstance(value, str):
        return f"s:{hash(value)}" if len(value) >= 4 else None
    if isinstance(value, _IMMUTABLE):
        try:
            return f"{type(value).__name__}:{hash(value)}"
        except Exception:  # noqa: BLE001  tuple cu conținut nehashabil sau __hash__ care aruncă orice
            return f"o:{id(value)}"
    return f"o:{id(value)}"


def _path_parts(filename: str) -> set[str]:
    return set(filename.replace("\\", "/").split("/"))


class Tracer:
    """Un tracer per proces. Stivele de apeluri sunt per thread; înregistrările sunt globale."""

    def __init__(self, root: Path, exclude: tuple[str, ...] = (), max_calls: int = DEFAULT_MAX_CALLS):
        self.root = root.resolve()
        self._root_str = str(self.root)
        self._root_prefix = self._root_str.rstrip(os.sep) + os.sep   # evită potrivirea cu /home/x/proiect2
        self.exclude = tuple(str((self.root / e).resolve()) + os.sep for e in exclude)
        self.max_calls = max_calls
        self.calls: list[dict[str, Any]] = []
        self._local = threading.local()
        self._lock = threading.Lock()
        self.t0 = time.perf_counter()
        self.overflow = False
        self._code_cache: dict[Any, bool] = {}
        self._meta_cache: dict[Any, tuple[str, tuple[str, ...]]] = {}  # code -> (fișier relativ, nume argumente)
        self._tool_id: int | None = None

    # ---- filtrare ---------------------------------------------------------
    def _in_project(self, code) -> bool:
        hit = self._code_cache.get(code)
        if hit is not None:
            return hit
        fn = code.co_filename
        ok = (
            bool(code.co_flags & inspect.CO_OPTIMIZED)  # exclude corpul modulelor și al claselor
            and fn.startswith(self._root_prefix)
            and not fn.startswith(_PKG_DIR + os.sep)
            and not (_path_parts(fn) & _SKIP_PARTS)
            and not any(fn.startswith(e) for e in self.exclude)
            and not code.co_name.startswith("<")  # <lambda>, <genexpr>, <listcomp>
        )
        self._code_cache[code] = ok
        return ok

    def _rel(self, filename: str) -> str:
        try:
            return Path(filename).relative_to(self.root).as_posix()
        except ValueError:
            return filename

    def _meta(self, code) -> tuple[str, tuple[str, ...]]:
        """Calculat o singură dată per funcție: Path.relative_to costă ~20 µs, un apel trasat ~2 µs."""
        m = self._meta_cache.get(code)
        if m is None:
            n_named = code.co_argcount + code.co_kwonlyargcount
            names = list(code.co_varnames[:n_named])
            if code.co_flags & inspect.CO_VARARGS:
                names.append(code.co_varnames[n_named])
            if code.co_flags & inspect.CO_VARKEYWORDS:
                names.append(code.co_varnames[n_named + (1 if code.co_flags & inspect.CO_VARARGS else 0)])
            m = self._meta_cache[code] = (self._rel(code.co_filename), tuple(names))
        return m

    @property
    def _stack(self) -> list[int]:
        st = getattr(self._local, "stack", None)
        if st is None:
            st = self._local.stack = []
        return st

    # ---- callback-uri -----------------------------------------------------
    def _on_start(self, code, instruction_offset):
        if not self._in_project(code):
            return sys.monitoring.DISABLE
        self._push(code, _getframe(1).f_locals)
        return None

    def _on_throw(self, code, instruction_offset, exception):
        # gen.throw()/close(), contextmanager.__exit__, anulare asyncio: generatorul e reluat cu o excepție.
        # Fără acest segment, PY_UNWIND-ul care urmează ar scoate din stivă înregistrarea altui apel.
        if self._in_project(code):  # PY_THROW nu poate fi dezactivat local
            self._push(code, _getframe(1).f_locals)

    def _push(self, code, f_locals):
        if self.overflow:
            return
        rel, names = self._meta(code)
        args: dict[str, str] = {}
        fps: dict[str, str] = {}
        for name in names:
            if name not in f_locals:
                continue
            v = f_locals[name]
            args[name] = f"<{type(v).__name__}>" if name in ("self", "cls") else _safe_repr(v)
            fp = _fingerprint(v)
            if fp:
                fps[name] = fp
        stack = self._stack
        with self._lock:
            if len(self.calls) >= self.max_calls:
                self.overflow = True
                self._disable()
                return
            cid = len(self.calls)
            self.calls.append({
                "id": cid,
                "parent": stack[-1] if stack else None,
                "thread": threading.get_ident(),
                "func": code.co_qualname,
                "file": rel,
                "line": code.co_firstlineno,
                "t0": round((time.perf_counter() - self.t0) * 1000, 3),
                "t1": None,
                "args": args,
                "arg_fp": fps,
                "ret": None,
                "ret_fp": None,
                "exc": None,
            })
        stack.append(cid)

    def _pop(self) -> dict[str, Any] | None:
        stack = self._stack
        if not stack:
            return None
        rec = self.calls[stack.pop()]
        rec["t1"] = round((time.perf_counter() - self.t0) * 1000, 3)
        return rec

    def _on_return(self, code, instruction_offset, retval):
        if not self._in_project(code):
            return sys.monitoring.DISABLE
        rec = self._pop()
        if rec is None:
            return None
        rec["ret"] = _safe_repr(retval)
        rec["ret_fp"] = _fingerprint(retval)
        if rec["exc"]:  # a ridicat/primit o excepție dar a returnat normal => a tratat-o
            rec["exc"]["handled"] = True
        return None

    def _on_unwind(self, code, instruction_offset, exception):
        if not self._in_project(code):  # PY_UNWIND/RAISE nu pot fi dezactivate local
            return
        rec = self._pop()
        if rec is None or isinstance(exception, GeneratorExit):  # close() pe un generator nu e o eroare
            return
        if rec["exc"] is None:  # propagată dintr-un apel copil, nu ridicată aici
            rec["exc"] = {"type": type(exception).__name__, "msg": _safe_repr(str(exception)), "origin": False}

    def _on_raise(self, code, instruction_offset, exception):
        if not self._in_project(code) or isinstance(exception, _CONTROL_FLOW_EXC):
            return
        stack = self._stack
        if not stack:
            return
        rec = self.calls[stack[-1]]
        # marchez obiectul excepției: la a doua apariție (propagare în alt frame) nu mai e origine
        origin = not getattr(exception, "_flowmap_seen", False)
        try:
            exception._flowmap_seen = True
        except Exception:  # noqa: BLE001  __slots__, __setattr__ personalizat
            pass
        if rec["exc"] is None:
            rec["exc"] = {"type": type(exception).__name__, "msg": _safe_repr(str(exception)), "origin": origin}

    # ---- activare ---------------------------------------------------------
    def start(self):
        mon = sys.monitoring
        for tid in (3, 4, 5, 2, 1):
            try:
                mon.use_tool_id(tid, "flowmap")
                self._tool_id = tid
                break
            except ValueError:
                continue
        if self._tool_id is None:
            raise RuntimeError("toate id-urile sys.monitoring sunt ocupate (alt profiler/debugger activ)")
        E = mon.events
        tid = self._tool_id
        mon.register_callback(tid, E.PY_START, self._on_start)
        mon.register_callback(tid, E.PY_RETURN, self._on_return)
        mon.register_callback(tid, E.PY_UNWIND, self._on_unwind)
        mon.register_callback(tid, E.RAISE, self._on_raise)
        # generatoare / corutine: fiecare segment între resume și yield devine un apel separat
        mon.register_callback(tid, E.PY_RESUME, self._on_start)
        mon.register_callback(tid, E.PY_YIELD, self._on_return)
        mon.register_callback(tid, E.PY_THROW, self._on_throw)
        mon.set_events(tid, E.PY_START | E.PY_RETURN | E.PY_UNWIND | E.RAISE | E.PY_RESUME | E.PY_YIELD | E.PY_THROW)

    def _disable(self):
        if self._tool_id is not None:
            sys.monitoring.set_events(self._tool_id, 0)

    def stop(self):
        if self._tool_id is None:
            return
        self._disable()
        sys.monitoring.free_tool_id(self._tool_id)
        self._tool_id = None
        now = round((time.perf_counter() - self.t0) * 1000, 3)
        for rec in self.calls:
            if rec["t1"] is None:
                rec["t1"] = now

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    # ---- export -----------------------------------------------------------
    def build(self) -> dict[str, Any]:
        """Derivă muchiile de date: producător (ret_fp) -> consumator (arg_fp)."""
        producers: dict[str, int] = {}
        data_edges: list[dict[str, Any]] = []
        for rec in self.calls:
            for arg, fp in rec["arg_fp"].items():
                src = producers.get(fp)
                if src is not None and src != rec["id"] and src != rec["parent"]:
                    data_edges.append({"from": src, "to": rec["id"], "via": arg})
            if rec["ret_fp"]:
                producers[rec["ret_fp"]] = rec["id"]
        public = [{k: v for k, v in rec.items() if k not in ("arg_fp", "ret_fp")} for rec in self.calls]
        return {
            "version": TRACE_VERSION,
            "root": self._root_str,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "overflow": self.overflow,
            "calls": public,
            "data_edges": data_edges,
        }

    def save(self, out: Path) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.build(), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out)  # scriere atomică: vizualizatorul nu vede un JSON pe jumătate
        return out


def run_traced(root: Path, target: str, argv: list[str], as_module: bool, out: Path,
               max_calls: int = DEFAULT_MAX_CALLS) -> int:
    """Rulează un script/modul sub tracer și scrie trace-ul la final (chiar și la excepție)."""
    import runpy

    root = root.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)
    if not as_module:
        target = str((root / target).resolve()) if not Path(target).is_absolute() else target
        if not Path(target).exists():
            print(f"[flowmap] nu găsesc scriptul {target}", file=sys.stderr)
            return 2
    tracer = Tracer(root, max_calls=max_calls)
    old_argv = sys.argv
    sys.argv = [target, *argv]
    code = 0
    tracer.start()
    try:
        if as_module:
            runpy.run_module(target, run_name="__main__", alter_sys=True)
        else:
            runpy.run_path(target, run_name="__main__")
    except SystemExit as e:  # pytest / argparse
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except KeyboardInterrupt:
        code = 130
        print("[flowmap] întrerupt; salvez ce s-a înregistrat", file=sys.stderr)
    except BaseException as e:  # noqa: BLE001
        code = 1
        print(f"[flowmap] execuția s-a oprit cu {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        tracer.stop()
        sys.argv = old_argv
        tracer.save(out)
        n = len(tracer.calls)
        print(f"[flowmap] {n} apeluri înregistrate -> {out}" + (" (TRUNCHIAT la limită)" if tracer.overflow else ""), file=sys.stderr)
    return code
