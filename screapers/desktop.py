"""Interfaz de escritorio (Tkinter/ttk) — simple, limpia y sin terminal."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .ai.bots import AIBots
from .config import get_settings, xdg_data
from .datasets import FORMATS, DatasetStore
from .scraper import Scraper
from .security import AuditLog, redact_text

BG, CARD, ACCENT, TXT = "#f4f6fb", "#ffffff", "#2563eb", "#1e293b"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Screapers {__version__} — Scraping web con IA")
        self.geometry("1080x720")
        self.minsize(880, 560)
        self.configure(bg=BG)
        self.settings = get_settings()
        self.store = DatasetStore()
        self.audit = AuditLog(xdg_data() / "audit.log")
        self.bots = AIBots(self.settings)
        self.records: list[dict] = []
        self.queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._style()
        self._build()
        self.after(120, self._drain)
        self.audit.append("app_start", f"modo IA: {self.bots.mode}")

    # ---------------------------------------------------------- UI
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=TXT, font=("Sans", 10))
        s.configure("Card.TLabel", background=CARD, foreground=TXT, font=("Sans", 10))
        s.configure("Title.TLabel", background=BG, foreground=TXT, font=("Sans", 17, "bold"))
        s.configure("Sub.TLabel", background=BG, foreground="#64748b", font=("Sans", 9))
        s.configure("Accent.TButton", background=ACCENT, foreground="white", font=("Sans", 10, "bold"), padding=8)
        s.map("Accent.TButton", background=[("active", "#1d4ed8")])
        s.configure("TButton", padding=7)
        s.configure("Treeview", rowheight=24, font=("Sans", 9))

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(14, 4))
        ttk.Label(head, text="🕷  Screapers", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=f"IA: {self.bots.mode}", style="Sub.TLabel").pack(side="right")

        ttk.Label(self, text="Extrae datos de sitios web de forma educada y segura: respeta robots.txt, "
                             "va despacio para no ser bloqueado y enmascara datos personales.",
                  style="Sub.TLabel", wraplength=1020).pack(fill="x", padx=18)

        bar = ttk.Frame(self, style="Card.TFrame")
        bar.pack(fill="x", padx=18, pady=10)
        ttk.Label(bar, text="URL:", style="Card.TLabel").grid(row=0, column=0, padx=(12, 4), pady=12)
        self.url_var = tk.StringVar(value="https://example.org")
        ttk.Entry(bar, textvariable=self.url_var, width=62).grid(row=0, column=1, sticky="ew", pady=12)
        ttk.Label(bar, text="Selector (opcional):", style="Card.TLabel").grid(row=0, column=2, padx=(14, 4))
        self.selector_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.selector_var, width=16).grid(row=0, column=3, pady=12)
        self.btn_start = ttk.Button(bar, text="▶  Iniciar", style="Accent.TButton", command=self.start)
        self.btn_start.grid(row=0, column=4, padx=(14, 6), pady=10)
        ttk.Button(bar, text="■ Detener", command=self.stop).grid(row=0, column=5, padx=(0, 12), pady=10)
        bar.columnconfigure(1, weight=1)

        opts = ttk.Frame(self, style="Card.TFrame")
        opts.pack(fill="x", padx=18, pady=(0, 10))
        self.max_pages = tk.IntVar(value=self.settings.max_pages)
        self.max_depth = tk.IntVar(value=self.settings.max_depth)
        self.delay_min = tk.DoubleVar(value=self.settings.delay_min)
        self.respect = tk.BooleanVar(value=self.settings.respect_robots)
        self.mask = tk.BooleanVar(value=self.settings.mask_pii)
        self.allow_priv = tk.BooleanVar(value=self.settings.allow_private)
        for col, (label, var, w) in enumerate([
                ("Máx. páginas", self.max_pages, 5), ("Profundidad", self.max_depth, 5),
                ("Pausa mín. (s)", self.delay_min, 5)]):
            ttk.Label(opts, text=label + ":", style="Card.TLabel").grid(row=0, column=col * 2, padx=(12, 2), pady=8)
            ttk.Spinbox(opts, textvariable=var, width=w, from_=0, to=500, increment=0.5 if var is self.delay_min else 1) \
                .grid(row=0, column=col * 2 + 1, pady=8)
        ttk.Checkbutton(opts, text="Respetar robots.txt", variable=self.respect).grid(row=0, column=6, padx=10)
        ttk.Checkbutton(opts, text="Ocultar datos personales (PII)", variable=self.mask).grid(row=0, column=7, padx=6)
        ttk.Checkbutton(opts, text="Permitir red local", variable=self.allow_priv).grid(row=0, column=8, padx=6)

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=18)
        self.status = tk.StringVar(value="Listo. Pega una URL y pulsa Iniciar.")
        ttk.Label(self, textvariable=self.status, style="Sub.TLabel").pack(fill="x", padx=18, pady=3)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=18, pady=(2, 8))
        f_res = ttk.Frame(nb); nb.add(f_res, text="  📋 Resultados  ")
        self.tree = ttk.Treeview(f_res, show="headings")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(f_res, command=self.tree.yview); sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        f_ai = ttk.Frame(nb); nb.add(f_ai, text="  🤖 Bots IA  ")
        self.ai_text = self._text_tab(f_ai)
        f_log = ttk.Frame(nb); nb.add(f_log, text="  🛡 Registro y seguridad  ")
        self.log_text = self._text_tab(f_log)

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Label(foot, text="Exportar:").pack(side="left")
        self.fmt_var = tk.StringVar(value=self.settings.export_format)
        ttk.Combobox(foot, textvariable=self.fmt_var, values=list(FORMATS), width=9, state="readonly").pack(side="left", padx=6)
        ttk.Button(foot, text="💾 Exportar datos", command=self.export).pack(side="left")
        ttk.Button(foot, text="🤖 Analizar con IA", command=self.analyze_ai).pack(side="left", padx=8)
        ttk.Button(foot, text="🔍 Ver auditoría", command=self.show_audit).pack(side="left")
        ttk.Button(foot, text="⚙ Guardar ajustes", command=self.save_settings).pack(side="right")

    @staticmethod
    def _text_tab(parent):
        txt = tk.Text(parent, wrap="word", font=("Sans", 9), bg="white", fg=TXT, relief="flat")
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        txt.configure(state="disabled")
        return txt

    # ------------------------------------------------------ acciones
    def _sync_settings(self):
        s = self.settings
        s.max_pages, s.max_depth = int(self.max_pages.get()), int(self.max_depth.get())
        s.delay_min = float(self.delay_min.get())
        s.respect_robots, s.mask_pii, s.allow_private = self.respect.get(), self.mask.get(), self.allow_priv.get()
        s.export_format = self.fmt_var.get()
        self.bots = AIBots(s)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        url = self.url_var.get().strip()
        if not url.startswith(("http://", "https://")):
            messagebox.showwarning("URL", "Escribe una URL válida que empiece por http:// o https://")
            return
        self._sync_settings()
        self.records = []
        self._fill_tree([])
        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Trabajando… (pausas educadas entre páginas para evitar bloqueos)")
        self.audit.append("scrape_start", url)
        self.worker = threading.Thread(target=self._run, args=(url, self.selector_var.get().strip()), daemon=True)
        self.worker.start()

    def _run(self, url, selector):
        try:
            scraper = Scraper(self.settings, log=lambda m: self.queue.put(("log", m)), stop=self.stop_event)
            pages, records = scraper.crawl(url, selector, on_page=lambda p, r: self.queue.put(("page", (p, r))))
            cleaned = self.bots.clean_records(records)
            self.store.save(url.split("//")[-1].split("/")[0] or "dataset", cleaned)
            self.queue.put(("done", (pages, cleaned)))
        except Exception as e:
            self.queue.put(("error", redact_text(str(e))))

    def stop(self):
        self.stop_event.set()
        self.status.set("Deteniendo…")

    def analyze_ai(self):
        if not getattr(self, "_last_page", None):
            messagebox.showinfo("Bots IA", "Primero extrae una página para que los bots puedan analizarla.")
            return
        info = self.bots.analyze_page(self._last_page, self.records)
        lines = [f"Modo IA: {info['modo_ia']}\n", "— Sugerencias del ScoutBot —", *info["sugerencias"],
                 "\n— Resumen (AnalystBot) —", info["resumen"]]
        if info.get("resumen_ia"):
            lines += ["\n— Resumen IA en nube —", info["resumen_ia"]]
        lines += ["\n— Esquema inferido —"] + [f"  • {k}: {v}" for k, v in info["esquema"].items()]
        self._set_text(self.ai_text, "\n".join(lines))

    def export(self):
        if not self.records:
            messagebox.showinfo("Exportar", "Todavía no hay datos para exportar.")
            return
        fmt = self.fmt_var.get()
        path = filedialog.asksaveasfilename(defaultextension=f".{fmt}",
                                            filetypes=[(fmt.upper(), f"*.{fmt}"), ("Todos", "*.*")])
        if not path:
            return
        try:
            out = self.store.export(self.records, fmt, Path(path))
            self.audit.append("export", f"{fmt} → {out.name} ({len(self.records)} registros)")
            self.status.set(f"Exportado: {out}  ·  {len(self.records)} registros")
        except Exception as e:
            messagebox.showerror("Exportar", redact_text(str(e)))

    def save_settings(self):
        self._sync_settings()
        path = self.settings.save_overrides()
        self.audit.append("settings_saved", str(path))
        self.status.set("Ajustes guardados (sin secretos: la clave IA/proxy solo viven en variables de entorno).")

    def show_audit(self):
        ok = self.audit.verify()
        lines = [f"Cadena de auditoría íntegra: {'SÍ ✓' if ok else 'NO ✗ — revisa el archivo'}", ""]
        lines += [f"{e['ts']}  {e['event']}: {e['detail']}" for e in self.audit.tail(40)]
        lines += ["", "Privacidad: ningún dato sale de tu equipo salvo que configures una clave de IA "
                        "(SCREAPERS_AI_API_KEY); aun así el texto se redacta antes de enviarse."]
        self._set_text(self.log_text, "\n".join(lines))

    # --------------------------------------------------------- cola
    def _drain(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._append(self.log_text, payload)
                    self.status.set(payload)
                elif kind == "page":
                    page, _ = payload
                    self._last_page = {k: v for k, v in page.items()}
                elif kind == "done":
                    pages, records = payload
                    self.records = records
                    self._fill_tree(records)
                    self.progress.stop()
                    self.btn_start.configure(state="normal")
                    self.status.set(f"Terminado: {pages} página(s), {len(records)} registros limpios y protegidos.")
                    self.audit.append("scrape_done", f"{pages} páginas, {len(records)} registros")
                    self.analyze_ai()
                elif kind == "error":
                    self.progress.stop()
                    self.btn_start.configure(state="normal")
                    self.status.set("Error — revisa la pestaña de registro.")
                    self._append(self.log_text, "✗ " + payload)
                    messagebox.showerror("Screapers", payload)
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _fill_tree(self, records: list[dict]):
        cols = []
        for r in records:
            for k in r:
                if k not in cols:
                    cols.append(k)
        cols = cols[:8]
        self.tree.configure(columns=cols)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=170)
        self.tree.delete(*self.tree.get_children())
        for r in records[:1000]:
            self.tree.insert("", "end", values=[str(r.get(c, ""))[:160] for c in cols])

    @staticmethod
    def _set_text(widget, text):
        widget.configure(state="normal"); widget.delete("1.0", "end")
        widget.insert("end", text); widget.configure(state="disabled")

    @staticmethod
    def _append(widget, text):
        widget.configure(state="normal"); widget.insert("end", text + "\n")
        widget.see("end"); widget.configure(state="disabled")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
