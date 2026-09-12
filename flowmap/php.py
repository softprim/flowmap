"""
Suport PHP: scheletul static și tracer-ul sunt scrise în PHP (flowmap/php/*.php, fără extensii, PHP 8.0+)
și produc exact aceleași fișiere JSON ca variantele Python. Aici doar le lansăm cu binarul `php`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PHP_DIR = Path(__file__).resolve().parent / "php"


def find_php() -> str | None:
    """Binarul php: FLOWMAP_PHP dacă e setat, altfel `php` din PATH."""
    return os.environ.get("FLOWMAP_PHP") or shutil.which("php")


def _php_cmd(php: str, script: str, *args: str) -> list[str]:
    return [php, "-d", "opcache.enable_cli=0", str(PHP_DIR / script), *args]   # opcache ar ocoli instrumentarea la include


def static_php(root: Path, files: list[Path]) -> dict[str, Any]:
    """Scheletul static al fișierelor PHP date; {"error": ...} dacă php lipsește sau crapă."""
    php = find_php()
    if not php:
        return {"error": "php nu e în PATH (instalează PHP 8+ sau setează FLOWMAP_PHP)"}
    payload = {"root": str(root), "files": [{"path": str(p), "rel": p.relative_to(root).as_posix()} for p in files]}
    try:
        r = subprocess.run(_php_cmd(php, "static.php"), input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": f"nu pot rula {php}: {e}"}
    if r.returncode != 0:
        return {"error": f"static.php a eșuat: {r.stderr.strip()[-300:]}"}
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        return {"error": f"static.php a produs JSON invalid: {e}"}


def run_traced_php(root: Path, script: Path, argv: list[str], out: Path, max_calls: int) -> int:
    """Rulează scriptul PHP sub tracer (bootstrap.php) și întoarce codul de ieșire al lui php."""
    php = find_php()
    if not php:
        print("[flowmap] php nu e în PATH (instalează PHP 8+ sau setează FLOWMAP_PHP)", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = _php_cmd(php, "bootstrap.php", str(root), str(out), str(max_calls), str(script), *argv)
    try:
        code = subprocess.call(cmd)   # stdin/stdout/stderr moștenite: programul trasat vorbește direct cu terminalul
    except OSError as e:
        print(f"[flowmap] nu pot rula {php}: {e}", file=sys.stderr)
        return 2
    if not out.exists():
        print("[flowmap] tracer-ul PHP nu a scris trace-ul (php a ieșit înainte de bootstrap?)", file=sys.stderr)
        return code or 1
    try:
        n = len(json.loads(out.read_text(encoding="utf-8"))["calls"])
    except (ValueError, KeyError, OSError):
        n = -1
    if n == 0:
        print(f"[flowmap] nicio funcție definită sub {root} nu a fost apelată. Verifică --root (rădăcina proiectului,"
              f" implicit directorul curent) și că scriptul apelează funcții din proiect.", file=sys.stderr)
    return code
