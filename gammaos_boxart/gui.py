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
        self.geometry("980x690")
        self.minsize(860, 600)
        self.configure(bg="#f7f7fc")

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
        ttk.Label(right, text="Cover", style="Head.TLabel").pack(anchor="w")
        self.preview = tk.Label(right, width=240, height=250, bg="#ffffff",
                                relief="solid", bd=1, text="select a game", fg="#7c7a92")
        self.preview.pack(pady=(6, 4), fill=tk.X)
        self.btn_set = ttk.Button(right, text="Set / Replace Cover...", style="Accent.TButton",
                                  command=self.set_cover, state="disabled")
        self.btn_set.pack(fill=tk.X, pady=2)

        ttk.Label(right, text="Background (fan art)", style="Head.TLabel").pack(anchor="w", pady=(10, 0))
        self.fan_preview = tk.Label(right, width=240, height=120, bg="#ffffff",
                                    relief="solid", bd=1, text="none", fg="#7c7a92")
        self.fan_preview.pack(pady=(6, 4), fill=tk.X)
        self.btn_setfan = ttk.Button(right, text="Set / Replace Background...",
                                     command=self.set_background, state="disabled")
        self.btn_setfan.pack(fill=tk.X, pady=2)

        self.sel_lbl = ttk.Label(right, text="", style="Dim.TLabel", wraplength=260, justify="left")
        self.sel_lbl.pack(anchor="w", pady=(8, 6))
        self.btn_save = ttk.Button(right, text="Save Cover As...",
                                   command=self.save_cover_as, state="disabled")
        self.btn_save.pack(fill=tk.X, pady=2)
        self.btn_rm = ttk.Button(right, text="Remove...", command=self.remove_art_dialog,
                                 state="disabled")
        self.btn_rm.pack(fill=tk.X, pady=2)

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
        maxsz = (240, 250) if attr == "_preview_img" else (240, 120)
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
