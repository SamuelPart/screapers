import functools
import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from screapers.chatbot import ChatEngine, detect_export_format, extract_url
from screapers.config import Settings

INDEX = """<html><head><title>Mi Serie — ver online</title></head><body>
<h1>Mi Serie</h1><iframe src="/player/ep1"></iframe>
<a href="/ep2.html">Mi Serie Temporada 1 Episodio 2</a>
<a href="/ep3.html">Mi Serie Temporada 2 Episodio 1</a>
<a href="/otra.html">Otra Cosa</a></body></html>"""
EP = ('<html><head><title>ep</title></head><body>'
      '<iframe src="https://player.example/embed/{n}"></iframe></body></html>')


def _settings():
    s = Settings()
    s.allow_private, s.respect_robots = True, False
    s.delay_min = s.delay_max = 0
    s.max_depth, s.max_pages = 0, 10
    return s


class TestChatSinRed(unittest.TestCase):
    def test_utilidades(self):
        self.assertEqual(extract_url("mira https://e.com/ver/1, porfa"), "https://e.com/ver/1")
        self.assertEqual(detect_export_format("exporta en csv.gz"), "csv.gz")
        self.assertEqual(detect_export_format("exporta eso"), "json.gz")

    def test_ayuda_y_sin_url(self):
        bot = ChatEngine(_settings())
        self.assertIn("Puedo trabajar", bot.process("ayuda").text)
        self.assertIn("Necesito una URL", bot.process("encuentra el iframe").text)

    def test_exportar_sin_datos(self):
        bot = ChatEngine(_settings())
        self.assertIn("Todavía no tengo", bot.process("exporta en json").text)


class TestChatConSitioLocal(unittest.TestCase):
    def test_conversacion_streaming(self):
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
                bot = ChatEngine(_settings())
                r1 = bot.process(f"encuentra el iframe de esta página: {base}/index.html")
                self.assertIn("Encontré", r1.text)
                self.assertTrue(any(x["embed_url"].endswith("/player/ep1") for x in r1.records))
                self.assertIn(base + "/index.html", r1.text)  # página exacta citada

                bot.set_query("Mi Serie")
                r2 = bot.process("busca episodios con el mismo nombre o similares y extrae su embed")
                embeds = {x["embed_url"] for x in (r2.records or [])}
                self.assertIn("https://player.example/embed/2", embeds)
                self.assertIn("https://player.example/embed/3", embeds)

                r3 = bot.process("exporta los enlaces en json.gz")
                self.assertEqual(r3.action, {"type": "export", "format": "json.gz"})
            finally:
                srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
