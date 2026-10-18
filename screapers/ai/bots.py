"""Bots de IA que asisten al scraping (locales por defecto).

- ScoutBot   : analiza la página y sugiere qué extraer.
- CleanerBot : limpia, deduplica y normaliza registros.
- AnalystBot : infiere tipos y resume los datos.
Si hay proveedor de nube, enriquece el análisis; si falla, se sigue en local.
"""
from __future__ import annotations

import re
from collections import Counter

from ..security import mask_records, mask_value
from .providers import BaseProvider, LocalProvider, get_provider

_PRICE = re.compile(r"^\$?\s?[\d.,]+\s?(€|EUR|USD|S/|PEN)?$", re.I)
_DATE = re.compile(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$")
_URL = re.compile(r"^https?://")
_EMAIL = re.compile(r"@")
_NUMBER = re.compile(r"^-?[\d.,]+$")


class ScoutBot:
    def analyze(self, page: dict) -> list[str]:
        tips = []
        if page.get("tablas"):
            tips.append(f"📊 Hay {len(page['tablas'])} tabla(s): ya convertí sus filas en registros.")
        if page.get("json_ld"):
            tips.append("🧩 La página trae datos estructurados (JSON-LD) legibles por máquinas.")
        n_links = len(page.get("enlaces", []))
        tips.append(f"🔗 {n_links} enlaces: sube «Profundidad» a 1–2 para seguir los del mismo dominio.")
        if any("precio" in (page.get("titulo", "") + " ".join(page.get("encabezados", []))).lower()
               or "$" in p or "€" in p for p in page.get("parrafos", [])[:5]):
            tips.append("💲 Parece haber precios: revisa la columna de importes tras la limpieza del CleanerBot.")
        if not tips:
            tips.append("Usa un selector simple (ej. `a`, `.producto`, `#lista`, `article`) para afinar la extracción.")
        return tips


class CleanerBot:
    def clean(self, records: list[dict], mask_pii: bool = True) -> list[dict]:
        seen, out = set(), []
        for r in records:
            clean = {}
            for k, v in r.items():
                key = re.sub(r"\s+", " ", str(k)).strip().lower()
                val = re.sub(r"\s+", " ", str(v)).strip() if isinstance(v, str) else v
                if isinstance(val, str) and (_PRICE.match(val) or _NUMBER.match(val)):
                    val = re.sub(r"[^\d.,-]", "", val)
                clean[key] = val
            sig = json_sig(clean)
            if sig not in seen and any(str(v).strip() for v in clean.values()):
                seen.add(sig)
                out.append(clean)
        return mask_records(out) if mask_pii else out


class AnalystBot:
    def infer_schema(self, records: list[dict]) -> dict[str, str]:
        schema: dict[str, Counter] = {}
        for r in records[:200]:
            for k, v in r.items():
                t = self._type(str(v))
                schema.setdefault(k, Counter())[t] += 1
        return {k: c.most_common(1)[0][0] for k, c in schema.items()}

    @staticmethod
    def _type(v: str) -> str:
        if _URL.match(v):
            return "url"
        if _EMAIL.search(v):
            return "email"
        if _DATE.match(v):
            return "fecha"
        if _PRICE.match(v):
            return "precio/número"
        if _NUMBER.match(v):
            return "número"
        return "texto" if len(v) > 3 else "—"

    def summarize(self, page: dict, records: list[dict]) -> str:
        text = " ".join(page.get("parrafos", []))
        words = [w.lower() for w in re.findall(r"[a-záéíóúñ]{4,}", text)]
        top = ", ".join(w for w, _ in Counter(words).most_common(6))
        return (f"{page.get('titulo') or 'Página'}: {len(records)} registros. "
                f"Temas frecuentes: {top or '—'}.")


def json_sig(record: dict) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(record.items()))


class AIBots:
    """Orquestador usado por la interfaz."""

    def __init__(self, settings):
        self.settings = settings
        self.provider: BaseProvider = get_provider(settings)
        self.scout, self.cleaner, self.analyst = ScoutBot(), CleanerBot(), AnalystBot()

    @property
    def mode(self) -> str:
        return "local (privado, sin enviar datos)" if isinstance(self.provider, LocalProvider) \
            else "nube (API, con texto redactado)"

    def analyze_page(self, page: dict, records: list[dict]) -> dict:
        result = {
            "sugerencias": self.scout.analyze(page),
            "resumen": self.analyst.summarize(page, records),
            "esquema": self.analyst.infer_schema(records),
            "modo_ia": self.mode,
        }
        if not isinstance(self.provider, LocalProvider) and self.settings.use_ai:
            try:
                extra = self.provider.complete(
                    "Eres un asistente de scraping. Responde breve en español.",
                    f"Resume en 2 frases qué datos útiles se pueden extraer de esta página:\n"
                    f"Título: {page.get('titulo')}\n{result['resumen']}")
                result["resumen_ia"] = mask_value(extra.strip())
            except Exception as e:
                result["resumen_ia"] = f"(IA en nube no disponible: {e}. Siguiendo en local.)"
        return result

    def clean_records(self, records: list[dict]) -> list[dict]:
        return self.cleaner.clean(records, mask_pii=self.settings.mask_pii)
