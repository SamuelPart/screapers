"""Integración: scraping real contra un servidor HTTP local efímero."""
import functools
import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from screapers.ai.bots import AIBots
from screapers.config import Settings
from screapers.scraper import Scraper

HTML = """<html><head><title>Tienda Demo</title></head><body>
<h1>Productos</h1>
<table><tr><th>Nombre</th><th>Precio</th></tr>
<tr><td>Teclado</td><td>25</td></tr><tr><td>Ratón</td><td>15</td></tr></table>
<a href="/index.html">Inicio</a></body></html>"""


class TestCrawlLocal(unittest.TestCase):
    def test_crawl_y_limpieza(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "index.html").write_text(HTML, encoding="utf-8")
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=td)
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                s = Settings()
                s.allow_private, s.respect_robots = True, False
                s.delay_min = s.delay_max = 0
                url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
                pages, records = Scraper(s).crawl(url)
                clean = AIBots(s).clean_records(records)
            finally:
                srv.shutdown()
                srv.server_close()
        self.assertEqual(pages, 1)
        self.assertTrue(any(r.get("nombre") == "Teclado" and r.get("precio") == "25" for r in clean))
        self.assertTrue(any(r.get("nombre") == "Ratón" for r in clean))


if __name__ == "__main__":
    unittest.main()
