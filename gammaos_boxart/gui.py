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

from .core import Adb, AdbError, Boxart
from .scraper import ScreenScraper, ScrapeError

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
        self.geometry("1040x790")
        self.minsize(940, 720)
        self.configure(bg="#f7f7fc")

        self.region_var = tk.StringVar(value="World")
        self.ss_user = ""
        self.ss_pass = ""

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
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
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
        ttk.Label(right, text="Scrape from ScreenScraper", style="Head.TLabel").pack(anchor="w")
        srow = ttk.Frame(right)
        srow.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(srow, text="Region:").pack(side=tk.LEFT)
        ttk.Combobox(srow, textvariable=self.region_var, state="readonly", width=9,
                     values=[r[0] for r in REGION_CHOICES]).pack(side=tk.LEFT, padx=6)
        ttk.Button(srow, text="Account...", command=self.ss_account_dialog).pack(side=tk.RIGHT)
        self.btn_scrape = ttk.Button(right, text="Scrape This Game", style="Accent.TButton",
                                     command=self.scrape_selected, state="disabled")
        self.btn_scrape.pack(fill=tk.X, pady=2)

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
        want = self.region_var.get()
        for label, code in REGION_CHOICES:
            if label == want:
                return code
        return "wor"

    def _make_scraper(self):
        ss = ScreenScraper(ssid=self.ss_user or None, sspassword=self.ss_pass or None,
                           region=self._region_code())
        if not ss.has_dev_creds:
            raise ScrapeError(
                "No ScreenScraper credentials. This build has no built-in developer "
                "account; add your own with the Account... button.")
        return ss

    def ss_account_dialog(self):
        win = tk.Toplevel(self)
        win.title("ScreenScraper Account")
        win.transient(self)
        win.grab_set()
        ttk.Label(win, padding=(14, 12, 14, 4), justify="left", wraplength=320,
                  text="Optional. GammaOS's developer account is built in, so this is "
                       "only needed for higher scraping quota. Create a free account at "
                       "screenscraper.fr.").pack(anchor="w")
        fr = ttk.Frame(win, padding=(14, 0, 14, 12))
        fr.pack(fill=tk.X)
        ttk.Label(fr, text="Username:").grid(row=0, column=0, sticky="w", pady=3)
        uvar = tk.StringVar(value=self.ss_user)
        ttk.Entry(fr, textvariable=uvar, width=26).grid(row=0, column=1, padx=6)
        ttk.Label(fr, text="Password:").grid(row=1, column=0, sticky="w", pady=3)
        pvar = tk.StringVar(value=self.ss_pass)
        ttk.Entry(fr, textvariable=pvar, width=26, show="*").grid(row=1, column=1, padx=6)
        bf = ttk.Frame(win, padding=(14, 0, 14, 14))
        bf.pack(fill=tk.X)

        def save():
            self.ss_user = uvar.get().strip()
            self.ss_pass = pvar.get().strip()
            win.destroy()
            self._set_status("ScreenScraper account " + ("set" if self.ss_user else "cleared"))

        ttk.Button(bf, text="Save", style="Accent.TButton", command=save).pack(side=tk.RIGHT)
        ttk.Button(bf, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)

    def scrape_selected(self):
        g = self._selected_game()
        if not g:
            return
        try:
            ss = self._make_scraper()
        except ScrapeError as e:
            messagebox.showerror("ScreenScraper", str(e))
            return
        self._run("Scraping %s..." % g.display, lambda: self._do_scrape_one(g, ss))

    def _do_scrape_one(self, g, ss):
        with tempfile.TemporaryDirectory() as td:
            r = self.bx.scrape_game(g.rom, ss, td, overwrite=True)
        if r.get("box") or r.get("fan"):
            self.bx.adb.restart_nano()
            self.after(0, self.refresh)
            msg = "Scraped '%s'" % (r.get("title") or g.display)
        elif r.get("matched"):
            msg = "Matched but no usable art for %s" % g.display
        else:
            msg = "No ScreenScraper match for %s" % g.display
        self.after(0, lambda: self._set_status(msg))

    def scrape_library(self):
        if not self.bx:
            return
        try:
            ss = self._make_scraper()
        except ScrapeError as e:
            messagebox.showerror("ScreenScraper", str(e))
            return
        win = tk.Toplevel(self)
        win.title("Scrape Library")
        win.transient(self)
        win.grab_set()
        ttk.Label(win, padding=(16, 14, 16, 6), justify="left", wraplength=360,
                  text="Scrape covers and backgrounds for your games from ScreenScraper "
                       "(region: %s). Only games missing art are scraped unless you choose "
                       "to overwrite." % self.region_var.get()).pack(anchor="w")
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
            self._run("Scraping library...", lambda: self._do_scrape_all(ss, wb, wf, ov))

        ttk.Button(bf, text="Start", style="Accent.TButton", command=go).pack(side=tk.RIGHT)
        ttk.Button(bf, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)

    def _do_scrape_all(self, ss, want_box, want_fan, overwrite):
        def prog(done, total, name, r):
            self.after(0, lambda: self._set_status(
                "Scraping %d/%d  %s" % (done, total, name[:40])))
        with tempfile.TemporaryDirectory() as td:
            matched, scanned = self.bx.scrape_missing(
                ss, td, want_box=want_box, want_fan=want_fan,
                overwrite=overwrite, progress=prog)
        if matched:
            self.bx.adb.restart_nano()
        self.after(0, self.refresh)
        self.after(0, lambda: self._set_status(
            "Scraped art for %d of %d games" % (matched, scanned)))

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
