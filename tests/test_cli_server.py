import json
import subprocess
import sys
import threading
import urllib.error
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


def _serve(data_dir):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(data_dir))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _status(req):
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code


def test_server_rejects_foreign_host_and_head(shop):
    """DNS rebinding: un site extern nu trebuie să poată citi sursa prin browserul utilizatorului.
    HEAD/GET pe fișiere din directorul curent (moștenire SimpleHTTPRequestHandler) nu trebuie servite."""
    httpd, base = _serve(shop / ".flowmap")
    try:
        assert _status(urllib.request.Request(base + "/api/trace", headers={"Host": "evil.example"})) == 403
        assert _status(urllib.request.Request(base + "/api/trace", headers={"Host": "127.0.0.1.evil.example:80"})) == 403
        for host in ("127.0.0.1:1", "localhost", "LOCALHOST:8765", "[::1]:8765"):
            assert _status(urllib.request.Request(base + "/api/trace", headers={"Host": host})) == 200, host
        assert _status(urllib.request.Request(base + "/pyproject.toml", method="HEAD")) != 200
        assert _status(urllib.request.Request(base + "/", method="HEAD")) != 200
    finally:
        httpd.shutdown()


def test_serve_invalid_port_exit_code(shop):
    r = run_cli("--root", str(shop), "serve", "--port", "70000")
    assert r.returncode == 1 and "nu pot porni" in r.stderr


def test_cli_slice_survives_cp1252_stdout(shop):
    """Pe Windows, stdout redirecționat (task VS Code, CI) e cp1252; valorile trasate conțin diacritice."""
    import os
    r = subprocess.run([sys.executable, "-m", "flowmap", "--root", str(shop), "slice", "26", "--direction", "backward"],
                       capture_output=True, text=True, encoding="cp1252", env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0, r.stderr
    assert "apply_discount(total=18.5, code='FIX50') -> -31.5" in r.stdout and "AssertionError" in r.stdout


def test_paths_with_spaces_and_diacritics(tmp_path):
    root = tmp_path / "proiect cu spații și ăâî"
    (root / "pachet ă").mkdir(parents=True)
    (root / "pachet ă" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pachet ă" / "modul.py").write_text("def calc(x):\n    return x * 2\n", encoding="utf-8")
    (root / "main.py").write_text("import importlib\nm = importlib.import_module('pachet ă.modul')\nprint(m.calc(21))\n", encoding="utf-8")
    assert run_cli("--root", str(root), "static").returncode == 0
    r = run_cli("--root", str(root), "run", "main.py")
    assert r.returncode == 0 and "42" in r.stdout, r.stderr
    t = json.loads((root / ".flowmap" / "trace.json").read_text(encoding="utf-8"))
    assert [(c["func"], c["file"]) for c in t["calls"]] == [("calc", "pachet ă/modul.py")]
    httpd, base = _serve(root / ".flowmap")
    try:
        from urllib.parse import quote
        assert b"def calc" in urllib.request.urlopen(base + "/api/source?file=" + quote("pachet ă/modul.py")).read()
    finally:
        httpd.shutdown()


def test_project_without_functions_and_empty_trace(tmp_path):
    (tmp_path / "script.py").write_text("print('doar cod la nivel de modul')\n")
    r = run_cli("--root", str(tmp_path), "static"); assert r.returncode == 0
    s = json.loads((tmp_path / ".flowmap" / "static.json").read_text(encoding="utf-8"))
    assert s["functions"] == [] and s["call_edges"] == [] and [m["file"] for m in s["modules"]] == ["script.py"]
    r = run_cli("--root", str(tmp_path), "run", "script.py"); assert r.returncode == 0 and "0 apeluri" in r.stderr
    t = json.loads((tmp_path / ".flowmap" / "trace.json").read_text(encoding="utf-8"))
    assert t["version"] == 1 and t["calls"] == [] and t["data_edges"] == [] and t["overflow"] is False
    r = run_cli("--root", str(tmp_path), "slice", "0")
    assert r.returncode == 2 and "0 apeluri" in r.stderr
    httpd, base = _serve(tmp_path / ".flowmap")
    try:
        assert json.loads(urllib.request.urlopen(base + "/api/trace").read())["calls"] == []
    finally:
        httpd.shutdown()
