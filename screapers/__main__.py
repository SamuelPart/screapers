"""Arranque: `python -m screapers` abre la interfaz de escritorio.

Sin terminal para el usuario final: el acceso directo de Linux llama a
este módulo. `--selftest` verifica el núcleo sin interfaz (para CI).
"""
from __future__ import annotations

import sys


def _selftest() -> int:
    from .ai.bots import AIBots
    from .config import get_settings
    from .datasets import DatasetStore, to_csv
    from .parser import parse_page
    from .security import AuditLog, mask_records, redact_text
    import tempfile
    from pathlib import Path

    page = parse_page('<html><head><title>T</title></head><body>'
                      '<h1>Hola</h1><a href="/a">Ir a A</a><p>test@example.com 612345678</p>'
                      '</body></html>', "https://example.org/")
    assert page["titulo"] == "T" and page["records"]
    assert mask_records([{"e": "test@example.com"}])[0]["e"].startswith("t***@")
    assert "test@" not in redact_text("Authorization: Bearer abcdefgh123456")
    bots = AIBots(get_settings())
    assert bots.clean_records([{"a": " 1 "}, {"a": "1"}]) == [{"a": "1"}]
    with tempfile.TemporaryDirectory() as td:
        store = DatasetStore(Path(td))
        store.save("demo", [{"a": 1}])
        assert store.load("demo") == [{"a": 1}]
        log = AuditLog(Path(td) / "audit.log")
        log.append("test")
        assert log.verify()
    assert to_csv([{"a": 1}]).startswith(b"\xef\xbb\xbf")
    print("selftest OK")
    return 0


def _gui_smoke() -> int:
    """Abre y cierra la ventana sin mainloop (para CI con Xvfb)."""
    from .desktop import App
    app = App()
    app.update_idletasks()
    app.update()
    app.destroy()
    print("gui-smoke OK")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    if "--gui-smoke" in argv:
        return _gui_smoke()
    try:
        from .desktop import main as gui_main
    except ModuleNotFoundError as e:
        if "tkinter" in str(e):
            print("Falta la interfaz gráfica. Instálala con:\n"
                  "  sudo apt install python3-tk\n"
                  "o reinstala Screapers con ./install.sh", file=sys.stderr)
            return 1
        raise
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
