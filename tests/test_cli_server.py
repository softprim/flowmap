import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from flowmap.server import make_handler
from tests.conftest import run_cli


def test_cli_help_and_missing_script(tmp_path):
    assert run_cli("--help").returncode == 0
    r = run_cli("--root", str(tmp_path), "run", "nope.py")
    assert r.returncode == 2 and "nu găsesc" in r.stderr


def test_cli_pytest_mode(shop):
    r = run_cli("--root", str(shop), "--out", ".fm-tests", "run", "-m", "pytest", "-q", "tests")
    assert r.returncode == 1  # un test pică intenționat
    t = json.loads((shop / ".fm-tests" / "trace.json").read_text(encoding="utf-8"))
    assert {c["func"] for c in t["calls"]} == {"test_line_total", "test_welcome_discount", "test_fixed_discount_never_negative", "line_total", "apply_discount"}


def test_cli_slice(shop):
    r = run_cli("--root", str(shop), "slice", "26", "--direction", "backward")
    assert r.returncode == 0 and "apply_discount" in r.stdout
    assert run_cli("--root", str(shop), "slice", "99999").returncode == 2


def test_init_vscode(tmp_path):
    assert run_cli("--root", str(tmp_path), "init-vscode").returncode == 0
    tasks = json.loads((tmp_path / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    assert {t["label"] for t in tasks["tasks"]} >= {"flowmap: rulează fișierul curent", "flowmap: vizualizator (http://127.0.0.1:8765)"}
    assert run_cli("--root", str(tmp_path), "init-vscode").returncode == 1  # nu suprascrie


def test_server_endpoints(shop):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(shop / ".flowmap"))
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True); th.start()
    try:
        get = lambda p: urllib.request.urlopen(f"http://127.0.0.1:{port}{p}")
        assert b"<title>flowmap</title>" in get("/").read()
        assert json.loads(get("/api/trace").read())["version"] == 1
        assert "modules" in json.loads(get("/api/static").read())
        assert b"def apply_discount" in get("/api/source?file=shop%2Fpricing.py").read()
        for bad in ("/api/source?file=..%2F..%2Fetc%2Fpasswd", "/api/source?file=", "/nope"):
            try:
                get(bad); assert False, bad
            except urllib.error.HTTPError as e:
                assert e.code == 404
    finally:
        httpd.shutdown()
