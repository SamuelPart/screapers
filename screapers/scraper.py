"""Motor de scraping educado (anti-bloqueo sin evasión abusiva).

Respeta robots.txt, limita la velocidad con jitter, reintenta con backoff
honrando Retry-After y se detiene ante 403/CAPTCHA en vez de forzar el
sitio. No burla CAPTCHAs, paywalls ni controles de acceso.
"""
from __future__ import annotations

import gzip
import http.cookiejar
import random
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections import deque
from urllib.parse import urlparse

from .config import Settings
from .parser import parse_page
from .security import assert_safe_url

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]
MAX_BYTES = 5_000_000


class Scraper:
    def __init__(self, settings: Settings, log=lambda m: None, stop: threading.Event | None = None):
        self.s, self.log = settings, log
        self.stop = stop or threading.Event()
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        # Sesión consistente: mismo User-Agent y cookies durante todo el rastreo.
        # Rotar la identidad en cada petición es justo lo que delata a un bot.
        self.user_agent = random.choice(USER_AGENTS)
        self.last_error: str = ""
        self._extra_delay = 0.0  # freno adaptativo ante 429/5xx
        self._opener = self._build_opener()

    def _build_opener(self):
        handlers = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
        if self.s.proxy:  # proxy propio del usuario, solo durante la sesión
            handlers.append(urllib.request.ProxyHandler({"http": self.s.proxy, "https": self.s.proxy}))
        return urllib.request.build_opener(*handlers)

    # -- robots.txt -------------------------------------------------
    def _allowed(self, url: str) -> bool:
        if not self.s.respect_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots_cache:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(base + "/robots.txt")
            try:
                rp.read()
            except Exception:
                rp = None  # sin robots legible: se permite, con velocidad educada
            self._robots_cache[base] = rp
        rp = self._robots_cache[base]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    # -- descarga ---------------------------------------------------
    def fetch(self, url: str) -> str:
        assert_safe_url(url, allow_private=self.s.allow_private)
        last_err = None
        for attempt in range(3):
            if self.stop.is_set():
                raise InterruptedError("Detenido por el usuario")
            req = urllib.request.Request(url, headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
                "Accept-Encoding": "gzip",
            })
            try:
                with self._opener.open(req, timeout=self.s.timeout) as resp:
                    raw = resp.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        self.log("⚠ Página truncada a 5 MB")
                        raw = raw[:MAX_BYTES]
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return raw.decode(charset, errors="replace")
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (401, 403):
                    raise PermissionError(
                        f"El sitio respondió {e.code} (acceso denegado/bot o CAPTCHA). "
                        "Me detengo: no fuerzo accesos. Prueba más lento o revisa el sitio manualmente.") from e
                if e.code == 429 or e.code >= 500:
                    wait = e.headers.get("Retry-After") if e.headers else None
                    delay = float(wait) if (wait or "").isdigit() else min(2 ** attempt * 2, 20)
                    self._extra_delay = min(self._extra_delay + 2.0, 30.0)  # frenar más a partir de ahora
                    self.log(f"⏳ HTTP {e.code}: el sitio pide calma. Espero {delay:.0f}s "
                             f"(reintento {attempt + 1}/3) y subo la pausa entre páginas.")
                    self.stop.wait(delay)
                    continue
                raise
            except Exception as e:  # red, SSL, timeout…
                last_err = e
                self.stop.wait(min(2 ** attempt, 8))
        raise RuntimeError(f"No se pudo descargar {url}: {last_err}")

    # -- rastreo ------------------------------------------------------
    def crawl(self, start_url: str, selector: str = "", on_page=lambda page, records: None,
              want_embeds: bool = False):
        """BFS mismo dominio. Devuelve (páginas, registros)."""
        try:
            start = assert_safe_url(start_url, allow_private=self.s.allow_private)
        except Exception as e:  # URL inválida/insegura: 0 páginas con motivo, sin excepción
            self.last_error = str(e)
            self.log(f"✗ {start_url}: {e}")
            return 0, []
        host = urlparse(start).netloc
        queue, visited = deque([(start, 0)]), set()
        all_records: list[dict] = []
        pages = 0
        while queue and pages < self.s.max_pages and not self.stop.is_set():
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            if not self._allowed(url):
                self.log(f"🤖 robots.txt no permite: {url}")
                continue
            if pages > 0:  # pausa educada (y adaptativa) entre peticiones
                self.stop.wait(random.uniform(self.s.delay_min, self.s.delay_max) + self._extra_delay)
            try:
                html = self.fetch(url)
            except InterruptedError:
                break
            except Exception as e:
                self.last_error = str(e)
                self.log(f"✗ {url}: {e}")
                continue
            page = parse_page(html, url, selector, want_embeds=want_embeds)
            pages += 1
            recs = page.pop("records")
            for r in recs:
                r.setdefault("fuente", url)
            all_records.extend(recs)
            self.log(f"✓ {url} — {len(recs)} registros")
            on_page(page, recs)
            if depth < self.s.max_depth:
                for link in page["enlaces"]:
                    u = link["url"].split("#")[0]
                    if urlparse(u).netloc == host and u not in visited:
                        queue.append((u, depth + 1))
        return pages, all_records
