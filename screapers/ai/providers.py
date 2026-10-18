"""Proveedores de IA: local (offline, por defecto) y API opcional.

Sin clave: todo funciona en local con heurísticas — ningún dato sale de
tu máquina. Con SCREAPERS_AI_API_KEY se usa una API compatible con
OpenAI, enviando solo texto ya redactado (sin secretos).
"""
from __future__ import annotations

import json
import urllib.request

from ..security import redact_text


class BaseProvider:
    name = "base"

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class LocalProvider(BaseProvider):
    """Marcador: los bots usan sus heurísticas locales."""
    name = "local"


class OpenAICompatibleProvider(BaseProvider):
    name = "openai-compatible"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini",
                 base_url: str = "https://api.openai.com/v1"):
        self.api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": redact_text(user)[:8000]}],
            "temperature": 0.2,
        }).encode()
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=payload, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]


def get_provider(settings) -> BaseProvider:
    if getattr(settings, "ai_api_key", None):
        return OpenAICompatibleProvider(settings.ai_api_key, settings.ai_model)
    return LocalProvider()
