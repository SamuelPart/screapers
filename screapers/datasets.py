"""Almacén de datasets y exportación: CSV, JSON, JSONL, XLSX, SQLite."""
from __future__ import annotations

import csv
import gzip
import io
import json
import sqlite3
from pathlib import Path

from .config import xdg_data
from .security import safe_join

FORMATS = ("csv", "json", "jsonl", "csv.gz", "json.gz", "xlsx", "sqlite")


def _columns(records: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in records:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def to_csv(records: list[dict]) -> bytes:
    buf = io.StringIO()
    cols = _columns(records)
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in records:
        w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM utf-8-sig para Excel


def to_json(records: list[dict]) -> bytes:
    return json.dumps(records, indent=2, ensure_ascii=False).encode("utf-8")


def to_jsonl(records: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf-8")


def to_xlsx(records: list[dict]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("Para XLSX instala: pip install openpyxl (o exporta en CSV)") from exc
    wb = Workbook()
    ws = wb.active
    ws.title = "datos"
    cols = _columns(records)
    ws.append(cols)
    for r in records:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_sqlite(records: list[dict], path: Path) -> Path:
    cols = _columns(records) or ["valor"]
    path = Path(path)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        cols_sql = ", ".join(f'"{c}" TEXT' for c in cols)
        con.execute(f'CREATE TABLE datos ({cols_sql})')
        marks = ", ".join("?" for _ in cols)
        con.executemany(
            f"INSERT INTO datos VALUES ({marks})",
            [[json.dumps(r.get(c), ensure_ascii=False) if isinstance(r.get(c), (list, dict)) else r.get(c, "")
              for c in cols] for r in records])
        con.commit()
    finally:
        con.close()
    return path


class DatasetStore:
    def __init__(self, base: Path | None = None):
        self.base = Path(base) if base else xdg_data() / "datasets"
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, records: list[dict]) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_") or "dataset"
        path = safe_join(self.base, f"{safe}.json")
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.base.glob("*.json"))

    def load(self, name: str) -> list[dict]:
        path = safe_join(self.base, f"{name}.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, name: str) -> None:
        safe_join(self.base, f"{name}.json").unlink(missing_ok=True)

    def export(self, records: list[dict], fmt: str, dest: Path) -> Path:
        fmt = fmt.lower()
        if fmt not in FORMATS:
            raise ValueError(f"Formato no soportado: {fmt} (usa {', '.join(FORMATS)})")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "sqlite":
            return to_sqlite(records, dest)
        if fmt.endswith(".gz"):  # comprimido: ideal para miles de embeds/enlaces
            raw = {"csv.gz": to_csv, "json.gz": to_json}[fmt](records)
            dest.write_bytes(gzip.compress(raw, compresslevel=9))
            return dest
        data = {"csv": to_csv, "json": to_json, "jsonl": to_jsonl, "xlsx": to_xlsx}[fmt](records)
        dest.write_bytes(data)
        return dest
