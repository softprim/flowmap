import json
import shutil
import subprocess
import sys
import time
import urllib.request

from tests.conftest import SHOP


def test_all_recovers_flags_after_script(tmp_path):
    shutil.copytree(SHOP, tmp_path / "shop", ignore=shutil.ignore_patterns(".flowmap*", "__pycache__"))
    proc = subprocess.Popen([sys.executable, "-m", "flowmap", "--root", str(tmp_path / "shop"), "all", "main.py", "--port", "8791"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(50):
            try:
                body = urllib.request.urlopen("http://127.0.0.1:8791/api/trace", timeout=1).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            raise AssertionError("serverul nu a pornit pe 8791: " + proc.stderr.read())
        assert len(json.loads(body)["calls"]) == 32
    finally:
        proc.terminate(); proc.wait(timeout=10)
