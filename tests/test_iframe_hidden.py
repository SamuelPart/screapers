import base64
import unittest

from screapers.iframe_finder import find_iframes
from screapers.parser import parse_page

BASE = "https://misitio.example/ver/capitulo-1"
B64 = base64.b64encode(b"https://player.example/e/secreto123").decode()
HTML = f"""<html><head><title>Mi Capítulo</title></head><body>
<iframe class="metaframe rptss" src="https://voe.sx/e/osmswbjzgzvu" frameborder="0"
        scrolling="no" allow="autoplay; encrypted-media" allowfullscreen=""></iframe>
<iframe data-src="https://player.example/lazy/1"></iframe>
<div class="play-button" data-embed="https://player.example/click/2">Ver ahora</div>
<button onclick="cargar('https://player.example/onclick/9')">Play</button>
<script>var a = "<iframe src=\\"https://player.example/js/3\\"></iframe>"; var b = "{B64}";</script>
<iframe srcdoc="&lt;iframe src='https://player.example/doc/4'&gt;&lt;/iframe&gt;"></iframe>
<iframe src="https://voe.sx/e/osmswbjzgzvu"></iframe>
<video src="https://cdn.example/no-es-iframe.mp4"></video>
</body></html>"""


class TestIframesOcultos(unittest.TestCase):
    def setUp(self):
        self.title, self.frames = find_iframes(HTML, BASE)
        self.urls = {f["embed_url"] for f in self.frames}

    def test_ejemplo_real_metaframe(self):
        # El caso pegado por el usuario: <iframe class="metaframe rptss" src="https://voe.sx/e/...">
        self.assertIn("https://voe.sx/e/osmswbjzgzvu", self.urls)
        rec = next(f for f in self.frames if "voe.sx" in f["embed_url"])
        self.assertEqual(rec["fuente_deteccion"], "iframe")
        self.assertEqual(rec["pagina_exacta"], BASE)

    def test_todos_los_ocultos_sin_duplicados(self):
        esperadas = {
            "https://player.example/lazy/1",
            "https://player.example/click/2",
            "https://player.example/js/3",
            "https://player.example/e/secreto123",   # base64
            "https://player.example/doc/4",          # srcdoc
        }
        self.assertTrue(esperadas.issubset(self.urls))
        self.assertEqual(len(self.frames), len(self.urls))       # sin duplicados
        self.assertNotIn("https://cdn.example/no-es-iframe.mp4", self.urls)  # solo iframe

    def test_metodos_de_deteccion(self):
        methods = {f["fuente_deteccion"] for f in self.frames}
        self.assertTrue(any("play" in m for m in methods))       # click-to-play resuelto
        self.assertTrue(any("base64" in m for m in methods))
        self.assertIn("srcdoc", methods)
        self.assertIn("iframe-en-script", methods)

    def test_integracion_con_parser(self):
        page = parse_page(HTML, BASE, want_embeds=True, iframe_only=True)
        self.assertIn("https://voe.sx/e/osmswbjzgzvu",
                      {r["embed_url"] for r in page["records"]})


if __name__ == "__main__":
    unittest.main()
