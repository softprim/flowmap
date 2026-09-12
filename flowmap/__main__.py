"""CLI: python -m flowmap <comandă>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _tolerant_stdio():
    """Windows: stdout/stderr redirecționate (task VS Code, CI, pipe) folosesc cp1252, iar textele CLI-ului,
    valorile trasate și ieșirea programului trasat conțin diacritice. Nu schimbăm codificarea, doar nu mai crăpăm."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


_FLOWMAP_OPTIONS = ("--root", "--out", "--max-calls", "--port", "--open")


def _warn_options_after_script(script_args: list[str]) -> None:
    """`flowmap run main.py --root .` trimite `--root .` scriptului, nu flowmap-ului; spunem asta explicit."""
    found = []
    for i, a in enumerate(script_args):
        if a.split("=")[0] in _FLOWMAP_OPTIONS:
            found.append(a)
            if "=" not in a and a != "--open" and i + 1 < len(script_args) and not script_args[i + 1].startswith("-"):
                found.append(script_args[i + 1])   # și valoarea, ca sugestia să fie completă
    if found:
        print(f"[flowmap] atenție: {' '.join(found)} apare după script, deci ajunge în sys.argv al scriptului, nu la flowmap."
              f" Opțiunile flowmap se pun înaintea scriptului: flowmap run {' '.join(found)} script.py", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    _tolerant_stdio()
    p = argparse.ArgumentParser(prog="flowmap", description="Hartă vizuală a execuției și a fluxului de date (Python 3.12+)",
                                epilog="Opțiunile --root/--out pot sta oriunde înaintea scriptului: `flowmap run --root proiect main.py`."
                                       " Tot ce urmează după script ajunge la script.")
    from . import __version__
    p.add_argument("--version", action="version", version=f"flowmap {__version__}")
    p.add_argument("--root", default=".", help="rădăcina proiectului (implicit: directorul curent)")
    p.add_argument("--out", default=".flowmap", help="directorul de ieșire (implicit: .flowmap)")
    # aceleași opțiuni acceptate și după subcomandă (`flowmap run --root x main.py`); SUPPRESS: nu suprascriu valoarea globală dacă lipsesc
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--out", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("static", parents=[common], help="extrage scheletul static (module, funcții, apeluri, puncte de intrare)")

    r = sub.add_parser("run", parents=[common], help="rulează un script sub tracer și salvează trace-ul")
    r.add_argument("target", help="script.py (față de directorul curent) sau, cu -m, numele modulului (ex: -m pytest)")
    r.add_argument("-m", dest="as_module", action="store_true", help="rulează ca modul")
    r.add_argument("--max-calls", type=int, default=None, help="limită de apeluri înregistrate (implicit 200000)")
    r.add_argument("args", nargs=argparse.REMAINDER, help="argumente pentru script (tot ce urmează după script)")

    sl = sub.add_parser("slice", parents=[common], help="afișează în terminal felia unui apel din trace")
    sl.add_argument("call_id", type=int, help="id-ul apelului (vezi #id în vizualizator)")
    sl.add_argument("--direction", choices=["backward", "forward", "both"], default="both")

    v = sub.add_parser("serve", parents=[common], help="pornește vizualizatorul local")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--open", action="store_true", help="deschide în browser")

    a = sub.add_parser("all", parents=[common], help="static + run + serve, într-un singur pas (opțiunile înaintea scriptului: flowmap all --open main.py)")
    a.add_argument("target")
    a.add_argument("-m", dest="as_module", action="store_true")
    a.add_argument("--port", type=int, default=8765)
    a.add_argument("--open", action="store_true")
    a.add_argument("args", nargs=argparse.REMAINDER)

    sub.add_parser("init-vscode", parents=[common], help="scrie .vscode/tasks.json cu task-urile flowmap în proiectul curent")

    ns = p.parse_args(argv)
    root = Path(ns.root).resolve()
    out = (root / ns.out) if not Path(ns.out).is_absolute() else Path(ns.out)

    if sys.version_info < (3, 12) and ns.cmd in ("run", "all"):
        print("[flowmap] tracer-ul necesită Python 3.12+ (sys.monitoring)", file=sys.stderr)
        return 2

    if ns.cmd == "init-vscode":
        import shutil
        tpl = Path(__file__).parent / "templates" / "tasks.json"
        dst = root / ".vscode" / "tasks.json"
        if dst.exists():
            print(f"[flowmap] {dst} există deja — îl las neatins; copiază manual task-urile din {tpl}", file=sys.stderr)
            return 1
        dst.parent.mkdir(exist_ok=True)
        shutil.copy(tpl, dst)
        print(f"[flowmap] scris {dst}. În VS Code: Ctrl+Shift+B rulează fișierul curent sub tracer; apoi Ctrl+Shift+P → „Simple Browser: Show” → http://127.0.0.1:8765", file=sys.stderr)
        return 0

    if ns.cmd == "static":
        from .static_map import save_static
        d = save_static(root, out / "static.json")
        print(f"[flowmap] {len(d['modules'])} module, {len(d['functions'])} funcții, {len(d['call_edges'])} apeluri, {len(d['entry_points'])} puncte de intrare -> {out/'static.json'}", file=sys.stderr)
        return 0

    if ns.cmd == "run":
        from .tracer import DEFAULT_MAX_CALLS, run_traced
        _warn_options_after_script(ns.args)
        return run_traced(root, ns.target, ns.args, ns.as_module, out / "trace.json", ns.max_calls or DEFAULT_MAX_CALLS)

    if ns.cmd == "slice":
        import json
        from . import slicer
        tf = out / "trace.json"
        if not tf.exists():
            print(f"[flowmap] lipsește {tf}; rulează întâi `flowmap run`", file=sys.stderr)
            return 2
        t = json.loads(tf.read_text(encoding="utf-8"))
        if not 0 <= ns.call_id < len(t["calls"]):
            print(f"[flowmap] id de apel invalid (trace-ul are {len(t['calls'])} apeluri)", file=sys.stderr)
            return 2
        fn = {"backward": slicer.backward_slice, "forward": slicer.forward_slice, "both": slicer.full_slice}[ns.direction]
        print(slicer.describe(t, fn(t, ns.call_id)))
        return 0

    if ns.cmd == "serve":
        from .server import serve
        return serve(out, ns.port, ns.open)

    if ns.cmd == "all":
        from .static_map import save_static
        from .tracer import run_traced
        from .server import serve
        # toleranță: `flowmap all main.py --open` pune --open în argumentele scriptului; îl recuperăm
        script_args = list(ns.args)
        if "--open" in script_args:
            script_args.remove("--open"); ns.open = True
        if "--port" in script_args:
            i = script_args.index("--port")
            if i + 1 < len(script_args) and script_args[i + 1].isdigit():
                ns.port = int(script_args[i + 1]); del script_args[i : i + 2]
        _warn_options_after_script(script_args)
        save_static(root, out / "static.json")
        run_traced(root, ns.target, script_args, ns.as_module, out / "trace.json")
        return serve(out, ns.port, ns.open)
    return 1


if __name__ == "__main__":
    sys.exit(main())
