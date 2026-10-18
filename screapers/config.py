"""Configuración (XDG) — sin dependencias externas.

Las claves secretas (API key, credenciales de proxy) NUNCA se guardan en
disco: solo se leen de variables de entorno y se muestran enmascaradas.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP = "screapers"

# Claves que sí pueden persistir en config.json (nada sensible).
PERSISTED = (
    "delay_min", "delay_max", "timeout", "max_pages", "max_depth",
    "respect_robots", "mask_pii", "allow_private", "use_ai",
    "export_format", "ai_model",
)


def xdg_config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP


def xdg_data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP


def mask_proxy(proxy: str | None) -> str:
    if not proxy:
        return ""
    if "@" in proxy and "://" in proxy:
        scheme, rest = proxy.split("://", 1)
        host = rest.rsplit("@", 1)[-1]
        return f"{scheme}://***:***@{host}"
    return proxy


@dataclass
class Settings:
    delay_min: float = 1.0          # pausa mínima entre peticiones (s)
    delay_max: float = 2.5          # pausa máxima (jitter anti-bloqueo)
    timeout: float = 20.0
    max_pages: int = 25
    max_depth: int = 1
    respect_robots: bool = True
    mask_pii: bool = True
    allow_private: bool = False     # permitir IP privadas/locales (SSRF)
    use_ai: bool = True
    export_format: str = "csv"
    ai_model: str = "gpt-4o-mini"
    # Sensibles: solo memoria / entorno, jamás persistidos.
    proxy: str | None = field(default=None, repr=False)
    ai_api_key: str | None = field(default=None, repr=False)

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        cfg = xdg_config() / "config.json"
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            for k in PERSISTED:
                if k in data:
                    setattr(s, k, data[k])
        except Exception:
            pass
        s.proxy = os.environ.get("SCREAPERS_PROXY") or s.proxy
        s.ai_api_key = os.environ.get("SCREAPERS_AI_API_KEY") or s.ai_api_key
        if os.environ.get("SCREAPERS_ALLOW_PRIVATE") == "1":
            s.allow_private = True
        s._coherencia()
        return s

    def _coherencia(self) -> None:
        if self.delay_max < self.delay_min:
            self.delay_max = self.delay_min
        self.max_pages = max(1, min(int(self.max_pages), 500))
        self.max_depth = max(0, min(int(self.max_depth), 5))
        self.timeout = max(3.0, min(float(self.timeout), 120.0))

    def save_overrides(self) -> Path:
        self._coherencia()
        cfg_dir = xdg_config()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        data = {k: getattr(self, k) for k in PERSISTED}
        path = cfg_dir / "config.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def public_view(self) -> dict:
        d = {k: getattr(self, k) for k in PERSISTED}
        d["proxy"] = mask_proxy(self.proxy)
        d["ai_api_key"] = "••••••••" if self.ai_api_key else ""
        d["ai_mode"] = "nube (API)" if self.ai_api_key else "local (sin clave)"
        d["data_dir"] = str(xdg_data())
        return d


_cache: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _cache
    if _cache is None or reload:
        _cache = Settings.load()
    return _cache
