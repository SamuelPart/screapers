import unittest

from screapers.parser import parse_page
from screapers.streaming import (base_title, episode_info, find_related,
                                 group_episodes, parse_instruction)


class TestOrdenes(unittest.TestCase):
    def test_embed_serie(self):
        plan = parse_instruction(
            "quiero extraer el enlace del embed de esta serie y buscar episodios "
            "con el mismo nombre o similares", "Mi Serie")
        self.assertEqual(plan.intent, "embed")
        self.assertEqual(plan.media_type, "serie")
        self.assertTrue(plan.search_in_site)
        self.assertTrue(plan.follow_related)
        self.assertTrue(plan.group_episodes)
        self.assertEqual(plan.query, "Mi Serie")

    def test_pelicula_sin_busqueda(self):
        plan = parse_instruction("extrae el embed de esta pelicula")
        self.assertEqual(plan.intent, "embed")
        self.assertEqual(plan.media_type, "pelicula")
        self.assertFalse(plan.follow_related)

    def test_tablas(self):
        self.assertEqual(parse_instruction("extrae las tablas de precios").intent, "tablas")

    def test_titulo_entre_comillas(self):
        plan = parse_instruction('busca episodios de "La Casa Grande" similares')
        self.assertEqual(plan.query, "La Casa Grande")


class TestRelacionados(unittest.TestCase):
    LINKS = [
        {"texto": "Mi Serie Temporada 1 Episodio 2", "url": "https://s.example/serie/mi-serie-1x2"},
        {"texto": "Mi Serie Temporada 1 Episodio 10", "url": "https://s.example/serie/mi-serie-1x10"},
        {"texto": "Mi Serie Temporada 2 Episodio 1", "url": "https://s.example/serie/mi-serie-2x1"},
        {"texto": "Otra Cosa Distinta", "url": "https://s.example/otra-cosa"},
        {"texto": "Mi Serie: la película", "url": "https://s.example/pelicula/mi-serie-la-pelicula"},
    ]

    def test_similares_y_episodios(self):
        rel = find_related(self.LINKS, "Mi Serie")
        urls = [r["url"] for r in rel]
        self.assertNotIn("https://s.example/otra-cosa", urls)
        self.assertGreaterEqual(len(rel), 3)
        self.assertIn("Temporada 1", group_episodes(rel))

    def test_base_y_episodio(self):
        self.assertEqual(base_title("Mi Serie Temporada 1 Episodio 3 HD"), "mi serie")
        self.assertEqual(episode_info("Show S02E05"), {"temporada": 2, "episodio": 5})


class TestEmbedsParser(unittest.TestCase):
    def test_tipos_de_embed(self):
        html = ('<html><head><title>Ver Mi Serie 1x1</title>'
                '<meta property="og:video" content="https://cdn.example/og.mp4"></head><body>'
                '<iframe src="/player/xyz"></iframe>'
                '<video><source src="https://cdn.example/v.mp4" type="video/mp4"></video>'
                '<script type="application/ld+json">{"@type":"VideoObject","name":"Ep1",'
                '"embedUrl":"https://player.example/e/9"}</script></body></html>')
        page = parse_page(html, "https://s.example/ver/1x1", want_embeds=True)
        tipos = {e["tipo"] for e in page["embeds"]}
        self.assertIn("iframe", tipos)
        self.assertIn("video", tipos)
        self.assertIn("jsonld-video", tipos)
        self.assertTrue(all(r["embed_url"] for r in page["records"]))


if __name__ == "__main__":
    unittest.main()
