# Changelog

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
