"""CLI: python -m flowmap <comandă>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="flowmap", description="Hartă vizuală a execuției și a fluxului de date (Python 3.12+)")
    from . import __version__
    p.add_argument("--version", action="version", version=f"flowmap {__version__}")
    p.add_argument("--root", default=".", help="rădăcina proiectului (implicit: directorul curent)")
    p.add_argument("--out", default=".flowmap", help="directorul de ieșire (implicit: .flowmap)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("static", help="extrage scheletul static (module, funcții, apeluri, puncte de intrare)")

    r = sub.add_parser("run", help="rulează un script sub tracer și salvează trace-ul")
    r.add_argument("target", help="script.py sau, cu -m, numele modulului (ex: -m pytest)")
    r.add_argument("-m", dest="as_module", action="store_true", help="rulează ca modul")
    r.add_argument("--max-calls", type=int, default=None, help="limită de apeluri înregistrate (implicit 200000)")
    r.add_argument("args", nargs=argparse.REMAINDER, help="argumente pentru script")

    sl = sub.add_parser("slice", help="afișează în terminal felia unui apel din trace")
    sl.add_argument("call_id", type=int, help="id-ul apelului (vezi #id în vizualizator)")
    sl.add_argument("--direction", choices=["backward", "forward", "both"], default="both")

    v = sub.add_parser("serve", help="pornește vizualizatorul local")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--open", action="store_true", help="deschide în browser")

    a = sub.add_parser("all", help="static + run + serve, într-un singur pas (opțiunile înaintea scriptului: flowmap all --open main.py)")
    a.add_argument("target")
    a.add_argument("-m", dest="as_module", action="store_true")
    a.add_argument("--port", type=int, default=8765)
    a.add_argument("--open", action="store_true")
    a.add_argument("args", nargs=argparse.REMAINDER)

    sub.add_parser("init-vscode", help="scrie .vscode/tasks.json cu task-urile flowmap în proiectul curent")

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
        serve(out, ns.port, ns.open)
        return 0

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
        save_static(root, out / "static.json")
        run_traced(root, ns.target, script_args, ns.as_module, out / "trace.json")
        serve(out, ns.port, ns.open)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
