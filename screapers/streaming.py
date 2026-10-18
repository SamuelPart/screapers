"""Centro de streaming: órdenes en lenguaje natural, embeds y relacionados.

El bot interpreta lo que escribes (ej. «quiero extraer el enlace del embed
de esta serie y buscar episodios con el mismo nombre») y lo convierte en un
plan que el motor obedece. Todo local, sin enviar tu orden a ningún sitio.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import quote_plus, urljoin, urlparse

_EMBED_WORDS = ("embed", "iframe", "reproductor", "player", "enlace del video",
                "enlace del vídeo", "url del video", "ver online", "streaming")
_SERIES_WORDS = ("serie", "series", "episodio", "episodios", "capitulo", "capítulo",
                 "capitulos", "temporada", "temporadas", "season")
_MOVIE_WORDS = ("pelicula", "película", "peliculas", "movie", "film", "cine")
_SEARCH_WORDS = ("buscar", "busca", "busqueda", "búsqueda", "mismo nombre", "similar",
                 "similares", "relacionado", "relacionados", "mismo titulo", "mismo título")
_EP_RE = re.compile(r"(?i)\b(?:s(\d{1,2})\s?e(\d{1,3})|temporada\s*(\d{1,2}).{0,20}?"
                    r"(?:episodio|cap[ií]tulo)\s*(\d{1,3})|(?:episodio|cap[ií]tulo)\s*(\d{1,3}))\b")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def base_title(text: str) -> str:
    """Título sin coletillas de episodio/temporada/calidad."""
    t = normalize(text)
    t = _EP_RE.sub("", t)
    t = re.sub(r"\b(temporada|season|episodio|capitulo|hd|720p|1080p|4k|online|ver|sub|latino|castellano)\b", "", t)
    return re.sub(r"\s+", " ", t).strip(" -|")


def episode_info(text: str) -> dict:
    m = _EP_RE.search(text or "")
    if not m:
        return {}
    season = m.group(1) or m.group(3)
    episode = m.group(2) or m.group(4) or m.group(5)
    info = {}
    if season:
        info["temporada"] = int(season)
    if episode:
        info["episodio"] = int(episode)
    return info


@dataclass
class TaskPlan:
    instruction: str = ""
    intent: str = "general"            # general | embed | enlaces | tablas | texto
    media_type: str = "auto"           # auto | serie | pelicula
    query: str = ""                    # título a buscar dentro del dominio
    search_in_site: bool = False       # buscar iguales/similares en el dominio
    follow_related: bool = False       # entrar en los relacionados encontrados
    group_episodes: bool = False

    def describe(self) -> list[str]:
        lines = ["🧭 Plan que obedecerá el bot:"]
        objetivo = {"embed": "extraer los enlaces de embed/reproductor de vídeo",
                    "enlaces": "extraer los enlaces", "tablas": "extraer las tablas",
                    "texto": "extraer el texto", "general": "extraer el contenido general"}[self.intent]
        lines.append(f"  1) Objetivo: {objetivo}.")
        if self.media_type != "auto":
            lines.append(f"  2) Tipo: {'serie (con temporadas/episodios)' if self.media_type == 'serie' else 'película'}.")
        if self.search_in_site:
            lines.append(f"  • Buscar en el mismo dominio títulos iguales o similares"
                         + (f" a «{self.query}»." if self.query else "."))
        if self.follow_related:
            lines.append("  • Entrar en cada relacionado y aplicarle el mismo objetivo.")
        if self.group_episodes:
            lines.append("  • Agrupar y ordenar por temporada/episodio.")
        if self.intent == "general" and self.media_type == "auto" and not self.search_in_site:
            lines.append("  (Orden genérica: escribe por ejemplo «extrae el embed de esta serie "
                         "y busca episodios con el mismo nombre».)")
        return lines


def _quoted(text: str) -> str:
    m = re.search(r"[\"'«]([^\"'»]{2,80})[\"'»]", text)
    return m.group(1).strip() if m else ""


def parse_instruction(instruction: str, title_input: str = "") -> TaskPlan:
    raw = (instruction or "").strip()
    low = normalize(raw)
    plan = TaskPlan(instruction=raw)

    if any(w in low for w in _EMBED_WORDS) or "embed" in low:
        plan.intent = "embed"
    elif any(w in low for w in ("tabla", "tablas", "precios", "listado")):
        plan.intent = "tablas"
    elif any(w in low for w in ("enlace", "enlaces", "link", "links", "url", "urls")):
        plan.intent = "enlaces"
    elif any(w in low for w in ("texto", "resumen", "resumir", "contenido")):
        plan.intent = "texto"

    if any(w in low for w in _SERIES_WORDS):
        plan.media_type = "serie"
        plan.group_episodes = True
    elif any(w in low for w in _MOVIE_WORDS):
        plan.media_type = "pelicula"

    plan.search_in_site = any(w in low for w in _SEARCH_WORDS) or bool(title_input.strip())
    if plan.media_type == "serie":
        plan.search_in_site = plan.search_in_site or any(
            w in low for w in ("episodio", "temporada", "nombre"))
    plan.follow_related = plan.search_in_site and any(
        w in low for w in ("entra", "entrar", "abre", "abrir", "sigue", "seguir", "todos", "cada", "extrae", "extraer"))
    if plan.intent == "embed" and plan.search_in_site:
        plan.follow_related = True  # buscar embeds suele implicar abrir los relacionados

    plan.query = (title_input or "").strip() or _quoted(raw)
    if not plan.query:
        m = re.search(r"(?i)(?:de|serie|pelicula|película|buscar|llamada|titulada)\s+"
                      r"([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑñ'’\- ]{2,50})", raw)
        if m:
            plan.query = m.group(1).strip()
    return plan


def similarity(a: str, b: str) -> float:
    na, nb = base_title(a), base_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.92
    token = len(set(na.split()) & set(nb.split())) / max(1, len(set(na.split()) | set(nb.split())))
    return max(SequenceMatcher(None, na, nb).ratio(), token)


def find_related(links: list[dict], query: str, threshold: float = 0.45, limit: int = 25) -> list[dict]:
    """Enlaces del mismo dominio con título igual o similar a `query`."""
    found = []
    for link in links:
        text = link.get("texto", "")
        slug = urlparse(link.get("url", "")).path.replace("-", " ").replace("_", " ").replace("/", " ")
        score = max(similarity(text, query), similarity(slug, query))
        if score >= threshold:
            info = episode_info(text + " " + slug)
            found.append({**link, "similitud": round(score, 2), **info})
    found.sort(key=lambda r: (-r["similitud"], r.get("temporada", 0), r.get("episodio", 0), r["url"]))
    seen, out = set(), []
    for f in found:
        if f["url"] not in seen:
            seen.add(f["url"])
            out.append(f)
    return out[:limit]


def group_episodes(related: list[dict]) -> str:
    if not related:
        return "Sin títulos relacionados encontrados en las páginas visitadas."
    seasons: dict[int, list[dict]] = {}
    others = []
    for r in related:
        (seasons.setdefault(r["temporada"], []) if "temporada" in r else others).append(r)
    lines = [f"🎬 Relacionados: {len(related)} título(s) igual(es)/similar(es)."]
    for s in sorted(seasons):
        eps = sorted(seasons[s], key=lambda r: r.get("episodio", 0))
        lines.append(f"  Temporada {s}: {len(eps)} episodio(s)"
                     + (f" (del {eps[0].get('episodio', '?')} al {eps[-1].get('episodio', '?')})" if eps else ""))
    if others:
        lines.append(f"  Sin episodio detectado: {len(others)} (películas o especiales)")
    return "\n".join(lines)


def search_candidates(base_url: str, query: str) -> list[str]:
    """Buscadores internos habituales (WordPress y genéricos)."""
    p = urlparse(base_url)
    root = f"{p.scheme}://{p.netloc}/"
    q = quote_plus(query)
    return [urljoin(root, f"?s={q}"), urljoin(root, f"search?q={q}"),
            urljoin(root, f"buscar?q={q}"), urljoin(root, f"search/{quote_plus(query.replace(' ', '-'))}/")]
