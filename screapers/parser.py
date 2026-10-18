"""Parser HTML con solo la biblioteca estándar (árbol DOM mínimo)."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

VOID = {"br", "img", "hr", "meta", "link", "input", "area", "base", "col", "embed", "source", "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "text_parts", "parent")

    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children: list[Node] = []
        self.text_parts: list[str] = []

    def text(self) -> str:
        parts = list(self.text_parts)
        for c in self.children:
            parts.append(c.text())
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {})
        self.stack = [self.root]
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs, self.stack[-1]))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack[-1].tag in ("script", "style"):
            if self.stack[-1].tag == "script":
                self.scripts.append(data)
            return
        if data.strip():
            self.stack[-1].text_parts.append(data)


def _matches(node: Node, selector: str) -> bool:
    """Selectores simples: tag · .clase · #id · tag.clase · tag#id"""
    sel = selector.strip()
    if not sel:
        return False
    tag = cls = idv = None
    if sel.startswith("."):
        cls = sel[1:]
    elif sel.startswith("#"):
        idv = sel[1:]
    elif "." in sel:
        tag, cls = sel.split(".", 1)
    elif "#" in sel:
        tag, idv = sel.split("#", 1)
    else:
        tag = sel
    if tag and node.tag != tag.lower():
        return False
    if cls and cls not in (node.attrs.get("class") or "").split():
        return False
    if idv and node.attrs.get("id") != idv:
        return False
    return True


def extract_embeds(nodes, scripts, base_url: str) -> list[dict]:
    """Todo lo embebible que la página expone (streaming)."""
    embeds, seen = [], set()

    def add(tipo, url, extra=None):
        if not url:
            return
        url = urljoin(base_url, url)
        if url in seen or not url.startswith(("http://", "https://")):
            return
        seen.add(url)
        rec = {"tipo": tipo, "embed_url": url, "dominio": urlparse(url).netloc}
        if extra:
            rec.update(extra)
        embeds.append(rec)

    for n in nodes:
        attrs = n.attrs
        if n.tag == "iframe" and attrs.get("src"):
            add("iframe", attrs["src"], {"titulo_iframe": attrs.get("title", "")})
        elif n.tag == "embed" and attrs.get("src"):
            add("embed", attrs["src"])
        elif n.tag == "object" and attrs.get("data"):
            add("object", attrs["data"])
        elif n.tag == "video":
            if attrs.get("src"):
                add("video", attrs["src"], {"poster": attrs.get("poster", "")})
            for c in n.children:
                if c.tag == "source" and c.attrs.get("src"):
                    add("video", c.attrs["src"], {"formato": c.attrs.get("type", "")})
        elif n.tag == "meta":
            prop = (attrs.get("property") or attrs.get("name") or "").lower()
            if prop in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player"):
                add("meta-" + prop.split(":")[-1], attrs.get("content", ""))
        elif n.tag == "link":
            rel = (attrs.get("rel") or "").lower()
            if attrs.get("type") == "application/json+oembed" or "alternate" in rel:
                if attrs.get("href") and "oembed" in (attrs.get("href") or ""):
                    add("oembed", attrs["href"])
    return embeds


def parse_page(html: str, base_url: str, selector: str = "", want_embeds: bool = False,
               iframe_only: bool = False) -> dict:
    b = _Builder()
    try:
        b.feed(html or "")
    except Exception:
        pass
    nodes = list(b.root.walk())

    def all_text(tag):
        return [n.text() for n in nodes if n.tag == tag and n.text()]

    title_node = next((n for n in nodes if n.tag == "title"), None)
    meta_desc = next((n.attrs.get("content", "") for n in nodes
                      if n.tag == "meta" and (n.attrs.get("name", "").lower() == "description")), "")

    links, seen = [], set()
    for n in nodes:
        if n.tag == "a" and n.attrs.get("href"):
            u = urljoin(base_url, n.attrs["href"])
            if u not in seen and u.startswith(("http://", "https://")):
                seen.add(u)
                links.append({"texto": n.text()[:120], "url": u})

    tables = []
    for t in (n for n in nodes if n.tag == "table"):
        rows = []
        for tr in (x for x in t.walk() if x.tag == "tr"):
            cells = [c.text() for c in tr.children if c.tag in ("td", "th")]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)

    json_ld = []
    for s in b.scripts:
        s = s.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                json_ld.append(json.loads(s))
            except Exception:
                pass

    embeds = extract_embeds(nodes, b.scripts, base_url)
    for item in json_ld:
        items = item if isinstance(item, list) else [item]
        for it in items:
            if isinstance(it, dict) and "VideoObject" in str(it.get("@type", "")):
                for key in ("embedUrl", "contentUrl"):
                    if it.get(key):
                        u = urljoin(base_url, it[key])
                        if all(e["embed_url"] != u for e in embeds):
                            embeds.append({"tipo": "jsonld-video", "embed_url": u,
                                           "dominio": urlparse(u).netloc,
                                           "nombre": str(it.get("name", ""))[:120]})

    if want_embeds or iframe_only:
        # El buscador dirigido aporta también los iframes ocultos/diferidos
        from .iframe_finder import find_iframes
        _, hidden = find_iframes(html, base_url)
        if iframe_only:
            embeds = hidden
        else:
            known = {e["embed_url"] for e in embeds}
            embeds = embeds + [h for h in hidden if h["embed_url"] not in known]

    records: list[dict] = []
    if want_embeds:
        title_txt = title_node.text() if title_node else ""
        records = [{**e, "pagina": title_txt, "fuente_pagina": base_url} for e in embeds]
    if selector:
        for n in nodes:
            if _matches(n, selector):
                rec = {"texto": n.text()[:500]}
                if n.tag == "a":
                    rec["url"] = urljoin(base_url, n.attrs.get("href", ""))
                for attr in ("href", "src", "title", "alt"):
                    if n.attrs.get(attr):
                        rec[attr] = n.attrs[attr]
                if rec["texto"] or len(rec) > 1:
                    records.append(rec)
    if not records and not want_embeds:  # registros por defecto: enlaces + tablas
        records = [{"texto": l["texto"], "url": l["url"]} for l in links if l["texto"]]
        for table in tables:
            if len(table) > 1:
                head = table[0]
                for row in table[1:]:
                    records.append({head[i] if i < len(head) else f"col{i+1}": row[i]
                                      for i in range(min(len(row), len(head) or len(row)))})

    return {
        "url": base_url,
        "titulo": title_node.text() if title_node else "",
        "descripcion": meta_desc,
        "encabezados": all_text("h1") + all_text("h2"),
        "parrafos": [p for p in all_text("p") if len(p) > 40][:30],
        "enlaces": links,
        "tablas": tables,
        "json_ld": json_ld,
        "embeds": embeds,
        "records": records,
    }
