"""Server HTTP local minimal: servește vizualizatorul și fișierele JSON din .flowmap/."""
from __future__ import annotations

import json
import sys
import webbrowser
from urllib.parse import parse_qs, urlsplit
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VIEWER = Path(__file__).parent / "viewer" / "index.html"


def make_handler(data_dir: Path):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *a):  # liniște în terminalul VS Code
            pass

        def _send(self, body: bytes, ctype: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                self._route()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # noqa: BLE001
                self._send(f"eroare internă: {type(e).__name__}: {e}".encode(), "text/plain; charset=utf-8", 500)

        def _route(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(VIEWER.read_bytes(), "text/html; charset=utf-8")
            if path in ("/api/trace", "/api/static"):
                f = data_dir / (path.rsplit("/", 1)[-1] + ".json")
                if not f.exists():
                    return self._send(json.dumps({"error": f"lipsește {f.name}"}).encode(), "application/json", 404)
                return self._send(f.read_bytes(), "application/json; charset=utf-8")
            if path == "/api/source":
                rel = parse_qs(urlsplit(self.path).query).get("file", [""])[0]
                root = Path(json.loads((data_dir / "static.json").read_text())["root"]) if (data_dir / "static.json").exists() else data_dir.parent
                target = (root / rel).resolve()
                if not rel or not target.is_relative_to(root.resolve()) or not target.is_file():
                    return self._send(b"not found", "text/plain", 404)
                return self._send(target.read_bytes(), "text/plain; charset=utf-8")
            return self._send(b"not found", "text/plain", 404)
    return Handler


def serve(data_dir: Path, port: int, open_browser: bool):
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(data_dir))
    except OSError as e:
        print(f"[flowmap] nu pot porni pe portul {port} ({e.strerror}); alege altul cu --port", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{port}/"
    print(f"[flowmap] vizualizator: {url}  (date din {data_dir})")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
