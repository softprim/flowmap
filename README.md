# flowmap

[![CI](https://github.com/softprim/flowmap/actions/workflows/ci.yml/badge.svg)](https://github.com/softprim/flowmap/actions/workflows/ci.yml)

Hartă vizuală a execuției și a fluxului de date pentru proiecte Python și PHP, cu feliere dinamică,
gândită să fie folosită din VS Code. Prototip pentru lucrarea de licență
„Cartografierea vizuală a execuției software și analiza dinamică a fluxului de date”.

Fără dependențe externe în Python (doar biblioteca standard, Python 3.12+). Pentru proiecte PHP e nevoie doar de
binarul `php` (8.0+), fără extensii. Vizualizatorul e un singur fișier HTML care folosește Cytoscape.js de pe CDN.

## Ce face

| Nivel | Modul | Ce produce |
|---|---|---|
| Schelet static | `flowmap/static_map.py` (`ast`), `flowmap/php/static.php` (`token_get_all`) | module, clase, funcții, apeluri rezolvate după nume, puncte de intrare (`main`, `__main__`, `test_*`, decoratoare/atribute de rute, cod la nivel de fișier) → `.flowmap/static.json` |
| Instrumentare | `flowmap/tracer.py` (`sys.monitoring`), `flowmap/php/runtime.php` (instrumentare la `include`) | fiecare apel din proiect: argumente, valoare returnată, durată, excepții (origine vs. propagare vs. tratată) + muchii de date (valoare returnată de A → argument al lui B) → `.flowmap/trace.json` |
| Vizualizare + feliere | `flowmap/viewer/index.html` | graf pe fișiere, felierea unei tranzacții, felia inversă/directă a unui apel concret, axă temporală, cod sursă |

Muchiile de date se deduc prin *amprentarea valorilor*: obiectele mutabile după identitate,
valorile imutabile după conținut (cu excepția celor triviale: `None`, boolean, întregi mici, șiruri scurte,
ca să nu apară legături false). Nu e taint analysis completă — e o aproximare ieftină care
funcționează bine pe fluxuri „return → argument”.

## Instalare

```bash
pip install git+https://github.com/softprim/flowmap.git
# sau, din clonă: pip install -e ".[test]" && python -m pytest
```

## Folosire din VS Code

1. Deschide proiectul tău în VS Code și rulează o dată:
   ```bash
   python -m flowmap init-vscode
   ```
   Asta scrie `.vscode/tasks.json` cu patru task-uri.
2. Deschide fișierul pe care vrei să-l urmărești și apasă **Ctrl+Shift+B**
   („flowmap: rulează fișierul curent”). Se extrage scheletul static și se rulează fișierul sub tracer.
   Pentru teste: **Ctrl+Shift+P → Tasks: Run Task → flowmap: rulează testele (pytest)**.
3. Vizualizatorul pornește singur la deschiderea folderului (task cu `runOn: folderOpen`; VS Code
   îți cere o dată permisiunea). Dacă nu, rulează task-ul „flowmap: vizualizator”.
4. **Ctrl+Shift+P → Simple Browser: Show → `http://127.0.0.1:8765`**. Poți trage tab-ul lângă editor.
   După fiecare rulare nouă apasă **Reîncarcă** în vizualizator.

Sugestie de scurtătură (Preferences → Keyboard Shortcuts → JSON):
```json
{ "key": "ctrl+alt+f", "command": "simpleBrowser.show", "args": "http://127.0.0.1:8765" }
```

## PHP

Aceleași comenzi, cu un script `.php` în loc de `.py`:

```bash
cd examples/shop-php && python -m flowmap all --open main.php
python -m flowmap run public/index.php          # sau vendor/bin/phpunit tests, orice script PHP
```

Cum funcționează: `flowmap run` pornește `php` cu `flowmap/php/bootstrap.php`, care înlocuiește stream wrapper-ul
`file://` și rescrie, la `include`/`require`, fiecare funcție și metodă din proiect (nu din `vendor/`) într-o formă
echivalentă care raportează intrarea, argumentele, valoarea returnată și excepțiile. Numerotarea liniilor nu se
schimbă, deci mesajele de eroare și stack trace-urile rămân corecte. Nu e nevoie de Xdebug sau de altă extensie;
OPcache e dezactivat pentru acel proces. Scheletul static vine din `token_get_all`. Formatul JSON e identic cu cel
din Python, așa că vizualizatorul, felierea și `flowmap slice` funcționează neschimbate; un proiect poate conține
ambele limbaje.

Limitări PHP: închiderile (`function () {}`, `fn() =>`) și funcțiile care returnează prin referință (`function &f`)
nu sunt trasate; generatoarele apar ca un singur apel; `$this` nu apare între argumente; fișierele sunt
instrumentate în memorie, deci overhead-ul la prima includere e vizibil pe proiecte mari.

## Folosire din terminal

```bash
python -m flowmap static                      # schelet static
python -m flowmap run main.py --arg1 x        # rulează scriptul sub tracer
python -m flowmap run -m pytest -q tests      # sau suita de teste
python -m flowmap slice 26 --direction backward   # felia unui apel, în terminal
python -m flowmap serve --open                # vizualizator
python -m flowmap all --open main.py          # toate trei (opțiunile flowmap înaintea scriptului)
```
Toate comenzile acceptă `--root <dir>` (rădăcina proiectului, implicit directorul curent) și `--out <dir>`
(implicit `.flowmap`), înainte sau după subcomandă: `flowmap run --root proiect main.py`.

Regula pentru `run` și `all`: **tot ce urmează după script ajunge la script**, în `sys.argv`. Opțiunile flowmap
(`--root`, `--out`, `--max-calls`, `--port`, `--open`) se pun înaintea scriptului; dacă apar după el, flowmap
avertizează. Calea scriptului se rezolvă ca în shell, față de directorul curent, apoi față de `--root`.
Se trasează doar codul de sub `--root`: dacă scriptul e în altă parte sau trace-ul iese gol, flowmap spune de ce.

Demo: `cd examples/shop && python -m flowmap all --open main.py` — comanda lui „Bogdan” produce
un total negativ (bug logic plantat în `apply_discount`), comanda lui „Carmen” eșuează pe stoc.
`flowmap slice 26 --direction backward` afișează exact lanțul care a produs excepția:

```
#0 main() -> None
  #16 process(customer='Bogdan', items=[('SKU-100', 1)], code='FIX50') !! AssertionError: ... (tratată aici)
    #22 build_invoice(order=<Order>, discount_code='FIX50') -> {... 'total': -37.48}
      #23 Order.subtotal() -> 18.5
      #24 apply_discount(total=18.5, code='FIX50') -> -31.5
      #25 add_vat(total=-31.5, rate=0.19) -> -37.48
    #26 validate_invoice(invoice={... 'total': -37.48}) !! AssertionError: 'total negativ pe factură: -37.48'
```

## Cum citești graful

- **Execuție** (implicit): un nod = o funcție care a rulat; `×n` = de câte ori. Muchii gri = a chemat pe;
  muchii albastre punctate = valoarea returnată a devenit argumentul celuilalt (eticheta e numele parametrului).
  Roșu = a ridicat o excepție netratată; galben = a tratat o excepție.
- **Tranzacții** (stânga): fiecare apel de nivel 1 e o „tranzacție”; alegerea uneia ascunde tot ce nu a
  participat la ea (feliere dinamică pe subarbore).
- **Felia unui apel concret**: click pe un nod, apoi pe un apel `#id` din panoul din dreapta. Rămân vizibile
  doar: strămoșii, producătorii valorilor primite ca argument (și calculul din interiorul lor, tranzitiv),
  descendenții și consumatorii valorii returnate. Pentru o excepție, click direct în lista „Excepții”.
- **Axa temporală** (jos): derulează sau apasă Redă — nodurile apar în ordinea primei execuții,
  relativ la selecția curentă.
- **Structură**: scheletul static, pe coloane per fișier. Contur punctat = funcție nerulată în trace
  (coverage gap); contur albastru = punct de intrare; muchie punctată = apel ambiguu (mai multe ținte cu același nume).

## Limitări cunoscute (candidate pentru capitolele de „lucrări viitoare”)

- Doar Python 3.12+ (tracer-ul depinde de `sys.monitoring`).
- Rezoluția statică a apelurilor e după nume, nu după tipuri — de aici muchiile „ambigue”.
- Amprentarea valorilor nu vede mutațiile in-place (o listă modificată de B și citită de C nu produce muchie B→C)
  și nu urmărește valori prin structuri (un element scos dintr-un dict nu se leagă de dict).
- Generatoarele/corutinele apar ca un apel separat pentru fiecare segment resume→yield.
- Overhead: ~5 µs per apel trasat (două callback-uri Python). Pe cod obișnuit e imperceptibil; pe micro-benchmark-uri
  de tip `fib(24)` (150 000 de apeluri în 4 ms) încetinirea e de ~180×. Trace-ul se oprește curat la
  `--max-calls` (implicit 200 000); vizualizatorul încarcă un trace de 150 000 de apeluri în sub o secundă.
- Nu execută nimic singur: are nevoie de un script sau de o suită de teste. Este alegerea deliberată discutată
  în documentul de analiză — auto-descoperirea intrărilor valide e o problemă separată (fuzzing / execuție concolică).

## Teste

```bash
pip install -e ".[test]" && python -m pytest -q
# opțional, testul de integrare al vizualizatorului:
pip install playwright && python -m playwright install chromium
```

50 de teste: tracer (arbore de apeluri, valori, excepții, generatoare/async, thread-uri, overflow, excluderea
bibliotecilor), schelet static (ambiguitate, fișiere cu erori de sintaxă, rute), feliere, CLI, server HTTP
(inclusiv path traversal), PHP (schelet, tracer, cazuri-limită ale instrumentării, proiect mixt) și un test
end-to-end în Chromium care verifică felierea în graf. CI rulează pe Linux, Windows și macOS cu Python 3.12 și 3.13
și PHP 8 (preinstalat pe runner-e). Testele PHP se sar dacă `php` lipsește.

## Structură

```
flowmap/
  flowmap/
    __main__.py      CLI (static | run | slice | serve | all | init-vscode)
    tracer.py        sys.monitoring, amprente de valori, muchii de date
    static_map.py    schelet ast (+ integrarea scheletului PHP)
    php.py           lansează php pentru static.php / bootstrap.php
    php/runtime.php  instrumentare la include (stream wrapper) + tracer PHP, același trace.json
    php/bootstrap.php, php/static.php
    slicer.py        feliere dinamică (implementare de referință, oglindită în viewer)
    server.py        server HTTP local (/api/trace, /api/static, /api/source)
    viewer/index.html
    templates/tasks.json
  examples/shop/     proiect demo cu două defecte plantate
  examples/shop-php/ același demo, în PHP
  tests/
  .github/workflows/ci.yml
```
