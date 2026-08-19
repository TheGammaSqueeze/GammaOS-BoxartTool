"""
Cross-platform desktop GUI for the GammaOS Boxart Tool (Tkinter).

Shows your games, previews the current cover, and lets you replace, add,
remove, bulk-import and bulk-export boxart over ADB. Runs on Windows, macOS
and Linux with the Python standard library; Pillow (pip install pillow) is
optional and only used for nicer cover previews.
"""

import os
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .core import Adb, AdbError, Boxart, _system_of
from .scraper import make_scraper, ScrapeError, SOURCES

REGION_CHOICES = [("World", "wor"), ("USA", "us"), ("Europe", "eu"), ("Japan", "jp")]

try:
    from PIL import Image, ImageTk
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

from . import __version__

ACCENT = "#7b2ff7"


class BoxartGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GammaOS Boxart Tool %s" % __version__)
        self.geometry("1040x850")
        self.minsize(940, 760)
        self.configure(bg="#f7f7fc")

        self.source_var = tk.StringVar(value=SOURCES[0][0])
        self.region_var = tk.StringVar(value="World")
        self.ss_user = ""
        self.ss_pass = ""
        self.tgdb_key = ""

        self.adb = None
        self.bx = None
        self.games = []
        self._preview_img = None
        self._fan_img = None
        self._tmp = tempfile.mkdtemp(prefix="gbt_gui_")
        self._busy = False

        self._build_style()
        self._build_widgets()
        self.after(200, self.connect)

    # -- layout -------------------------------------------------------------
    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("TFrame", background="#f7f7fc")
        st.configure("TLabel", background="#f7f7fc", foreground="#17151f")
        st.configure("Head.TLabel", font=("Helvetica", 13, "bold"))
        st.configure("Dim.TLabel", foreground="#7c7a92")
        st.configure("Accent.TButton", foreground="#ffffff", background=ACCENT)
        st.map("Accent.TButton", background=[("active", "#6d28d9")])
        st.configure("Treeview", rowheight=24, fieldbackground="#ffffff")
        st.configure("Treeview.Heading", font=("Helvetica", 10, "bold"))

    def _build_widgets(self):
        # top bar
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="GammaOS Boxart Tool", style="Head.TLabel").pack(side=tk.LEFT)
        self.device_lbl = ttk.Label(top, text="connecting...", style="Dim.TLabel")
        self.device_lbl.pack(side=tk.LEFT, padx=12)
        ttk.Button(top, text="Restart Nano", command=self.restart_nano).pack(side=tk.RIGHT)
        ttk.Button(top, text="Bulk Export...", command=self.bulk_export).pack(side=tk.RIGHT, padx=6)
        ttk.Button(top, text="Bulk Import...", command=self.bulk_import).pack(side=tk.RIGHT)
        ttk.Button(top, text="Scrape Library...", style="Accent.TButton",
                   command=self.scrape_library).pack(side=tk.RIGHT, padx=6)
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side=tk.RIGHT, padx=6)

        # filter
        fbar = ttk.Frame(self, padding=(12, 0))
        fbar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(fbar, text="Filter:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(fbar, textvariable=self.filter_var, width=32).pack(side=tk.LEFT, padx=6)
        self.only_box = tk.BooleanVar(value=False)
        ttk.Checkbutton(fbar, text="Only games with boxart", variable=self.only_box,
                        command=self._apply_filter).pack(side=tk.LEFT, padx=10)

        # main split
        main = ttk.Frame(self, padding=12)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cols = ("box", "system", "game")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("box", text="Boxart")
        self.tree.heading("system", text="System")
        self.tree.heading("game", text="Game")
        self.tree.column("box", width=64, anchor="center", stretch=False)
        self.tree.column("system", width=130, stretch=False)
        self.tree.column("game", width=360)
        self.tree.tag_configure("has", foreground="#1eb877")
        self.tree.tag_configure("no", foreground="#7c7a92")
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # right: preview + actions
        right = ttk.Frame(main, width=280)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(14, 0))
        right.pack_propagate(False)
        # Fixed pixel-sized preview boxes (a Frame with pack_propagate off), so the
        # layout never depends on text-line label sizing and the controls below are
        # always visible on every platform.
        ttk.Label(right, text="Cover", style="Head.TLabel").pack(anchor="w")
        cf = tk.Frame(right, width=236, height=188, bg="#ffffff", relief="solid", bd=1)
        cf.pack(pady=(5, 3))
        cf.pack_propagate(False)
        self.preview = tk.Label(cf, bg="#ffffff", text="select a game", fg="#7c7a92")
        self.preview.pack(fill=tk.BOTH, expand=True)
        self.btn_set = ttk.Button(right, text="Set / Replace Cover...", style="Accent.TButton",
                                  command=self.set_cover, state="disabled")
        self.btn_set.pack(fill=tk.X, pady=2)

        ttk.Label(right, text="Background (fan art)", style="Head.TLabel").pack(anchor="w", pady=(8, 0))
        ff = tk.Frame(right, width=236, height=104, bg="#ffffff", relief="solid", bd=1)
        ff.pack(pady=(5, 3))
        ff.pack_propagate(False)
        self.fan_preview = tk.Label(ff, bg="#ffffff", text="none", fg="#7c7a92")
        self.fan_preview.pack(fill=tk.BOTH, expand=True)
        self.btn_setfan = ttk.Button(right, text="Set / Replace Background...", style="Accent.TButton",
                                     command=self.set_background, state="disabled")
        self.btn_setfan.pack(fill=tk.X, pady=2)

        self.sel_lbl = ttk.Label(right, text="", style="Dim.TLabel", wraplength=260, justify="left")
        self.sel_lbl.pack(anchor="w", pady=(6, 4))
        rowf = ttk.Frame(right)
        rowf.pack(fill=tk.X)
        self.btn_save = ttk.Button(rowf, text="Save Cover...", command=self.save_cover_as,
                                   state="disabled")
        self.btn_save.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        self.btn_rm = ttk.Button(rowf, text="Remove...", command=self.remove_art_dialog,
                                 state="disabled")
        self.btn_rm.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(3, 0))

        ttk.Separator(right, orient="horizontal").pack(fill=tk.X, pady=(12, 8))
        ttk.Label(right, text="Scrape art", style="Head.TLabel").pack(anchor="w")
        srow = ttk.Frame(right)
        srow.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(srow, text="Source:").pack(side=tk.LEFT)
        ttk.Combobox(srow, textvariable=self.source_var, state="readonly", width=15,
                     values=[s[0] for s in SOURCES]).pack(side=tk.LEFT, padx=6)
        rrow = ttk.Frame(right)
        rrow.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(rrow, text="Region:").pack(side=tk.LEFT)
        ttk.Combobox(rrow, textvariable=self.region_var, state="readonly", width=8,
                     values=[r[0] for r in REGION_CHOICES]).pack(side=tk.LEFT, padx=6)
        ttk.Button(rrow, text="Credentials...", command=self.credentials_dialog).pack(side=tk.RIGHT)
        self.btn_scrape = ttk.Button(right, text="Scrape Selected", style="Accent.TButton",
                                     command=self.scrape_selected, state="disabled")
        self.btn_scrape.pack(fill=tk.X, pady=2)
        self.btn_search = ttk.Button(right, text="Search & Choose...",
                                     command=self.search_choose, state="disabled")
        self.btn_search.pack(fill=tk.X, pady=2)

        # status bar
        self.status = ttk.Label(self, text="", style="Dim.TLabel", padding=(12, 6),
                                anchor="w")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # -- device -------------------------------------------------------------
    def connect(self):
        try:
            a = Adb()
            devs = a.list_devices()
            if not devs:
                self.device_lbl.config(text="no device (plug in, enable USB debugging)")
                self._set_status("No device connected.")
                return
            a = Adb(serial=devs[0])
            a.ensure_root()
            self.adb = a
            self.bx = Boxart(a)
            self.device_lbl.config(text="device %s  (root)" % devs[0])
            self.refresh()
        except AdbError as e:
            self.device_lbl.config(text="connect failed")
            messagebox.showerror("ADB", str(e))

    def refresh(self):
        if not self.bx or self._busy:
            return
        self._run("Loading games...", self._load_games)

    def _load_games(self):
        games = self.bx.list_games(include_all=True)
        self.after(0, lambda: self._populate(games))

    def _populate(self, games):
        self.games = games
        self._apply_filter()
        have = sum(1 for g in games if g.has_box)
        self._set_status("%d games, %d with boxart" % (len(games), have))
        # Optional: auto-select a game (used for demos/screenshots).
        want = os.environ.get("GBT_SELECT")
        if want:
            for iid in self.tree.get_children():
                if want.lower() in self.tree.item(iid, "values")[2].lower():
                    self.tree.selection_set(iid)
                    self.tree.see(iid)
                    self.on_select()
                    break
            if os.environ.get("GBT_SEARCH") and not getattr(self, "_hooked", False):
                self._hooked = True
                self.after(600, self.search_choose)
            if os.environ.get("GBT_SCRAPE") and not getattr(self, "_hooked", False):
                self._hooked = True
                self.after(600, self.scrape_selected)

    def _apply_filter(self):
        q = self.filter_var.get().strip().lower()
        only = self.only_box.get()
        self.tree.delete(*self.tree.get_children())
        for i, g in enumerate(self.games):
            if only and not g.has_box:
                continue
            if q and q not in g.display.lower() and q not in g.system.lower():
                continue
            mark = "★" if g.has_box else "·"
            self.tree.insert("", "end", iid=str(i), values=(mark, g.system, g.display),
                             tags=("has" if g.has_box else "no",))

    def _selected_game(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.games[int(sel[0])]

    def on_select(self, _evt=None):
        g = self._selected_game()
        if not g:
            return
        self.btn_set.config(state="normal")
        self.btn_setfan.config(state="normal")
        self.btn_scrape.config(state="normal")
        self.btn_search.config(state="normal")
        self.btn_rm.config(state="normal" if (g.has_box or g.has_fan) else "disabled")
        self.btn_save.config(state="normal" if g.has_box else "disabled")
        self.sel_lbl.config(text="%s\n%s\ncover: %s   background: %s" % (
            g.display, g.system, "yes" if g.has_box else "no",
            "yes" if g.has_fan else "no"))
        self.preview.config(image="", text="loading..." if g.has_box else "no cover")
        self.fan_preview.config(image="", text="loading..." if g.has_fan else "none")
        self._preview_img = None
        self._fan_img = None
        if g.has_box:
            self._run("Loading cover...",
                      lambda: self._load_art(g, "box", self.preview, "_preview_img"),
                      busy_ui=False)
        if g.has_fan:
            self._run("Loading background...",
                      lambda: self._load_art(g, "fan", self.fan_preview, "_fan_img"),
                      busy_ui=False)

    def _load_art(self, g, kind, target, attr):
        local = os.path.join(self._tmp, "prev_%s.img" % kind)
        ok = self.bx.get_art(g.rom, local, kind)
        empty = "no cover" if kind == "box" else "none"
        self.after(0, lambda: self._show_art(local if ok else None, target, attr, empty))

    def _show_art(self, local, target, attr, empty_text):
        if not local or not os.path.isfile(local):
            target.config(image="", text=empty_text)
            return
        maxsz = (230, 182) if attr == "_preview_img" else (230, 98)
        img = None
        if _HAVE_PIL:
            try:
                im = Image.open(local)
                im.thumbnail(maxsz)
                img = ImageTk.PhotoImage(im)
            except Exception:
                img = None
        if img is None:
            try:
                img = tk.PhotoImage(file=local)
            except Exception:
                target.config(image="", text="(set; install Pillow to preview)")
                return
        setattr(self, attr, img)
        target.config(image=img, text="")

    # -- actions ------------------------------------------------------------
    def set_cover(self):
        self._pick_and_set("box", "cover image")

    def set_background(self):
        self._pick_and_set("fan", "background (fan art) image")

    def _pick_and_set(self, kind, what):
        g = self._selected_game()
        if not g:
            return
        img = filedialog.askopenfilename(
            title="Choose a %s for %s" % (what, g.display),
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
        if not img:
            return
        self._run("Setting %s + restarting Nano..." % kind, lambda: self._do_set(g, img, kind))

    def _do_set(self, g, img, kind):
        with tempfile.TemporaryDirectory() as td:
            self.bx.set_art(g.rom, img, td, kind=kind)
        self.bx.adb.restart_nano()
        self.after(0, self.refresh)
        self.after(0, lambda: self._set_status("Set %s for %s" % (
            "background" if kind == "fan" else "cover", g.display)))

    def remove_art_dialog(self):
        g = self._selected_game()
        if not g or not (g.has_box or g.has_fan):
            return
        win = tk.Toplevel(self)
        win.title("Remove")
        win.transient(self)
        win.grab_set()
        ttk.Label(win, text="Remove for %s:" % g.display, padding=14).pack()
        fr = ttk.Frame(win, padding=(14, 0, 14, 14))
        fr.pack()

        def do(kind):
            win.destroy()
            self._run("Removing + restarting Nano...", lambda: self._do_remove(g, kind))

        if g.has_box:
            ttk.Button(fr, text="Cover", command=lambda: do("box")).pack(side=tk.LEFT, padx=4)
        if g.has_fan:
            ttk.Button(fr, text="Background", command=lambda: do("fan")).pack(side=tk.LEFT, padx=4)
        if g.has_box and g.has_fan:
            ttk.Button(fr, text="Both", command=lambda: do(None)).pack(side=tk.LEFT, padx=4)
        ttk.Button(fr, text="Cancel", command=win.destroy).pack(side=tk.LEFT, padx=4)

    def _do_remove(self, g, kind):
        with tempfile.TemporaryDirectory() as td:
            self.bx.remove_art(g.rom, td, kind=kind)
        self.bx.adb.restart_nano()
        self.after(0, self.refresh)

    def save_cover_as(self):
        g = self._selected_game()
        if not g or not g.has_box:
            return
        out = filedialog.asksaveasfilename(defaultextension=".png",
                                           initialfile=g.display + ".png")
        if not out:
            return
        self._run("Saving...", lambda: self._do_save(g, out))

    def _do_save(self, g, out):
        ok = self.bx.get_cover(g.rom, out)
        self.after(0, lambda: self._set_status("Saved cover -> %s" % out if ok else "no cover"))

    def bulk_import(self):
        d = filedialog.askdirectory(title="Folder of cover images (or an export folder)")
        if not d:
            return
        self._run("Importing covers...", lambda: self._do_import(d))

    def _do_import(self, d):
        with tempfile.TemporaryDirectory() as td:
            applied, _ = self.bx.import_dir(d, td, mode="auto")
        if applied:
            self.bx.adb.restart_nano()
        self.after(0, self.refresh)
        self.after(0, lambda: self._set_status("Imported %d covers" % applied))

    def bulk_export(self):
        d = filedialog.askdirectory(title="Export covers to folder")
        if not d:
            return
        self._run("Exporting covers...", lambda: self._do_export(d))

    def _do_export(self, d):
        n = self.bx.export_all(d)
        self.after(0, lambda: self._set_status("Exported %d covers -> %s" % (n, d)))

    # -- scraping -----------------------------------------------------------
    def _region_code(self):
        for label, code in REGION_CHOICES:
            if label == self.region_var.get():
                return code
        return "wor"

    def _source_code(self):
        for label, code in SOURCES:
            if label == self.source_var.get():
                return code
        return "screenscraper"

    def _make_scraper(self):
        sc = make_scraper(source=self._source_code(), region=self._region_code(),
                          ss_user=self.ss_user or None, ss_pass=self.ss_pass or None,
                          tgdb_key=self.tgdb_key or None)
        if not sc.ready:
            raise ScrapeError(sc.unready_reason())
        return sc

    def _selected_games(self):
        return [self.games[int(i)] for i in self.tree.selection()]

    def credentials_dialog(self):
        win = tk.Toplevel(self)
        win.title("Scraper Credentials")
        win.transient(self)
        win.grab_set()
        ttk.Label(win, padding=(14, 12, 14, 4), justify="left", wraplength=360,
                  text="ScreenScraper's GammaOS developer account is built in; a personal "
                       "account is optional (higher quota). TheGamesDB needs your own free "
                       "API key from thegamesdb.net.").pack(anchor="w")
        fr = ttk.Frame(win, padding=(14, 0, 14, 12))
        fr.pack(fill=tk.X)
        ttk.Label(fr, text="ScreenScraper user:").grid(row=0, column=0, sticky="w", pady=3)
        uvar = tk.StringVar(value=self.ss_user)
        ttk.Entry(fr, textvariable=uvar, width=30).grid(row=0, column=1, padx=6)
        ttk.Label(fr, text="ScreenScraper pass:").grid(row=1, column=0, sticky="w", pady=3)
        pvar = tk.StringVar(value=self.ss_pass)
        ttk.Entry(fr, textvariable=pvar, width=30, show="*").grid(row=1, column=1, padx=6)
        ttk.Label(fr, text="TheGamesDB API key:").grid(row=2, column=0, sticky="w", pady=(10, 3))
        kvar = tk.StringVar(value=self.tgdb_key)
        ttk.Entry(fr, textvariable=kvar, width=30).grid(row=2, column=1, padx=6, pady=(10, 3))
        bf = ttk.Frame(win, padding=(14, 0, 14, 14))
        bf.pack(fill=tk.X)

        def save():
            self.ss_user = uvar.get().strip()
            self.ss_pass = pvar.get().strip()
            self.tgdb_key = kvar.get().strip()
            win.destroy()
            self._set_status("Credentials saved")

        ttk.Button(bf, text="Save", style="Accent.TButton", command=save).pack(side=tk.RIGHT)
        ttk.Button(bf, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)

    # -- scrape the highlighted games ---------------------------------------
    def scrape_selected(self):
        games = self._selected_games()
        if not games:
            return
        try:
            sc = self._make_scraper()
        except ScrapeError as e:
            messagebox.showerror("Scrape", str(e))
            return
        roms = [g.rom for g in games]
        overwrite = len(games) == 1   # a single explicit pick re-scrapes; a bulk pick fills gaps
        title = "Scraping %d game%s" % (len(roms), "" if len(roms) == 1 else "s")

        def run(td, progress, cancel):
            return self.bx.scrape_roms(sc, td, roms, overwrite=overwrite,
                                       progress=progress, cancel=cancel)
        self._scrape_with_progress(title, "%s, region %s" % (sc.label, self.region_var.get()), run)

    # -- scrape the whole library -------------------------------------------
    def scrape_library(self):
        if not self.bx:
            return
        try:
            sc = self._make_scraper()
        except ScrapeError as e:
            messagebox.showerror("Scrape", str(e))
            return
        win = tk.Toplevel(self)
        win.title("Scrape Library")
        win.transient(self)
        win.grab_set()
        ttk.Label(win, padding=(16, 14, 16, 6), justify="left", wraplength=380,
                  text="Scrape covers and backgrounds for your games from %s (region: %s). "
                       "Only games missing art are scraped unless you choose to overwrite."
                       % (sc.label, self.region_var.get())).pack(anchor="w")
        fr = ttk.Frame(win, padding=(16, 0, 16, 6))
        fr.pack(fill=tk.X)
        want_box = tk.BooleanVar(value=True)
        want_fan = tk.BooleanVar(value=True)
        overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(fr, text="Covers", variable=want_box).pack(anchor="w")
        ttk.Checkbutton(fr, text="Backgrounds (fan art)", variable=want_fan).pack(anchor="w")
        ttk.Checkbutton(fr, text="Overwrite games that already have art",
                        variable=overwrite).pack(anchor="w")
        bf = ttk.Frame(win, padding=(16, 4, 16, 14))
        bf.pack(fill=tk.X)

        def go():
            wb, wf, ov = want_box.get(), want_fan.get(), overwrite.get()
            win.destroy()
            if not (wb or wf):
                return

            def run(td, progress, cancel):
                return self.bx.scrape_missing(sc, td, want_box=wb, want_fan=wf,
                                              overwrite=ov, progress=progress, cancel=cancel)
            self._scrape_with_progress("Scraping library",
                                       "%s, region %s" % (sc.label, self.region_var.get()), run)

        ttk.Button(bf, text="Start", style="Accent.TButton", command=go).pack(side=tk.RIGHT)
        ttk.Button(bf, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)

    # -- shared modal progress + result dialog ------------------------------
    def _scrape_with_progress(self, title, subtitle, run):
        """run(tmpdir, progress, cancel) -> (matched, scanned), shown in a modal dialog."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        ttk.Label(dlg, text=title, style="Head.TLabel", padding=(18, 16, 18, 2)).pack(anchor="w")
        ttk.Label(dlg, text=subtitle, style="Dim.TLabel", padding=(18, 0)).pack(anchor="w")
        pb = ttk.Progressbar(dlg, mode="determinate", length=380, maximum=1)
        pb.pack(padx=18, pady=(10, 4))
        cur = ttk.Label(dlg, text="Starting...", padding=(18, 0), wraplength=380, justify="left")
        cur.pack(anchor="w")
        tally = ttk.Label(dlg, text="", style="Dim.TLabel", padding=(18, 8),
                          wraplength=380, justify="left")
        tally.pack(anchor="w")
        bf = ttk.Frame(dlg, padding=(18, 2, 18, 14))
        bf.pack(fill=tk.X)
        cancel_ev = threading.Event()
        btn = ttk.Button(bf, text="Cancel", command=cancel_ev.set)
        btn.pack(side=tk.RIGHT)
        dlg.protocol("WM_DELETE_WINDOW", cancel_ev.set)

        m = {"box": 0, "fan": 0, "skip": 0, "miss": 0, "err": 0}

        def tally_text():
            return ("Covers %d    Backgrounds %d\nSkipped %d    No match %d    Errors %d"
                    % (m["box"], m["fan"], m["skip"], m["miss"], m["err"]))

        def prog(done, total, name, r):
            if r.get("box"):
                m["box"] += 1
            if r.get("fan"):
                m["fan"] += 1
            if r.get("skipped"):
                m["skip"] += 1
            elif "matched" not in r:
                m["err"] += 1
            elif not r.get("matched"):
                m["miss"] += 1

            def ui():
                pb.config(maximum=max(total, 1), value=done)
                cur.config(text="(%d/%d)  %s" % (done, total, name[:44]))
                tally.config(text=tally_text())
            self.after(0, ui)

        def finish(matched, scanned, err):
            if err:
                head = "Scraping failed"
            elif cancel_ev.is_set():
                head = "Cancelled"
            elif matched and (m["miss"] or m["err"]):
                head = "Finished with mixed results"
            elif matched:
                head = "Scraping complete"
            else:
                head = "No art found"
            pb.config(value=pb["maximum"])
            cur.config(text=head)
            tally.config(text=err or ("Applied art to %d of %d game%s.\n%s"
                                      % (matched, scanned, "" if scanned == 1 else "s", tally_text())))
            btn.config(text="Close", command=dlg.destroy)
            dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
            self._set_status("Scraped art for %d of %d game(s)" % (matched, scanned))

        def worker():
            err = None
            matched = scanned = 0
            try:
                with tempfile.TemporaryDirectory() as td:
                    matched, scanned = run(td, prog, cancel_ev.is_set)
            except Exception as e:  # noqa: BLE001
                err = str(e)
            if matched:
                try:
                    self.bx.adb.restart_nano()
                except Exception:  # noqa: BLE001
                    pass
            self.after(0, lambda: finish(matched, scanned, err))
            self.after(0, self.refresh)

        threading.Thread(target=worker, daemon=True).start()

    # -- search the scraper and choose the result / art ---------------------
    def _apply_from_result(self, rom, result, kinds):
        applied = []
        with tempfile.TemporaryDirectory() as td:
            for kind in kinds:
                data = getattr(result, kind, None)
                if not data:
                    continue
                local = os.path.join(td, "art.%s" % kind)
                with open(local, "wb") as f:
                    f.write(data)
                self.bx.set_art(rom, local, td, kind=kind,
                                title=result.title or None, scraper=self._source_code())
                applied.append(kind)
        return applied

    def search_choose(self):
        g = self._selected_game()
        if not g:
            return
        try:
            sc = self._make_scraper()
        except ScrapeError as e:
            messagebox.showerror("Scrape", str(e))
            return

        win = tk.Toplevel(self)
        win.title("Search and Choose - %s" % g.display)
        win.transient(self)
        win.geometry("620x480")
        win.grab_set()

        top = ttk.Frame(win, padding=(12, 12, 12, 6))
        top.pack(fill=tk.X)
        ttk.Label(top, text="Search %s:" % sc.label).pack(side=tk.LEFT)
        qvar = tk.StringVar(value=g.display)
        ent = ttk.Entry(top, textvariable=qvar, width=32)
        ent.pack(side=tk.LEFT, padx=6)

        mid = ttk.Frame(win, padding=(12, 0))
        mid.pack(fill=tk.BOTH, expand=True)
        res = ttk.Treeview(mid, columns=("t", "s"), show="headings", height=9, selectmode="browse")
        res.heading("t", text="Result")
        res.heading("s", text="System")
        res.column("t", width=300)
        res.column("s", width=100)
        res.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pv = tk.Label(mid, width=26, bg="#ffffff", relief="solid", bd=1, text="pick a result",
                      fg="#7c7a92")
        pv.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))

        st = ttk.Label(win, text="", style="Dim.TLabel", padding=(12, 4))
        st.pack(fill=tk.X)
        bf = ttk.Frame(win, padding=(12, 0, 12, 12))
        bf.pack(fill=tk.X)

        state = {"cands": [], "result": None, "img": None}

        def do_search():
            res.delete(*res.get_children())
            state["cands"] = []
            st.config(text="searching...")
            q = qvar.get().strip() or g.display

            def work():
                try:
                    cands = sc.search(q, _system_of(g.rom))
                    err = None
                except Exception as e:  # noqa: BLE001
                    cands, err = [], str(e)

                def show():
                    state["cands"] = cands
                    for i, c in enumerate(cands):
                        res.insert("", "end", iid=str(i), values=(c.title, c.system))
                    st.config(text=err or ("%d result(s)" % len(cands)))
                self.after(0, show)
            threading.Thread(target=work, daemon=True).start()

        def on_pick(_evt=None):
            sel = res.selection()
            if not sel:
                return
            cand = state["cands"][int(sel[0])]
            st.config(text="loading art...")
            pv.config(image="", text="loading...")
            state["result"] = None

            def work():
                try:
                    r = sc.fetch_media(cand, want_box=True, want_fan=True)
                except Exception:  # noqa: BLE001
                    r = None

                def show():
                    state["result"] = r
                    if r and r.box:
                        local = os.path.join(self._tmp, "search_prev.img")
                        with open(local, "wb") as f:
                            f.write(r.box)
                        img = None
                        if _HAVE_PIL:
                            try:
                                im = Image.open(local)
                                im.thumbnail((180, 240))
                                img = ImageTk.PhotoImage(im)
                            except Exception:
                                img = None
                        if img is None:
                            try:
                                img = tk.PhotoImage(file=local)
                            except Exception:
                                img = None
                        if img is not None:
                            state["img"] = img
                            pv.config(image=img, text="")
                        else:
                            pv.config(image="", text="(cover found)")
                    else:
                        pv.config(image="", text="no cover")
                    have = [k for k in ("box", "fan") if r and getattr(r, k)]
                    st.config(text=("art: " + ", ".join(have)) if have else "no usable art")
                self.after(0, show)
            threading.Thread(target=work, daemon=True).start()

        res.bind("<<TreeviewSelect>>", on_pick)
        ttk.Button(top, text="Search", style="Accent.TButton", command=do_search).pack(side=tk.LEFT)

        def apply(kinds):
            r = state["result"]
            if not r:
                return
            applied = self._apply_from_result(g.rom, r, kinds)
            win.destroy()
            if applied:
                self._run("Applying + restarting Nano...", self._apply_finish)

        ttk.Button(bf, text="Apply Cover", command=lambda: apply(["box"])).pack(side=tk.LEFT)
        ttk.Button(bf, text="Apply Background", command=lambda: apply(["fan"])).pack(side=tk.LEFT, padx=6)
        ttk.Button(bf, text="Apply Both", style="Accent.TButton",
                   command=lambda: apply(["box", "fan"])).pack(side=tk.LEFT)
        ttk.Button(bf, text="Close", command=win.destroy).pack(side=tk.RIGHT)

        ent.bind("<Return>", lambda _e: do_search())
        do_search()

    def _apply_finish(self):
        self.bx.adb.restart_nano()
        self.after(0, self.refresh)
        self.after(0, lambda: self._set_status("Applied chosen art"))

    def restart_nano(self):
        if self.bx:
            self._run("Restarting Nano...", self.bx.adb.restart_nano)

    # -- worker plumbing ----------------------------------------------------
    def _run(self, status, fn, busy_ui=True):
        if self._busy and busy_ui:
            return
        if busy_ui:
            self._busy = True
            self.config(cursor="watch")
        self._set_status(status)

        def worker():
            try:
                fn()
            except AdbError as e:
                self.after(0, lambda: messagebox.showerror("ADB", str(e)))
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                if busy_ui:
                    self.after(0, self._done)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self):
        self._busy = False
        self.config(cursor="")

    def _set_status(self, text):
        self.status.config(text=text)


def main():
    BoxartGUI().mainloop()


if __name__ == "__main__":
    main()
