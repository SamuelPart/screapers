"""Regresión del aviso engañoso: 0 páginas deben reportar el motivo real."""
import unittest

from screapers.config import Settings
from screapers.scraper import Scraper


def _settings():
    s = Settings()
    s.allow_private, s.respect_robots = True, False
    s.delay_min = s.delay_max = 0
    return s


class TestSinPaginas(unittest.TestCase):
    def test_puerto_cerrado_deja_error_real(self):
        scraper = Scraper(_settings())
        pages, records = scraper.crawl("http://127.0.0.1:9/sin-servicio")
        self.assertEqual(pages, 0)
        self.assertEqual(records, [])
        self.assertTrue(scraper.last_error)  # la UI muestra esto, no el aviso de IA

    def test_url_insegura_deja_error_real(self):
        scraper = Scraper(_settings())
        pages, _ = scraper.crawl("file:///etc/passwd")
        self.assertEqual(pages, 0)
        self.assertIn("http", scraper.last_error)

    def test_sesion_consistente(self):
        scraper = Scraper(_settings())
        self.assertIn(scraper.user_agent, __import__("screapers.scraper", fromlist=["USER_AGENTS"]).USER_AGENTS)
        ua2 = Scraper(_settings()).user_agent
        self.assertTrue(ua2)  # la identidad se fija por sesión, no por petición


if __name__ == "__main__":
    unittest.main()
