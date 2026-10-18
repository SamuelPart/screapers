"""Cerebro conversacional del asistente de streaming.

Entiende órdenes en español, recuerda el contexto (última URL, iframes
encontrados, relacionados, episodios) y obedece: buscar el iframe de una
página exacta, rastrear títulos iguales/similares en el dominio, entrar en
los episodios, filtrar por temporada o preparar una exportación.
Todo el entendimiento es local (reglas + heurísticas), sin enviar tu
conversación a ningún servicio.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .ai.bots import AIBots
from .parser import parse_page
from .scraper import Scraper
from .streaming import (base_title, episode_info, find_related, group_episodes,
                        normalize, parse_instruction, search_candidates)

_URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")
_EXPORT_WORDS = ("exporta", "exportar", "descarga", "descargar", "guardar en", "guarda en", "csv", "json", "sqlite", "xlsx")
_SIMILAR_WORDS = ("similar", "mismo nombre", "relacionad", "episodio", "temporada", "serie")


def extract_url(text: str) -> str:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(".,;") if m else ""


def detect_export_format(text: str) -> str:
    raw = (text or "").lower()
    low = normalize(text)  # ojo: normalize convierte "csv.gz" en "csv gz"
    if "csv.gz" in raw or "csv gz" in low:
        return "csv.gz"
    if "json.gz" in raw or "json gz" in low:
        return "json.gz"
    for fmt in ("jsonl", "xlsx", "sqlite", "json", "csv"):
        if fmt in low:
            return fmt
    return "json.gz"


@dataclass
class BotReply:
    text: str
    records: list[dict] | None = None      # si no es None, sustituye los resultados
    related: list[dict] | None = None
    action: dict | None = None             # {"type": "export", "format": ...}
    status: str = ""


@dataclass
class ChatContext:
    last_url: str = ""
    last_query: str = ""
    records: list[dict] = field(default_factory=list)
    related: list[dict] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)   # ligero: url/título/enlaces/embeds


class ChatEngine:
    """Un motor por conversación (conserva el contexto entre mensajes)."""

    def __init__(self, settings, log=lambda m: None):
        self.settings = settings
        self.log = log
        self.bots = AIBots(settings)
        self.ctx = ChatContext()

    def set_settings(self, settings):
        self.settings = settings
        self.bots = AIBots(settings)

    # ------------------------------------------------------------ util
    def _scraper(self, logs: list[str], single_page: bool = False) -> Scraper:
        cfg = copy.copy(self.settings)
        if single_page:
            cfg.max_pages, cfg.max_depth = 1, 0
        def _log(m):
            logs.append(m)
            self.log(m)
        return Scraper(cfg, log=_log)

    def _reason(self, logs: list[str], scraper: Scraper) -> str:
        for line in logs:
            if "robots.txt" in line:
                return ("el `robots.txt` del sitio no permite rastrearlo. Si es tu web, "
                        "marca «Es mi sitio» en los ajustes y lo audito igualmente.")
            if "403" in line or "401" in line or "CAPTCHA" in line:
                return "el sitio denegó el acceso (403/CAPTCHA). No fuerzo accesos protegidos."
        return scraper.last_error or "sin respuesta del sitio"

    def _dedupe_embeds(self, records: list[dict]) -> list[dict]:
        cleaned = self.bots.clean_records(records)
        seen, out = set(), []
        for r in cleaned:
            key = r.get("embed_url") or r.get("url") or str(sorted(r.items()))
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    @staticmethod
    def _fmt_records(records: list[dict], limit: int = 12) -> str:
        lines = []
        for i, r in enumerate(records[:limit], 1):
            url = r.get("embed_url") or r.get("url", "")
            page = r.get("pagina_exacta") or r.get("fuente_pagina") or r.get("fuente", "")
            dom = r.get("dominio", "")
            lines.append(f"{i}. 🔗 {url}" + (f"\n   dominio: {dom}" if dom else "")
                         + (f"\n   página exacta: {page}" if page else ""))
        if len(records) > limit:
            lines.append(f"… y {len(records) - limit} más (en la tabla/exportación están todos).")
        return "\n".join(lines)

    # ---------------------------------------------------- extracción
    def _extract(self, url: str, instruction: str, single_page: bool,
                 logs: list[str]) -> tuple[int, list[dict], Scraper]:
        plan = parse_instruction(instruction, self.ctx.last_query)
        focused = plan.intent in ("embed", "general")  # foco streaming: solo <iframe>
        seen: list[dict] = []

        def on_page(page, recs):
            seen.append({k: page.get(k) for k in ("url", "titulo", "enlaces", "embeds")})
            self.ctx.pages = seen

        scraper = self._scraper(logs, single_page=single_page)
        pages, records = scraper.crawl(url, want_embeds=focused, iframe_only=focused,
                                       on_page=on_page)
        return pages, records, scraper

    def _related_flow(self, instruction: str, logs: list[str], scraper: Scraper,
                      base_url: str) -> list[dict]:
        query = self.ctx.last_query or (base_title(self.ctx.pages[0].get("titulo", ""))
                                        if self.ctx.pages else "")
        if not query:
            return []
        self.ctx.last_query = query
        links = [l for pg in self.ctx.pages for l in (pg.get("enlaces") or [])]
        related = find_related(links, query)
        if not related:
            for cand in search_candidates(base_url, query):
                try:
                    if not scraper._allowed(cand):
                        continue
                    self.log(f"🔎 Probando buscador del sitio: {cand}")
                    pg = parse_page(scraper.fetch(cand), cand, want_embeds=True, iframe_only=True)
                    self.ctx.pages.append({k: pg.get(k) for k in ("url", "titulo", "enlaces", "embeds")})
                    related = find_related(pg.get("enlaces", []), query)
                    if related:
                        break
                except Exception as e:
                    self.log(f"✗ Buscador {cand}: {e}")
        self.ctx.related = related
        # Entrar en cada relacionado y extraerle el iframe
        extra: list[dict] = []
        visited = {pg.get("url") for pg in self.ctx.pages}
        follower = self._scraper(logs, single_page=True)
        for rel in related[:12]:
            if rel["url"] in visited:
                continue
            visited.add(rel["url"])
            try:
                seen2: list[dict] = []
                n, recs = follower.crawl(
                    rel["url"], want_embeds=True, iframe_only=True,
                    on_page=lambda pg, r: seen2.append({k: pg.get(k) for k in ("url", "titulo", "enlaces", "embeds")}))
                self.ctx.pages.extend(seen2)
                extra.extend(recs)
            except Exception as e:
                self.log(f"✗ Relacionado {rel['url']}: {e}")
        return extra

    # --------------------------------------------------------- chat
    def process(self, message: str) -> BotReply:
        text = (message or "").strip()
        low = normalize(text)
        url = extract_url(text)
        logs: list[str] = []

        if not text:
            return BotReply("Escribe una orden o pega la URL de una película, serie o capítulo. 🙂")

        if low in ("hola", "buenas", "hey") or low.startswith("hola "):
            return BotReply("¡Hola! 🎬 Pega la URL de una película, serie o capítulo y dime qué hacer, "
                            "por ejemplo: «encuentra el iframe de esta página».")

        if "ayuda" in low or "que puedes hacer" in low or "qué puedes hacer" in text.lower():
            return BotReply(
                "Puedo trabajar sobre tus sitios de streaming (o con permiso):\n"
                "• «Encuentra el iframe de esta URL» — te entrego el enlace exacto del embed.\n"
                "• «Busca episodios con el mismo nombre o similares» — rastreo el dominio y los ordeno por temporada/episodio.\n"
                "• «Entra en cada episodio y extrae su embed».\n"
                "• «Quédate solo con la temporada 1».\n"
                "• «Exporta los enlaces en json.gz / csv».\n"
                "Respeto robots.txt (salvo que marques «Es mi sitio») y no fuerzo accesos protegidos.")

        # --- exportación (sobre lo ya encontrado) ---
        if any(w in low for w in _EXPORT_WORDS) and ("export" in low or "descarg" in low or "guarda" in low):
            if not self.ctx.records:
                return BotReply("Todavía no tengo resultados que exportar. Primero pídeme buscar algo, "
                                "por ejemplo el iframe de una URL.")
            fmt = detect_export_format(text)
            return BotReply(f"Preparando la exportación de {len(self.ctx.records)} resultado(s) en **{fmt}**. "
                            "Elige dónde guardarlo en la ventana que se abre. ⬇",
                            action={"type": "export", "format": fmt}, status="Exportando…")

        # --- filtro por temporada (sobre lo ya encontrado) ---
        m = re.search(r"temporada\s*(\d{1,2})", low)
        if m and any(w in low for w in ("solo", "quédate", "quedate", "filtra", "filtrar", "muestra", "muéstrame")):
            season = int(m.group(1))
            pool = self.ctx.records or self.ctx.related
            filtered = [r for r in pool
                        if episode_info(str(r.get("pagina", "")) + " " + str(r.get("fuente_pagina", ""))
                                          + " " + str(r.get("texto", "")) + " " + str(r.get("url", ""))).get("temporada") == season
                        or r.get("temporada") == season]
            if not filtered:
                return BotReply(f"No encontré nada de la temporada {season} en los resultados actuales. "
                                "Prueba: «busca episodios con el mismo nombre».")
            self.ctx.records = filtered
            return BotReply(f"Filtrado ✅: {len(filtered)} resultado(s) de la **temporada {season}**:\n"
                            + self._fmt_records(filtered),
                            records=filtered, status=f"Temporada {season}: {len(filtered)}")

        want_similar = any(w in low for w in _SIMILAR_WORDS) and not url
        target = url or (self.ctx.last_url if want_similar else "")

        if not target:
            return BotReply("Necesito una URL para empezar. Pégame la de una película, serie o capítulo, "
                            "ejemplo: «encuentra el iframe de https://misitio.com/ver/…». "
                            + ("Si ya estábamos con una, dime «sigue con la misma»." if self.ctx.last_url else ""))

        # --- extracción (con o sin búsqueda de similares) ---
        from .streaming import parse_instruction as _pi
        plan = _pi(text, self.ctx.last_query)
        if plan.query:
            self.ctx.last_query = plan.query
        self.ctx.last_url = target
        do_similar = plan.search_in_site or want_similar
        single = not do_similar

        pages, records, scraper = self._extract(target, text, single_page=single, logs=logs)
        if pages == 0:
            return BotReply("No pude extraer esa página: " + self._reason(logs, scraper) + "\n"
                            "Revisa la URL o pruébala primero en tu navegador.",
                            status="Sin resultados")

        extra: list[dict] = []
        related_note = ""
        if do_similar:
            extra = self._related_flow(text, logs, scraper, target)
            if self.ctx.related:
                related_note = "\n\n" + group_episodes(self.ctx.related)
            else:
                related_note = ("\n\nNo vi títulos iguales o similares en las páginas visitadas del dominio. "
                                "Prueba subiendo «Máx. páginas» o pegando la URL del índice de la serie.")

        all_records = self._dedupe_embeds(records + extra)
        self.ctx.records = all_records

        if plan.intent not in ("embed", "general"):
            return BotReply(f"Listo ✅: extraje {len(all_records)} registro(s) de "
                            f"`{urlparse(target).netloc}` según tu orden ({plan.intent}). "
                            "Están en las tarjetas de abajo y puedes exportarlos." + related_note,
                            records=all_records, related=self.ctx.related,
                            status=f"{len(all_records)} registros")
        if True:
            n_iframe = len([r for r in all_records if r.get("embed_url")])
            if n_iframe:
                head = (f"✅ Encontré **{n_iframe} embed(s)/iframe** en "
                        f"{'la página exacta' if single else 'las páginas revisadas'} "
                        f"(`{urlparse(target).netloc}`):\n")
                tail = ("\n\n¿Quieres que busque episodios con el mismo nombre o similares en este dominio, "
                        "o que exporte los enlaces (json.gz/csv)?" if not do_similar else "")
                return BotReply(head + self._fmt_records(all_records) + related_note + tail,
                                records=all_records, related=self.ctx.related,
                                status=f"{n_iframe} embed(s) encontrados")
            return BotReply("La página cargó, pero **no contiene ningún `<iframe>`** con `src` válido. "
                            "Puede que el reproductor se inyecte con JavaScript (esta versión lee el HTML inicial) "
                            "o que el embed esté en otra página del mismo título." + related_note,
                            records=all_records, related=self.ctx.related, status="Sin iframes en la página")

    # atajo para la GUI: fijar el título buscado
    def set_query(self, query: str):
        if query.strip():
            self.ctx.last_query = query.strip()
