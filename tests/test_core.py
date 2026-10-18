import tempfile
import unittest
from pathlib import Path

from screapers.ai.bots import AIBots
from screapers.config import Settings
from screapers.datasets import DatasetStore, to_csv
from screapers.parser import parse_page
from screapers.security import AuditLog, assert_safe_url, mask_records, redact_text, safe_join


class TestParser(unittest.TestCase):
    def test_extract(self):
        page = parse_page(
            '<html><head><title>Título</title></head><body><h1>Hola</h1>'
            '<a href="/x">Enlace X</a><table><tr><th>Nombre</th><th>Precio</th></tr>'
            '<tr><td>A</td><td>10</td></tr></table></body></html>',
            "https://example.org/")
        self.assertEqual(page["titulo"], "Título")
        self.assertTrue(any(r.get("Nombre") == "A" for r in page["records"]))

    def test_selector(self):
        page = parse_page('<div class="prod">Uno</div><div>Dos</div>',
                          "https://e.org/", selector=".prod")
        self.assertEqual([r["texto"] for r in page["records"]], ["Uno"])


class TestSecurity(unittest.TestCase):
    def test_pii_y_secretos(self):
        self.assertTrue(mask_records([{"e": "ana@example.com"}])[0]["e"].startswith("a***@"))
        self.assertNotIn("secreto123", redact_text("password=secreto123"))
        self.assertIn("***:***@", redact_text("https://user:pass@example.com/x"))

    def test_ssrf_esquema(self):
        with self.assertRaises(ValueError):
            assert_safe_url("file:///etc/passwd")
        with self.assertRaises(ValueError):
            assert_safe_url("https://user:pass@example.org/")

    def test_safe_join(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                safe_join(Path(td), "..", "fuera.txt")

    def test_audit_chain(self):
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(Path(td) / "a.log")
            log.append("uno"); log.append("dos")
            self.assertTrue(log.verify())
            self.assertEqual(len(log.tail()), 2)


class TestDataYBots(unittest.TestCase):
    def test_dataset_roundtrip_y_csv_bom(self):
        with tempfile.TemporaryDirectory() as td:
            store = DatasetStore(Path(td))
            store.save("demo", [{"a": 1}])
            self.assertEqual(store.load("demo"), [{"a": 1}])
            self.assertIn("demo", store.list())
            store.delete("demo")
            self.assertEqual(store.list(), [])
        self.assertTrue(to_csv([{"a": 1}]).startswith(b"\xef\xbb\xbf"))

    def test_cleaner_dedupe(self):
        bots = AIBots(Settings())
        self.assertEqual(bots.clean_records([{"a": " 1 "}, {"a": "1"}]), [{"a": "1"}])


if __name__ == "__main__":
    unittest.main()
