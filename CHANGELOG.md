# Changelog

## Nelansat

Reparații găsite la revizia de cod și la rularea pe proiecte reale (tomli, attrs); formatul JSON (versiunea 1) rămâne neschimbat.

- Tracer: se înregistrează și `PY_THROW` (`gen.throw()`/`close()`, `contextmanager.__exit__`, anulare asyncio).
  Fără el, `PY_UNWIND` scotea din stivă înregistrarea altui apel și corupea părinții apelurilor următoare;
  `GeneratorExit` de la `close()` nu mai apare ca excepție.
- Tracer: `sys._getframe` e legat la import (attrs are un test care îl șterge din `sys`); un `__hash__` sau
  `__setattr__` care aruncă orice excepție nu mai poate crăpa callback-urile.
- Schelet static: fișierele sunt parsate ca octeți (BOM UTF-8 și `# -*- coding: ... -*-` acceptate ca de interpretor);
  importurile relative (`from .x import`, `from . import x`) sunt rezolvate față de pachet și apar în `import_edges`.
- Server: handler-ul derivă din `BaseHTTPRequestHandler` (cel vechi servea `HEAD`/fișiere din directorul curent);
  cererile cu alt `Host` decât `127.0.0.1`/`localhost` primesc 403 (apărare contra DNS rebinding);
  portul invalid nu mai lasă un traceback, iar codul de ieșire al lui `serve`/`all` reflectă eroarea.
- CLI: `flowmap slice` nu mai crapă pe Windows când stdout e redirecționat (cp1252) și valorile conțin diacritice.
- CLI, după feedback de la primii utilizatori: `--root`/`--out` acceptate și după subcomandă; calea scriptului se
  rezolvă față de directorul curent, apoi față de `--root`, iar mesajul de „nu găsesc” arată ambele căi încercate;
  avertisment când scriptul e în afara rădăcinii (nu ar fi trasat), când trace-ul iese gol și când opțiuni flowmap
  apar după script (ajung în `sys.argv` al scriptului).
- 14 teste noi: stivă echilibrată la throw/close, `sys._getframe` lipsă, BOM/cookie de codificare, importuri relative,
  `Host` străin și `HEAD`, port invalid, stdout cp1252, căi cu spații și diacritice, proiect fără funcții / trace gol.

## 0.1.0 — 2026-09-12

Prima versiune stabilă.

- Tracer `sys.monitoring` (3.12+): argumente, valori returnate, durată, excepții (origine / propagată / tratată),
  generatoare și corutine, thread-uri, limită de apeluri cu oprire curată, ~5 µs per apel trasat.
- Muchii de date prin amprentarea valorilor (returnat → argument).
- Schelet static `ast`: module, clase, funcții, apeluri rezolvate după nume (cu marcarea ambiguității),
  puncte de intrare (`main`, `__main__`, `test_*`, decoratoare de rute).
- Feliere dinamică (subarbore, felie inversă, felie directă) — în vizualizator și în CLI (`flowmap slice`).
- Vizualizator Cytoscape: grupare pe fișier, axă temporală, cod sursă, mod Structură cu coverage gap,
  temă deschisă/întunecată după sistem.
- Integrare VS Code prin `flowmap init-vscode` (task-uri + Simple Browser).
- 27 de teste (unitare, CLI, server HTTP, integrare browser) și CI pe Linux/Windows/macOS.
