"""Test de integrare al vizualizatorului (necesită playwright + chromium; altfel se sare)."""
import threading
from http.server import ThreadingHTTPServer

import pytest

pw = pytest.importorskip("playwright.sync_api")
from flowmap.server import make_handler


@pytest.fixture
def url(shop):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(shop / ".flowmap"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


def test_viewer_renders_and_slices(url):
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"chromium indisponibil: {e}")
        pg = b.new_page(viewport={"width": 1400, "height": 820})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(url); pg.wait_for_function("window.fm && window.fm.cy && window.fm.cy.nodes().length > 0", timeout=20000)
        assert pg.evaluate("fm.cy.nodes('[kind=\"fn\"]').length") == 12
        assert pg.evaluate("fm.cy.edges('[kind=\"data\"]').length") == 4
        assert pg.evaluate("fm.cy.nodes('[err > 0]').map(n => n.data('label')).sort()") == ["Order.add", "validate_invoice"]
        pg.click("#tx-16"); pg.wait_for_timeout(300)
        assert pg.evaluate("fm.cy.nodes('[kind=\"fn\"].dim').map(n => n.data('label'))") == ["main"]
        pg.click("#exc-26"); pg.wait_for_timeout(300)
        visible = pg.evaluate("fm.cy.nodes('[kind=\"fn\"]').not('.dim').map(n => n.data('label')).sort()")
        assert visible == sorted(["validate_invoice", "process", "main", "build_invoice", "Order.subtotal", "apply_discount", "add_vat"])
        assert "def validate_invoice" in pg.inner_text("#detail")
        pg.click("#mode-static"); pg.wait_for_timeout(500)
        assert pg.evaluate("fm.cy.nodes('[covered = \"no\"]').length") == 3
        assert errors == []
        b.close()
