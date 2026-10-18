"""Seguridad: redacción de secretos, máscara de PII, anti-SSRF y auditoría."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

# --------------------------- Secretos ---------------------------
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),  # JWT
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                  # AWS
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),                        # GitHub
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),                      # Slack
    re.compile(r"\bsk-(?:live|test)_[A-Za-z0-9]{10,}\b"),                # Stripe
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),                               # OpenAI-like
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@"),        # user:pass@
    re.compile(r"(?i)\b(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*\S+"),
]


def redact_text(text: str) -> str:
    if not text:
        return text
    out = text
    for i, pat in enumerate(_SECRET_PATTERNS):
        if i == 8:
            out = pat.sub(r"\1***:***@", out)
        elif i == 9:
            out = pat.sub(lambda m: f"{m.group(1)}=***", out)
        elif i == 6:
            out = pat.sub("Bearer ***", out)
        else:
            out = pat.sub("***REDACTED***", out)
    return out


# ------------------------------ PII ------------------------------
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE = re.compile(r"\b(?:\+?\d[\s.-]?){9,15}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DNI = re.compile(r"\b\d{8}[A-HJ-NP-TV-Z]\b", re.I)


def _luhn_ok(num: str) -> bool:
    digits = [int(c) for c in num if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total, alt = 0, False
    for d in reversed(digits):
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _mask_card(m: re.Match) -> str:
    return "**** **** **** " + re.sub(r"\D", "", m.group(0))[-4:] if _luhn_ok(m.group(0)) else m.group(0)


def mask_value(value):
    if not isinstance(value, str):
        return value
    out = _EMAIL.sub(lambda m: m.group(0)[0] + "***@" + m.group(0).split("@")[-1], value)
    out = _CARD.sub(_mask_card, out)
    out = _DNI.sub("*********", out)
    out = _PHONE.sub(lambda m: "***" + re.sub(r"\D", "", m.group(0))[-3:]
                     if len(re.sub(r"\D", "", m.group(0))) >= 9 else m.group(0), out)
    out = _IPV4.sub(lambda m: m.group(0).rsplit(".", 1)[0] + ".***", out)
    return out


def mask_records(records: list[dict]) -> list[dict]:
    return [{k: mask_value(v) for k, v in r.items()} for r in records]


# ----------------------------- Anti-SSRF -----------------------------
def resolve_host(host: str) -> list[str]:
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(host, None)})
    except Exception:
        return []


def assert_safe_url(url: str, allow_private: bool = False) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError("Solo se permiten URLs http:// o https://")
    if p.username or p.password:
        raise ValueError("La URL no debe contener usuario/contraseña")
    if not p.hostname:
        raise ValueError("URL sin dominio")
    if not allow_private:
        for ip_str in resolve_host(p.hostname):
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ValueError(
                    f"Bloqueado por seguridad (anti-SSRF): {p.hostname} → {ip_str} es red privada/local. "
                    "Activa «Permitir red local» solo si confías en el destino.")
    return url


def safe_join(base: Path, *parts: str) -> Path:
    target = (base.joinpath(*parts)).resolve()
    if base.resolve() not in target.parents and target != base.resolve():
        raise ValueError("Ruta fuera del directorio permitido")
    return target


# ---------------------------- Auditoría ----------------------------
class AuditLog:
    """Registro append-only con cadena SHA-256 verificable."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        try:
            lines = self.path.read_text(encoding="utf-8").strip().splitlines()
            return json.loads(lines[-1])["hash"] if lines else "GENESIS"
        except Exception:
            return "GENESIS"

    def append(self, event: str, detail: str = "") -> dict:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
            "detail": redact_text(str(detail))[:500],
            "prev": self._last_hash(),
        }
        entry["hash"] = hashlib.sha256(
            (entry["prev"] + entry["ts"] + entry["event"] + entry["detail"]).encode()).hexdigest()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def verify(self) -> bool:
        prev = "GENESIS"
        try:
            for line in self.path.read_text(encoding="utf-8").strip().splitlines():
                if not line.strip():
                    continue
                e = json.loads(line)
                expect = hashlib.sha256(
                    (e["prev"] + e["ts"] + e["event"] + e["detail"]).encode()).hexdigest()
                if e["prev"] != prev or e["hash"] != expect:
                    return False
                prev = e["hash"]
            return True
        except Exception:
            return False

    def tail(self, n: int = 50) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").strip().splitlines()[-n:]
            return [json.loads(x) for x in lines if x.strip()]
        except Exception:
            return []
