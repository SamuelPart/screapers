"""Flujo streaming completo contra un sitio propio simulado (local)."""
import functools
import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from screapers.config import Settings
from screapers.scraper import Scraper
from screapers.parser import parse_page
from screapers.streaming import find_related

INDEX = """<html><head><title>Mi Serie — ver online</title></head><body>
<h1>Mi Serie</h1><iframe src="/player/ep1"></iframe>
<a href="/ep2.html">Mi Serie Temporada 1 Episodio 2</a>
<a href="/ep3.html">Mi Serie Temporada 1 Episodio 3</a>
<a href="/otra.html">Otra Cosa</a></body></html>"""

EP = """<html><head><title>Mi Serie episodio</title></head><body>
<iframe src="https://player.example/embed/{n}"></iframe>
<a href="/index.html">Mi Serie</a></body></html>"""


class TestFlujoStreaming(unittest.TestCase):
    def test_embed_y_relacionados(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "index.html").write_text(INDEX, encoding="utf-8")
            (root / "ep2.html").write_text(EP.format(n=2), encoding="utf-8")
            (root / "ep3.html").write_text(EP.format(n=3), encoding="utf-8")
            (root / "otra.html").write_text("<html><body>Otra</body></html>", encoding="utf-8")
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=td)
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                base = f"http://127.0.0.1:{srv.server_address[1]}"
                s = Settings()
                s.allow_private, s.respect_robots = True, False
                s.delay_min = s.delay_max = 0
                s.max_depth, s.max_pages = 0, 5
                pages_seen = []
                pages, records = Scraper(s).crawl(
                    base + "/index.html", want_embeds=True,
                    on_page=lambda pg, r: pages_seen.append(pg))
                links = [l for pg in pages_seen for l in pg["enlaces"]]
                related = find_related(links, "Mi Serie")
            finally:
                srv.shutdown(); srv.server_close()
        self.assertEqual(pages, 1)
        self.assertTrue(any(r["embed_url"].endswith("/player/ep1") for r in records))
        self.assertEqual(len(related), 2)  # solo los dos episodios, no "Otra Cosa"


if __name__ == "__main__":
    unittest.main()
