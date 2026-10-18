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
from .parser import parse_page
from .scraper import Scraper
from .streaming import (base_title, find_related, group_episodes,
                        parse_instruction, search_candidates)
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

        ttk.Label(self, text="Streaming (películas y series) y web en general: dile al bot qué hacer, "
                             "extrae embeds, busca títulos iguales o similares y protege tus datos.",
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

        task = ttk.Frame(self, style="Card.TFrame")
        task.pack(fill="x", padx=18, pady=(0, 10))
        ttk.Label(task, text="🎯 ¿Qué quieres hacer en este sitio?", style="Card.TLabel", font=("Sans", 10, "bold")) \
            .grid(row=0, column=0, padx=(12, 4), pady=(10, 4), sticky="w")
        self.instruction_var = tk.StringVar(
            value="Extrae el enlace del embed y, si es una serie, busca episodios con el mismo nombre o similares")
        ttk.Entry(task, textvariable=self.instruction_var).grid(row=0, column=1, columnspan=3, sticky="ew", pady=(10, 4))
        ttk.Label(task, text="Título (serie/película):", style="Card.TLabel").grid(row=1, column=0, padx=(12, 4), pady=(0, 10), sticky="w")
        self.title_var = tk.StringVar()
        ttk.Entry(task, textvariable=self.title_var, width=28).grid(row=1, column=1, sticky="w", pady=(0, 10))
        ttk.Label(task, text="Ej.: «extrae el embed», «busca la temporada 2», «extrae las tablas»… el bot obedece tu orden.",
                  style="Card.TLabel").grid(row=1, column=2, columnspan=2, padx=8, pady=(0, 10), sticky="w")
        task.columnconfigure(1, weight=1)

        opts = ttk.Frame(self, style="Card.TFrame")
        opts.pack(fill="x", padx=18, pady=(0, 10))
        self.max_pages = tk.IntVar(value=self.settings.max_pages)
        self.max_depth = tk.IntVar(value=self.settings.max_depth)
        self.delay_min = tk.DoubleVar(value=self.settings.delay_min)
        self.delay_max = tk.DoubleVar(value=self.settings.delay_max)
        self.timeout = tk.DoubleVar(value=self.settings.timeout)
        self.respect = tk.BooleanVar(value=self.settings.respect_robots)
        self.mask = tk.BooleanVar(value=self.settings.mask_pii)
        self.allow_priv = tk.BooleanVar(value=self.settings.allow_private)
        self.use_ai = tk.BooleanVar(value=self.settings.use_ai)
        for col, (label, var, w) in enumerate([
                ("Máx. páginas", self.max_pages, 5), ("Profundidad", self.max_depth, 5),
                ("Pausa mín. (s)", self.delay_min, 5), ("Pausa máx. (s)", self.delay_max, 5),
                ("Timeout (s)", self.timeout, 5)]):
            ttk.Label(opts, text=label + ":", style="Card.TLabel").grid(row=0, column=col * 2, padx=(12, 2), pady=8)
            ttk.Spinbox(opts, textvariable=var, width=w, from_=0, to=500,
                        increment=0.5 if isinstance(var, tk.DoubleVar) else 1) \
                .grid(row=0, column=col * 2 + 1, pady=8)
        ttk.Checkbutton(opts, text="Respetar robots.txt", variable=self.respect).grid(row=1, column=0, padx=10, pady=(0, 8), sticky="w")
        ttk.Checkbutton(opts, text="Ocultar datos personales (PII)", variable=self.mask).grid(row=1, column=2, padx=6, pady=(0, 8), sticky="w")
        ttk.Checkbutton(opts, text="Permitir red local", variable=self.allow_priv).grid(row=1, column=4, padx=6, pady=(0, 8), sticky="w")
        ttk.Checkbutton(opts, text="Bots IA activos", variable=self.use_ai).grid(row=1, column=6, padx=6, pady=(0, 8), sticky="w")
        ttk.Label(opts, text="Proxy propio (opcional):", style="Card.TLabel").grid(row=2, column=0, padx=(12, 2), pady=(0, 8), sticky="w")
        self.proxy_var = tk.StringVar(value="")
        ttk.Entry(opts, textvariable=self.proxy_var, width=44, show="•").grid(
            row=2, column=1, columnspan=5, sticky="w", pady=(0, 8))
        ttk.Label(opts, text="ej. http://127.0.0.1:8080 · solo dura la sesión, no se guarda",
                  style="Card.TLabel").grid(row=2, column=6, columnspan=4, padx=6, pady=(0, 8), sticky="w")
        self.own_site = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="🏠 Es mi sitio / tengo permiso: auditarlo ignorando su robots.txt",
                        variable=self.own_site).grid(row=3, column=0, columnspan=6, padx=12, pady=(0, 10), sticky="w")

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

        f_prev = ttk.Frame(nb); nb.add(f_prev, text="  👁 Vista previa  ")
        self.preview_text = self._text_tab(f_prev)
        f_ai = ttk.Frame(nb); nb.add(f_ai, text="  🤖 Bots IA  ")
        self.ai_text = self._text_tab(f_ai)
        f_ds = ttk.Frame(nb); nb.add(f_ds, text="  💾 Datasets guardados  ")
        self.ds_list = tk.Listbox(f_ds, font=("Sans", 10), relief="flat", activestyle="none")
        self.ds_list.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        ds_btns = ttk.Frame(f_ds)
        ds_btns.pack(side="right", fill="y", padx=6, pady=6)
        ttk.Button(ds_btns, text="↻ Actualizar", command=self.refresh_datasets).pack(fill="x", pady=3)
        ttk.Button(ds_btns, text="📂 Cargar en tabla", command=self.load_dataset).pack(fill="x", pady=3)
        ttk.Button(ds_btns, text="🗑 Borrar", command=self.delete_dataset).pack(fill="x", pady=3)
        self.refresh_datasets()
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
        s.delay_max = float(self.delay_max.get())
        s.timeout = float(self.timeout.get())
        s.use_ai = self.use_ai.get()
        s.proxy = self.proxy_var.get().strip() or None  # solo en memoria, jamás a disco
        s.respect_robots, s.mask_pii, s.allow_private = self.respect.get(), self.mask.get(), self.allow_priv.get()
        if self.own_site.get():  # auditoría de tu propio sitio: sin robots, pero registrado
            s.respect_robots = False
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
        self._last_page = None
        self._extra_ai: list[str] = []
        self._fill_tree([])
        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Trabajando… (pausas educadas entre páginas para evitar bloqueos)")
        self.audit.append("scrape_start", url)
        if self.own_site.get():
            self.audit.append("own_site_robots_ignored", url)
        self.worker = threading.Thread(
            target=self._run,
            args=(url, self.selector_var.get().strip(),
                  self.instruction_var.get().strip(), self.title_var.get().strip()),
            daemon=True)
        self.worker.start()

    def _run(self, url, selector, instruction="", title_input=""):
        try:
            plan = parse_instruction(instruction, title_input)
            self.queue.put(("plan", plan))
            seen_pages: list[dict] = []

            def on_page(page, recs):
                seen_pages.append(page)
                self.queue.put(("page", (page, recs)))

            scraper = Scraper(self.settings, log=lambda m: self.queue.put(("log", m)), stop=self.stop_event)
            pages, records = scraper.crawl(url, selector, on_page=on_page,
                                           want_embeds=(plan.intent == "embed"))

            if plan.search_in_site and not self.stop_event.is_set():
                query = plan.query or (base_title(seen_pages[0].get("titulo", "")) if seen_pages else "")
                if query:
                    all_links = [l for pg in seen_pages for l in pg.get("enlaces", [])]
                    related = find_related(all_links, query)
                    if not related:  # probar el buscador interno del dominio
                        for cand in search_candidates(url, query):
                            if self.stop_event.is_set():
                                break
                            try:
                                if not scraper._allowed(cand):
                                    continue
                                self.queue.put(("log", f"🔎 Probando buscador del sitio: {cand}"))
                                pg = parse_page(scraper.fetch(cand), cand,
                                                want_embeds=(plan.intent == "embed"))
                                seen_pages.append(pg)
                                self.queue.put(("page", (pg, pg.get("records", []))))
                                records.extend(pg.get("records", []))
                                related = find_related(pg.get("enlaces", []), query)
                                if related:
                                    break
                            except Exception as e:
                                self.queue.put(("log", f"✗ Buscador {cand}: {e}"))
                    self.queue.put(("related", (query, related)))
                    if plan.follow_related and related:
                        import copy as _copy
                        visited = {pg.get("url") for pg in seen_pages}
                        cfg = _copy.copy(self.settings)
                        cfg.max_pages, cfg.max_depth = 1, 0
                        follower = Scraper(cfg, log=lambda m: self.queue.put(("log", m)), stop=self.stop_event)
                        for rel in related[:12]:
                            if self.stop_event.is_set() or rel["url"] in visited:
                                continue
                            visited.add(rel["url"])
                            n2, r2 = follower.crawl(rel["url"], selector, on_page=on_page,
                                                    want_embeds=(plan.intent == "embed"))
                            pages += n2
                            records.extend(r2)

            cleaned = self.bots.clean_records(records)
            if plan.intent == "embed":  # sin duplicados por URL de embed
                seen_e, unique = set(), []
                for r in cleaned:
                    key = r.get("embed_url") or r.get("url") or str(r)
                    if key not in seen_e:
                        seen_e.add(key); unique.append(r)
                cleaned = unique
            if pages:
                self.store.save(url.split("//")[-1].split("/")[0] or "dataset", cleaned)
            self.queue.put(("done", (pages, cleaned, scraper.last_error)))
        except Exception as e:
            self.queue.put(("error", redact_text(str(e))))

    def stop(self):
        self.stop_event.set()
        self.status.set("Deteniendo…")

    def analyze_ai(self, silent: bool = False):
        if not self.settings.use_ai:
            if not silent:
                self._set_text(self.ai_text, "Los bots de IA están desactivados en los ajustes. "
                                             "Activa «Bots IA activos» para analizar la página.")
            return
        if not getattr(self, "_last_page", None):
            # En automático (al terminar una búsqueda) nunca se tapa el resultado
            # con esta ventana: el motivo real ya va al registro y a la barra de estado.
            if not silent:
                messagebox.showinfo("Bots IA", "Primero extrae una página para que los bots puedan analizarla.")
            return
        info = self.bots.analyze_page(self._last_page, self.records)
        lines = [f"Modo IA: {info['modo_ia']}\n", "— Sugerencias del ScoutBot —", *info["sugerencias"],
                 "\n— Resumen (AnalystBot) —", info["resumen"]]
        if info.get("resumen_ia"):
            lines += ["\n— Resumen IA en nube —", info["resumen_ia"]]
        lines += ["\n— Esquema inferido —"] + [f"  • {k}: {v}" for k, v in info["esquema"].items()]
        self._set_text(self.ai_text, "\n".join(lines))
        if getattr(self, "_extra_ai", None):
            self._append(self.ai_text, "\n" + "\n".join(self._extra_ai))

    # ------------------------------------------------------ datasets
    def refresh_datasets(self):
        if not hasattr(self, "ds_list"):
            return
        self.ds_list.delete(0, "end")
        for name in self.store.list():
            try:
                n = len(self.store.load(name))
            except Exception:
                n = "?"
            self.ds_list.insert("end", f"{name}  ({n} registros)")

    def _selected_dataset(self) -> str | None:
        sel = self.ds_list.curselection()
        if not sel:
            messagebox.showinfo("Datasets", "Selecciona primero un dataset de la lista.")
            return None
        return self.ds_list.get(sel[0]).rsplit("  (", 1)[0]

    def load_dataset(self):
        name = self._selected_dataset()
        if not name:
            return
        try:
            self.records = self.store.load(name)
            self._fill_tree(self.records)
            self.status.set(f"Dataset «{name}» cargado: {len(self.records)} registros. Ya puedes exportarlo.")
            self.audit.append("dataset_load", name)
        except Exception as e:
            messagebox.showerror("Datasets", redact_text(str(e)))

    def delete_dataset(self):
        name = self._selected_dataset()
        if not name:
            return
        if messagebox.askyesno("Borrar dataset", f"¿Borrar definitivamente «{name}»?"):
            self.store.delete(name)
            self.refresh_datasets()
            self.audit.append("dataset_delete", name)

    def _show_preview(self, page: dict):
        lines = [page.get("titulo") or "(sin título)", page.get("url", ""), ""]
        if page.get("descripcion"):
            lines += [page["descripcion"], ""]
        if page.get("encabezados"):
            lines += ["— Encabezados —"] + [f"  • {h}" for h in page["encabezados"][:10]] + [""]
        if page.get("parrafos"):
            lines += ["— Texto —"] + page["parrafos"][:8]
        self._set_text(self.preview_text, "\n".join(lines))

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
                if kind == "plan":
                    plan = payload
                    self._extra_ai = plan.describe()
                    self._set_text(self.ai_text, "\n".join(self._extra_ai))
                    self.status.set("Bot: " + self._extra_ai[1].strip() if len(self._extra_ai) > 1 else "Bot trabajando…")
                elif kind == "related":
                    query, related = payload
                    bloque = [f"\n🔎 Búsqueda en el dominio de títulos como «{query}»:", group_episodes(related)]
                    bloque += [f"  • [{r.get('similitud', '')}] {r.get('texto', '') or r['url']} → {r['url']}"
                               for r in related[:25]]
                    self._extra_ai = getattr(self, "_extra_ai", []) + bloque
                    if getattr(self, "_last_page", None):
                        pass
                    else:
                        self._set_text(self.ai_text, "\n".join(self._extra_ai))
                elif kind == "log":
                    self._append(self.log_text, payload)
                    self.status.set(payload)
                elif kind == "page":
                    page, _ = payload
                    self._last_page = {k: v for k, v in page.items()}
                    self._show_preview(self._last_page)
                elif kind == "done":
                    pages, records, last_error = payload
                    self.records = records
                    self._fill_tree(records)
                    self.refresh_datasets()
                    self.progress.stop()
                    self.btn_start.configure(state="normal")
                    if pages == 0:
                        detalle = last_error or "sin respuesta del sitio"
                        self.status.set(f"Sin resultados: el sitio no entregó ninguna página. Motivo: {detalle}")
                        self._append(self.log_text,
                                     "⚠ Búsqueda sin páginas. Motivo real: " + detalle)
                        self._set_text(self.ai_text,
                                       "Los bots no tienen página que analizar porque el sitio no entregó ninguna.\n"
                                       "Mira la pestaña «Registro y seguridad»: ahí está el motivo exacto "
                                       "(403/CAPTCHA, robots.txt, tiempo agotado…).\n"
                                       "Si el sitio deniega el acceso, Screapers no lo fuerza; prueba pausas más "
                                       "largas, profundidad 0 o otra página del mismo sitio.")
                        self.audit.append("scrape_empty", detalle)
                    else:
                        self.status.set(f"Terminado: {pages} página(s), {len(records)} registros limpios y protegidos.")
                        self.audit.append("scrape_done", f"{pages} páginas, {len(records)} registros")
                        self.analyze_ai(silent=True)
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
