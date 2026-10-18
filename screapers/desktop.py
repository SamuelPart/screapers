"""Interfaz conversacional (Tkinter) — hablas con el bot, el bot obedece.

Diseño oscuro desde cero: conversación como pantalla principal, tarjetas
de embed con botones, y ajustes avanzados en la barra lateral.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .chatbot import ChatEngine
from .config import get_settings, xdg_data
from .datasets import FORMATS, DatasetStore
from .security import AuditLog, redact_text

# Paleta oscura
BG = "#0b1220"        # fondo ventana
PANEL = "#0f172a"     # paneles
CARD = "#1e293b"      # burbuja bot / tarjetas
USER = "#2563eb"      # burbuja usuario
ACCENT = "#38bdf8"    # acentos / enlaces
TXT = "#e2e8f0"
MUTED = "#94a3b8"
SIDEBAR = "#020617"

GREETING = (
    "¡Hola! Soy tu asistente de streaming 🎬\n\n"
    "Pega la URL de una película, serie o capítulo de tus sitios y dime qué hacer, por ejemplo:\n"
    "• «Encuentra el iframe de esta página»\n"
    "• «Busca episodios con el mismo nombre o similares»\n"
    "• «Entra en cada episodio y extrae su embed»\n\n"
    "Te entrego el enlace exacto del embed (solo busco la línea <iframe>, "
    "no proceso el resto de la página).")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Screapers {__version__} — Asistente de streaming con IA")
        self.geometry("1180x760")
        self.minsize(940, 600)
        self.configure(bg=BG)
        self.settings = get_settings()
        self.store = DatasetStore()
        self.audit = AuditLog(xdg_data() / "audit.log")
        self.engine = ChatEngine(self.settings, log=lambda m: self.queue.put(("log", m)))
        self.records: list[dict] = []
        self.queue: queue.Queue = queue.Queue()
        self.busy = False
        self._build()
        self.after(120, self._drain)
        self._bot(GREETING)
        self.audit.append("app_start", "interfaz conversacional")

    # ------------------------------------------------------------- UI
    def _build(self):
        self._style()
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True)

        # ---------- barra lateral ----------
        side = tk.Frame(root, bg=SIDEBAR, width=272)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="🕷 Screapers", bg=SIDEBAR, fg=TXT,
                 font=("Sans", 16, "bold")).pack(anchor="w", padx=16, pady=(16, 0))
        tk.Label(side, text="Asistente de streaming · IA local", bg=SIDEBAR, fg=MUTED,
                 font=("Sans", 8)).pack(anchor="w", padx=16, pady=(0, 12))
        tk.Button(side, text="＋  Nueva conversación", command=self.new_chat,
                  bg=CARD, fg=TXT, activebackground=USER, relief="flat",
                  font=("Sans", 9, "bold"), pady=6).pack(fill="x", padx=12, pady=4)

        tk.Label(side, text="RESULTADOS", bg=SIDEBAR, fg=MUTED, font=("Sans", 8, "bold")) \
            .pack(anchor="w", padx=16, pady=(14, 2))
        self.count_var = tk.StringVar(value="0 embeds / enlaces")
        tk.Label(side, textvariable=self.count_var, bg=SIDEBAR, fg=ACCENT, font=("Sans", 9)) \
            .pack(anchor="w", padx=16)

        tk.Label(side, text="DATASETS GUARDADOS", bg=SIDEBAR, fg=MUTED, font=("Sans", 8, "bold")) \
            .pack(anchor="w", padx=16, pady=(14, 4))
        self.ds_list = tk.Listbox(side, bg=CARD, fg=TXT, relief="flat", height=6,
                                  selectbackground=USER, font=("Sans", 8), activestyle="none")
        self.ds_list.pack(fill="x", padx=12)
        self.ds_list.bind("<Double-Button-1>", lambda e: self.load_dataset())
        row = tk.Frame(side, bg=SIDEBAR)
        row.pack(fill="x", padx=12, pady=4)
        for txt, cmd in (("↻", self.refresh_datasets), ("📂 Cargar", self.load_dataset), ("🗑", self.delete_dataset)):
            tk.Button(row, text=txt, command=cmd, bg=CARD, fg=TXT, relief="flat",
                      font=("Sans", 8)).pack(side="left", padx=2)
        self.refresh_datasets()

        tk.Label(side, text="AJUSTES DE BÚSQUEDA", bg=SIDEBAR, fg=MUTED, font=("Sans", 8, "bold")) \
            .pack(anchor="w", padx=16, pady=(14, 4))
        box = tk.Frame(side, bg=SIDEBAR)
        box.pack(fill="x", padx=12)
        self.max_pages = tk.IntVar(value=self.settings.max_pages)
        self.max_depth = tk.IntVar(value=self.settings.max_depth)
        self.delay_min = tk.DoubleVar(value=self.settings.delay_min)
        for i, (lab, var) in enumerate((("Máx. páginas", self.max_pages),
                                        ("Profundidad", self.max_depth),
                                        ("Pausa mín. (s)", self.delay_min))):
            tk.Label(box, text=lab, bg=SIDEBAR, fg=MUTED, font=("Sans", 8)).grid(row=i, column=0, sticky="w", pady=2)
            tk.Spinbox(box, textvariable=var, width=6, from_=0, to=500, increment=0.5,
                       bg=CARD, fg=TXT, relief="flat", buttonbackground=CARD).grid(row=i, column=1, sticky="e", pady=2)
        self.respect = tk.BooleanVar(value=self.settings.respect_robots)
        self.own_site = tk.BooleanVar(value=False)
        self.mask = tk.BooleanVar(value=self.settings.mask_pii)
        for var, lab in ((self.respect, "Respetar robots.txt"),
                         (self.own_site, "🏠 Es mi sitio (ignora robots)"),
                         (self.mask, "Ocultar datos personales")):
            tk.Checkbutton(box, text=lab, variable=var, bg=SIDEBAR, fg=TXT,
                           selectcolor=CARD, activebackground=SIDEBAR, activeforeground=TXT,
                           font=("Sans", 8)).grid(columnspan=2, sticky="w", pady=1)
        tk.Label(box, text="Proxy propio (solo sesión)", bg=SIDEBAR, fg=MUTED, font=("Sans", 8)) \
            .grid(columnspan=2, sticky="w", pady=(6, 1))
        self.proxy_var = tk.StringVar()
        tk.Entry(box, textvariable=self.proxy_var, show="•", bg=CARD, fg=TXT, relief="flat") \
            .grid(columnspan=2, sticky="ew")
        tk.Button(side, text="⚙ Guardar ajustes", command=self.save_settings,
                  bg=CARD, fg=TXT, relief="flat", font=("Sans", 8)) \
            .pack(fill="x", padx=12, pady=10)

        # ---------- conversación ----------
        main = tk.Frame(root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        head = tk.Frame(main, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text="💬 Habla con el bot", bg=PANEL, fg=TXT,
                 font=("Sans", 13, "bold")).pack(side="left", padx=14, pady=10)
        self.status = tk.StringVar(value="Listo")
        tk.Label(head, textvariable=self.status, bg=PANEL, fg=ACCENT, font=("Sans", 9)) \
            .pack(side="right", padx=14)

        self.chat = tk.Text(main, wrap="word", bg=BG, fg=TXT, relief="flat",
                            font=("Sans", 10), padx=14, pady=10, state="disabled",
                            spacing1=2, spacing3=4)
        sb = tk.Scrollbar(main, command=self.chat.yview)
        sb.pack(side="right", fill="y")
        self.chat.pack(fill="both", expand=True)
        self.chat.configure(yscrollcommand=sb.set)
        self.chat.tag_configure("bot_name", foreground=ACCENT, font=("Sans", 9, "bold"))
        self.chat.tag_configure("user_name", foreground="#93c5fd", font=("Sans", 9, "bold"))
        self.chat.tag_configure("bot", background=CARD, foreground=TXT, lmargin1=8, lmargin2=8, rmargin=60)
        self.chat.tag_configure("user", background=USER, foreground="white", lmargin1=60, lmargin2=60, rmargin=8)
        self.chat.tag_configure("url", foreground=ACCENT, font=("Sans", 9, "bold"))
        self.chat.tag_configure("dim", foreground=MUTED, font=("Sans", 8))

        chips = tk.Frame(main, bg=BG)
        chips.pack(fill="x", padx=12, pady=(4, 0))
        for label, text in (
                ("🎬 Encuentra el iframe de esta URL", "Encuentra el iframe de esta página: "),
                ("📺 Busca episodios similares", "Busca episodios con el mismo nombre o similares y entra en cada uno a extraer su embed"),
                ("⬇ Exporta en JSON.GZ", "Exporta los enlaces en json.gz"),
                ("❓ Ayuda", "ayuda")):
            tk.Button(chips, text=label, command=lambda t=text: self._chip(t),
                      bg=CARD, fg=TXT, relief="flat", font=("Sans", 8), padx=8, pady=4) \
                .pack(side="left", padx=3)

        bottom = tk.Frame(main, bg=PANEL)
        bottom.pack(fill="x")
        self.fmt_var = tk.StringVar(value="json.gz")
        ttk.Combobox(bottom, textvariable=self.fmt_var, values=list(FORMATS), width=9,
                     state="readonly").pack(side="right", padx=(4, 6), pady=10)
        tk.Button(bottom, text="⬇", command=self.export, bg=CARD, fg=TXT, relief="flat",
                  font=("Sans", 11)).pack(side="right", pady=10)
        self.btn_send = tk.Button(bottom, text="Enviar ➤", command=self.send,
                                  bg=USER, fg="white", activebackground="#1d4ed8", relief="flat",
                                  font=("Sans", 10, "bold"), padx=14, pady=8)
        self.btn_send.pack(side="right", padx=(4, 10), pady=10)
        self.input = tk.Entry(bottom, bg=CARD, fg=TXT, relief="flat", font=("Sans", 11),
                              insertbackground=TXT)
        self.input.pack(side="left", fill="x", expand=True, padx=(12, 4), pady=10, ipady=6)
        self.input.bind("<Return>", lambda e: self.send())
        self.input.focus_set()

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=TXT)

    # -------------------------------------------------------- chat IO
    def _write(self, who: str, text: str):
        self.chat.configure(state="normal")
        if who == "bot":
            self.chat.insert("end", "🤖 Bot\n", "bot_name")
            self.chat.insert("end", text + "\n\n", "bot")
        elif who == "user":
            self.chat.insert("end", "Tú\n", "user_name")
            self.chat.insert("end", text + "\n\n", "user")
        else:
            self.chat.insert("end", text + "\n", "dim")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _bot(self, text):
        self._write("bot", text)

    def _chip(self, text):
        self.input.delete(0, "end")
        self.input.insert(0, text)
        self.input.focus_set()
        if text == "ayuda" or text.startswith("Exporta"):
            self.send()

    def new_chat(self):
        self.engine = ChatEngine(self.settings, log=lambda m: self.queue.put(("log", m)))
        self.records = []
        self.count_var.set("0 embeds / enlaces")
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._bot(GREETING)
        self.status.set("Nueva conversación")

    # ------------------------------------------------------- acciones
    def _sync_settings(self):
        s = self.settings
        s.max_pages, s.max_depth = int(self.max_pages.get()), int(self.max_depth.get())
        s.delay_min = float(self.delay_min.get())
        s.delay_max = max(s.delay_max, s.delay_min)
        s.respect_robots = False if self.own_site.get() else self.respect.get()
        s.mask_pii = self.mask.get()
        s.proxy = self.proxy_var.get().strip() or None
        self.engine.set_settings(s)

    def send(self):
        if self.busy:
            return
        msg = self.input.get().strip()
        if not msg:
            return
        self.input.delete(0, "end")
        self._write("user", msg)
        self._sync_settings()
        if self.own_site.get():
            self.audit.append("chat_own_site", msg[:120])
        self.audit.append("chat", msg[:200])
        self.busy = True
        self.btn_send.configure(state="disabled")
        self.status.set("El bot está buscando…")
        threading.Thread(target=self._run, args=(msg,), daemon=True).start()

    def _run(self, msg):
        try:
            reply = self.engine.process(msg)
            self.queue.put(("reply", reply))
        except Exception as e:  # nunca dejar la UI colgada
            self.queue.put(("reply_text", "Algo falló por dentro: " + redact_text(str(e))))

    # ------------------------------------------------------------ cola
    def _drain(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._write("sys", "  " + payload)
                elif kind == "reply_text":
                    self._bot(payload)
                    self._finish()
                elif kind == "reply":
                    self._bot(payload.text)
                    if payload.records is not None:
                        self.records = payload.records
                        self.count_var.set(f"{len(self.records)} embed(s) / enlaces")
                        self._cards(payload.records)
                        if self.records and self.engine.ctx.last_url:
                            domain = self.engine.ctx.last_url.split("//")[-1].split("/")[0]
                            self.store.save(domain or "dataset", self.records)
                            self.audit.append("chat_extract", f"{domain}: {len(self.records)} resultados")
                        self.refresh_datasets()
                    if payload.status:
                        self.status.set(payload.status)
                    if payload.action and payload.action.get("type") == "export":
                        self.fmt_var.set(payload.action.get("format", "json.gz"))
                        self.export()
                    self._finish()
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _finish(self):
        self.busy = False
        self.btn_send.configure(state="normal")
        if self.status.get() == "El bot está buscando…":
            self.status.set("Listo")

    def _cards(self, records: list[dict], limit: int = 20):
        """Tarjetas con botones bajo la conversación (Copiar / Abrir)."""
        embeds = [r for r in records if r.get("embed_url")][:limit]
        if not embeds:
            return
        self.chat.configure(state="normal")
        self.chat.insert("end", "Resultados rápidos:\n", "bot_name")
        for r in embeds:
            url = r["embed_url"]
            page = r.get("pagina_exacta") or r.get("fuente_pagina") or ""
            self.chat.insert("end", f"🔗 {url}\n", "url")
            if page:
                self.chat.insert("end", f"   página exacta: {page}\n", "dim")
            for label, cmd in (("📋 Copiar", lambda u=url: self._copy(u)),
                               ("🌐 Abrir", lambda u=url: webbrowser.open(u))):
                btn = tk.Button(self.chat, text=label, command=cmd, bg=CARD, fg=TXT,
                                relief="flat", font=("Sans", 8), padx=6)
                self.chat.window_create("end", window=btn)
                self.chat.insert("end", " ")
            self.chat.insert("end", "\n\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.set("Copiado al portapapeles 📋")

    # ---------------------------------------------------- datasets/io
    def refresh_datasets(self):
        if not hasattr(self, "ds_list"):
            return
        self.ds_list.delete(0, "end")
        for name in self.store.list():
            try:
                n = len(self.store.load(name))
            except Exception:
                n = "?"
            self.ds_list.insert("end", f"{name} ({n})")

    def _selected_dataset(self):
        sel = self.ds_list.curselection()
        if not sel:
            messagebox.showinfo("Datasets", "Selecciona un dataset de la barra lateral.")
            return None
        return self.ds_list.get(sel[0]).rsplit(" (", 1)[0]

    def load_dataset(self):
        name = self._selected_dataset()
        if not name:
            return
        try:
            self.records = self.store.load(name)
            self.engine.ctx.records = self.records
            self.count_var.set(f"{len(self.records)} embed(s) / enlaces")
            self._bot(f"Dataset «{name}» cargado: {len(self.records)} resultado(s). "
                      "Puedes pedirme filtrarlos o exportarlos.")
            self._cards(self.records)
        except Exception as e:
            messagebox.showerror("Datasets", redact_text(str(e)))

    def delete_dataset(self):
        name = self._selected_dataset()
        if name and messagebox.askyesno("Borrar", f"¿Borrar «{name}»?"):
            self.store.delete(name)
            self.refresh_datasets()

    def export(self):
        if not self.records:
            messagebox.showinfo("Exportar", "Todavía no hay resultados. Pide al bot que busque algo primero.")
            return
        fmt = self.fmt_var.get()
        path = filedialog.asksaveasfilename(defaultextension=f".{fmt}",
                                            filetypes=[(fmt.upper(), f"*.{fmt}"), ("Todos", "*.*")])
        if not path:
            return
        try:
            out = self.store.export(self.records, fmt, Path(path))
            self.audit.append("export", f"{fmt} → {out.name} ({len(self.records)})")
            self._bot(f"Exportado ✅: {out} ({len(self.records)} resultado(s), formato {fmt}).")
            self.status.set(f"Exportado: {out.name}")
        except Exception as e:
            messagebox.showerror("Exportar", redact_text(str(e)))

    def save_settings(self):
        self._sync_settings()
        self.settings.save_overrides()
        self._bot("Ajustes guardados ⚙ (el proxy y los secretos nunca se guardan en disco).")
        self.status.set("Ajustes guardados")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
