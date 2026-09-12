import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SHOP = REPO / "examples" / "shop"


def run_cli(*args, cwd=None, timeout=60):
    return subprocess.run([sys.executable, "-m", "flowmap", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="session")
def shop(tmp_path_factory):
    """Copie a proiectului demo cu static.json + trace.json generate o singură dată."""
    dst = tmp_path_factory.mktemp("shop")
    shutil.copytree(SHOP, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".flowmap*", "__pycache__", ".pytest_cache"))
    r = run_cli("--root", str(dst), "static"); assert r.returncode == 0, r.stderr
    r = run_cli("--root", str(dst), "run", "main.py"); assert r.returncode == 0, r.stderr
    return dst


@pytest.fixture(scope="session")
def trace(shop):
    return json.loads((shop / ".flowmap" / "trace.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def static(shop):
    return json.loads((shop / ".flowmap" / "static.json").read_text(encoding="utf-8"))
