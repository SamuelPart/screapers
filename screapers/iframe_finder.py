"""Buscador dirigido de <iframe>: no construye el DOM ni guarda la página.

Recorre el HTML en flujo y conserva SOLO lo relacionado con iframes,
incluidas las formas ocultas/diferidas habituales en reproductores:

- `<iframe src=...>` clásico (como el `class="metaframe rptss"` de voe).
- Carga diferida: `data-src`, `data-lazy-src`, `data-original`, `data-url`.
- `srcdoc` con otro iframe dentro.
- Iframes escritos desde JavaScript (cadenas con la etiqueta en <script>).
- URLs codificadas en base64 dentro de atributos o scripts.
- «Click-to-play»: elementos con botón play y la URL del embed en
  `data-*`/`onclick` que solo crean el iframe al pulsar. El bot no pulsa
  nada en el sitio: lee esos atributos y entrega la URL ya activada.

El resto del documento se descarta al instante.
"""
from __future__ import annotations

import base64
import binascii
import html as html_mod
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

_URL_RE = re.compile(r"https?://[^\s\"'<>\\\)\]]+")
_B64_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{24,}\b")
_IFRAME_SRC_RE = re.compile(
    r"""<iframe[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.I | re.S)
_LAZY_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-url",
               "data-embed", "data-embed-url", "data-video", "data-video-url",
               "data-player", "data-iframe", "data-frame")
_ACTIVABLE_HINTS = ("play", "player", "reproduc", "watch", "ver-", "load-", "cargar")


def _clean_url(raw: str, base_url: str) -> str:
    u = html_mod.unescape((raw or "").strip()).replace("\\/", "/")
    u = unquote(u).strip(" \"'<>")
    if u.startswith("//"):
        u = urlparse(base_url).scheme + ":" + u
    return urljoin(base_url, u)


def _decode_b64(token: str) -> str:
    try:
        padded = token.strip() + "=" * (-len(token.strip()) % 4)
        return base64.b64decode(padded, validate=False).decode("utf-8", errors="ignore")
    except (binascii.Error, ValueError):
        return ""


def _urls_from_text(text: str, base_url: str) -> list[tuple[str, str]]:
    """(url, método) escondidas en texto: directas, en iframes o en base64."""
    found: list[tuple[str, str]] = []
    if not text:
        return found
    decoded_html = html_mod.unescape(text).replace("\\/", "/").replace('\\"', '"')
    for m in _IFRAME_SRC_RE.finditer(decoded_html):
        found.append((_clean_url(m.group(1), base_url), "iframe-en-script"))
    plain = unquote(decoded_html)
    for m in _URL_RE.finditer(plain):
        u = _clean_url(m.group(0), base_url)
        # Solo URLs con pinta de embed/vídeo, para no inundar de enlaces sueltos
        low = u.lower()
        if any(k in low for k in ("/e/", "embed", "player", "watch", "video",
                                  ".mp4", ".m3u", "iframe")):
            found.append((u, "url-en-script"))
    for token in _B64_RE.findall(text):
        decoded = _decode_b64(token)
        if not decoded or "http" not in decoded:
            continue
        for m in _IFRAME_SRC_RE.finditer(decoded):
            found.append((_clean_url(m.group(1), base_url), "iframe-base64"))
        for m in _URL_RE.finditer(decoded):
            found.append((_clean_url(m.group(0), base_url), "url-base64"))
    return found


class _IframeParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.iframes: list[dict] = []
        self.title = ""
        self._seen: set[str] = set()
        self._in_title = False
        self._in_script = False
        self._script_parts: list[str] = []

    # --------------------------------------------------------- registro
    def _add(self, url: str, method: str, extra: dict | None = None):
        if not url or url.lower().startswith(("javascript:", "data:", "about:", "#")):
            return
        url = _clean_url(url, self.base_url)
        if url in self._seen or not url.startswith(("http://", "https://")):
            return
        self._seen.add(url)
        rec = {
            "tipo": "iframe" if method == "iframe" else "iframe-oculto",
            "embed_url": url,
            "dominio": urlparse(url).netloc,
            "fuente_deteccion": method,
            "pagina_exacta": self.base_url,
        }
        if extra:
            rec.update(extra)
        self.iframes.append(rec)

    # ------------------------------------------------------------ tags
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
            return
        if tag == "script":
            self._in_script = True
            # scripts con src no aportan; el texto inline se analiza al cerrar
            return
        if tag == "iframe":
            src = (a.get("src") or "").strip()
            if src:
                self._add(src, "iframe", {"titulo_iframe": a.get("title", "")})
            for attr in _LAZY_ATTRS:
                if a.get(attr):
                    self._add(a[attr], f"diferido ({attr})",
                              {"titulo_iframe": a.get("title", "")})
            if a.get("srcdoc"):
                for u, method in _urls_from_text(a["srcdoc"], self.base_url):
                    self._add(u, "srcdoc")
            return
        # click-to-play y contenedores del reproductor con la URL en data-*
        hints = " ".join([a.get("class", ""), a.get("id", ""), tag]).lower()
        looks_activable = any(h in hints for h in _ACTIVABLE_HINTS) or "onclick" in a
        for attr in _LAZY_ATTRS:
            if a.get(attr) and (looks_activable or attr != "data-url"):
                self._add(a[attr],
                          "activable al pulsar play" if looks_activable else f"diferido ({attr})")
        if a.get("onclick"):
            for u, _m in _urls_from_text(a["onclick"], self.base_url):
                self._add(u, "activable al pulsar play")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_script = False
            if self._script_parts:
                blob = "".join(self._script_parts)
                self._script_parts = []
                for u, method in _urls_from_text(blob, self.base_url):
                    self._add(u, method)

    def handle_data(self, data):
        if self._in_title and len(self.title) < 200:
            self.title = (self.title + data).strip()[:200]
        elif self._in_script and len(data) < 200_000:
            self._script_parts.append(data)


def find_iframes(html: str, base_url: str) -> tuple[str, list[dict]]:
    """Devuelve (título, iframes) sin retener nada más de la página."""
    parser = _IframeParser(base_url)
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        pass
    for rec in parser.iframes:
        rec["pagina"] = parser.title
    return parser.title, parser.iframes
