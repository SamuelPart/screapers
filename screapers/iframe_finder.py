"""Buscador dirigido de <iframe>: no construye el DOM ni guarda la página.

Recorre el HTML en flujo y conserva SOLO las etiquetas iframe (su `src`
y poco más) y el título. El resto del documento se descarta al instante.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


class _IframeParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.iframes: list[dict] = []
        self.title = ""
        self._seen: set[str] = set()
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
            return
        if tag != "iframe":
            return
        a = dict(attrs)
        src = (a.get("src") or "").strip()
        if not src or src.lower().startswith(("javascript:", "data:", "about:")):
            return
        url = urljoin(self.base_url, src)
        if url in self._seen or not url.startswith(("http://", "https://")):
            return
        self._seen.add(url)
        self.iframes.append({
            "tipo": "iframe",
            "embed_url": url,
            "dominio": urlparse(url).netloc,
            "titulo_iframe": a.get("title", ""),
            "pagina_exacta": self.base_url,
        })

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and len(self.title) < 200:
            self.title = (self.title + data).strip()[:200]


def find_iframes(html: str, base_url: str) -> tuple[str, list[dict]]:
    """Devuelve (título, iframes) sin retener nada más de la página."""
    parser = _IframeParser(base_url)
    try:
        parser.feed(html or "")  # HTMLParser admite entradas enormes en flujo
        parser.close()
    except Exception:
        pass
    for rec in parser.iframes:
        rec["pagina"] = parser.title
    return parser.title, parser.iframes
