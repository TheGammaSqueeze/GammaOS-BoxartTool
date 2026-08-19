"""
Core model and ADB layer for the GammaOS Boxart Tool.

GammaOS Nano stores game cover art (boxart) in a private on-device cache:

    /data/system/nano_scrape/
        index.json      manifest, version 2: rom -> {box, fan, title, scraper, ...}
        names.json      title overrides, version 1: rom -> name
        <key>.box.png   the cover image for a game
        <key>.fan.jpg   the fan art for a game

  * <key> is the 64-bit FNV-1a hash of the game's full ROM path, printed as
    16 lowercase hex digits. This is only a naming convention: Nano actually
    loads a cover from the absolute path stored in the manifest "box" field,
    so the tool follows the same convention for clean interop.
  * The "rom" key is matched by Nano with storage-alias normalization across
    /storage/emulated/0, /data/media/0, /sdcard and /storage/self/primary, so
    a cover set under any of those prefixes resolves for the same game.
  * "scraper" is set to "manual" for a user-supplied cover.
  * Nano loads index.json once at startup, so changes need a Nano restart to
    show. The tool restarts Nano for you unless you pass --no-restart.

Nano runs as root and the cache dir is 0700, so the tool needs root ADB
(adb root, available on the userdebug GammaOS builds). All writes are made to
a temp path and copied into place, then chowned to match the cache dir owner
and re-labelled with restorecon so Nano can read them.
"""

import json
import os
import posixpath
import subprocess
import time

NANO_DIR = "/data/system/nano_scrape"
INDEX_PATH = NANO_DIR + "/index.json"
NAMES_PATH = NANO_DIR + "/names.json"
SYSTEMS_PATH = "/data/system/nano_systems.json"

# Internal-storage ROM roots, in the exact order Nano's scanner tries them.
# The first one that actually contains the file is the canonical key Nano uses.
ROM_ROOTS = ["/data/media/0/ROMs", "/sdcard/ROMs", "/storage/emulated/0/ROMs"]
STORAGE_ALIASES = ["/storage/emulated/0", "/data/media/0", "/sdcard", "/storage/self/primary"]

FNV64_OFFSET = 0xCBF29CE484222325
FNV64_PRIME = 0x100000001B3
MASK64 = 0xFFFFFFFFFFFFFFFF

DEFAULT_EXTS = [".zip", ".7z"]

# The two kinds of art Nano stores per game. "box" is the cover/thumbnail;
# "fan" is the fan art shown as the background / preview behind the game.
ART = {
    "box": {"field": "box", "ext": "box.png", "label": "cover"},
    "fan": {"field": "fan", "ext": "fan.jpg", "label": "background"},
}


def cache_key(rom_path: str) -> str:
    """64-bit FNV-1a of the ROM path, 16 lowercase hex digits (Nano's scheme)."""
    h = FNV64_OFFSET
    for b in rom_path.encode("utf-8"):
        h = ((h ^ b) * FNV64_PRIME) & MASK64
    return "%016x" % h


class AdbError(RuntimeError):
    pass


class Adb:
    """Thin wrapper around the adb CLI, optionally pinned to one serial."""

    def __init__(self, serial=None, adb="adb"):
        self.serial = serial
        self.adb = adb

    def _base(self):
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def raw(self, args, input_bytes=None, binary=False, check=True, timeout=120):
        cmd = self._base() + list(args)
        p = subprocess.run(
            cmd, input=input_bytes,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
        if check and p.returncode != 0:
            err = p.stderr.decode("utf-8", "replace").strip()
            raise AdbError("adb %s failed: %s" % (" ".join(args), err or p.returncode))
        return p.stdout if binary else p.stdout.decode("utf-8", "replace")

    # -- device / root ------------------------------------------------------
    def list_devices(self):
        out = self.raw(["devices"], check=False)
        devs = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if line and "\t" in line and line.split("\t")[1] == "device":
                devs.append(line.split("\t")[0])
        return devs

    def uid(self):
        return self.raw(["shell", "id", "-u"], check=False).strip()

    def is_root(self):
        return self.uid() == "0"

    def ensure_root(self):
        if self.is_root():
            return True
        self.raw(["root"], check=False, timeout=30)
        # adbd restarts; wait for the device to come back as root
        self.raw(["wait-for-device"], check=False, timeout=60)
        for _ in range(20):
            if self.is_root():
                return True
            time.sleep(0.5)
        raise AdbError(
            "could not get root adb. GammaOS userdebug builds allow 'adb root'; "
            "a user/release build does not, and this tool needs it."
        )

    # -- shell helpers ------------------------------------------------------
    def sh(self, command, check=True):
        return self.raw(["shell", command], check=check)

    def exists(self, path):
        out = self.sh("[ -e %s ] && echo Y || echo N" % _q(path), check=False)
        return out.strip().endswith("Y")

    def cat(self, path):
        """Read a file as bytes (root). Empty bytes if the file does not exist."""
        if not self.exists(path):
            return b""
        return self.raw(["exec-out", "cat %s" % _q(path)], binary=True, check=False)

    def owner(self, path):
        out = self.sh("stat -c %%U:%%G %s" % _q(path), check=False).strip()
        return out if ":" in out else "root:root"

    def file_size(self, path):
        out = self.sh("stat -c %%s %s 2>/dev/null || echo 0" % _q(path), check=False).strip()
        try:
            return int(out.split()[0])
        except (ValueError, IndexError):
            return 0

    def read_rom_head(self, path, cap_mb=128):
        """Read up to cap_mb of a ROM (for a CRC32 match). Exact CRC for smaller files."""
        return self.raw(
            ["exec-out", "dd if=%s bs=1048576 count=%d 2>/dev/null" % (_q(path), cap_mb)],
            binary=True, check=False, timeout=300,
        )

    def pull(self, remote, local):
        os.makedirs(os.path.dirname(os.path.abspath(local)) or ".", exist_ok=True)
        self.raw(["pull", remote, local])

    def put_file(self, local, remote, mode="600"):
        """Push a local file into a root-owned path with correct owner + SELinux label."""
        base = posixpath.basename(remote)
        tmp = "/data/local/tmp/.gbt_" + base
        self.raw(["push", local, tmp])
        own = self.owner(posixpath.dirname(remote))
        script = (
            "cp {tmp} {dst} && chmod {mode} {dst} && chown {own} {dst} && "
            "(restorecon {dst} 2>/dev/null || true) && rm -f {tmp}"
        ).format(tmp=_q(tmp), dst=_q(remote), mode=mode, own=own)
        self.sh(script)

    def rm(self, remote):
        self.sh("rm -f %s" % _q(remote), check=False)

    def restart_nano(self, wait=3.0):
        self.sh("setprop ctl.stop gammaos-nano", check=False)
        time.sleep(0.6)
        self.sh("setprop ctl.start gammaos-nano", check=False)
        time.sleep(wait)


def _q(s):
    """Single-quote a token for the device shell."""
    return "'" + s.replace("'", "'\\''") + "'"


class Game:
    __slots__ = ("rom", "system", "filename", "title", "box", "fan",
                 "scraper", "when", "has_box", "has_fan")

    def __init__(self, rom, system="", filename="", title="", box="", fan="",
                 scraper="", when=0):
        self.rom = rom
        self.system = system
        self.filename = filename or posixpath.basename(rom)
        self.title = title
        self.box = box
        self.fan = fan
        self.scraper = scraper
        self.when = when
        self.has_box = bool(box)
        self.has_fan = bool(fan)

    @property
    def display(self):
        return self.title or os.path.splitext(self.filename)[0]

    def __repr__(self):
        return "<Game %s box=%s>" % (self.rom, bool(self.box))


class Boxart:
    """High-level boxart operations against one device."""

    def __init__(self, adb: Adb):
        self.adb = adb
        self._systems = None

    # -- manifest I/O -------------------------------------------------------
    def read_index(self):
        data = self.adb.cat(INDEX_PATH)
        if not data:
            return {"version": 2, "items": []}
        try:
            obj = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            raise AdbError(
                "index.json on the device is not valid JSON. Refusing to touch it "
                "so no boxart is lost. Fix or remove %s first." % INDEX_PATH
            )
        obj.setdefault("version", 2)
        obj.setdefault("items", [])
        return obj

    def write_index(self, obj, tmpdir):
        obj["version"] = 2
        local = os.path.join(tmpdir, "index.json")
        with open(local, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        self.adb.put_file(local, INDEX_PATH)

    def read_names(self):
        data = self.adb.cat(NAMES_PATH)
        if not data:
            return {}
        try:
            obj = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            return {}
        out = {}
        for it in obj.get("items", []):
            if it.get("rom") and it.get("name"):
                out[it["rom"]] = it["name"]
        return out

    # -- rom-path resolution (match Nano's scanner) -------------------------
    def canonical_rom(self, rom_or_relpath):
        """
        Return the ROM path exactly as Nano keys it. Accepts either a full path
        or a 'system/file' relative path, and picks the first internal-storage
        view that actually holds the file (the same order Nano's scanner uses).
        """
        p = rom_or_relpath
        if p.startswith("/"):
            # Already absolute. If it is one of the alias prefixes, prefer the
            # canonical /data/media/0 form when that view exists.
            for a in STORAGE_ALIASES:
                if p.startswith(a + "/ROMs/"):
                    rest = p[len(a):]
                    for root_alias in ("/data/media/0", "/sdcard", "/storage/emulated/0"):
                        cand = root_alias + rest
                        if self.adb.exists(cand):
                            return cand
                    return p
            return p
        # relative "system/file"
        for root in ROM_ROOTS:
            cand = root + "/" + p
            if self.adb.exists(cand):
                return cand
        return ROM_ROOTS[0] + "/" + p

    # -- systems / enumeration ---------------------------------------------
    def systems(self):
        if self._systems is not None:
            return self._systems
        data = self.adb.cat(SYSTEMS_PATH)
        out = []
        if data:
            try:
                obj = json.loads(data.decode("utf-8", "replace"))
                for s in obj.get("systems", []):
                    if not s.get("enabled", True):
                        continue
                    exts = [e.lower() for e in s.get("extensions", []) if e]
                    out.append({
                        "id": s.get("id", ""),
                        "romDir": s.get("romDir", s.get("id", "")),
                        "name": s.get("displayName", s.get("id", "")),
                        "exts": exts + DEFAULT_EXTS,
                    })
            except ValueError:
                pass
        self._systems = out
        return out

    def enumerate_games(self, max_depth=2):
        """Best-effort list of games on internal storage, keyed like Nano."""
        games = []
        seen = set()
        for sys in self.systems():
            romdir = sys["romDir"]
            base = None
            for root in ROM_ROOTS:
                if self.adb.exists(root + "/" + romdir):
                    base = root + "/" + romdir
                    break
            if not base:
                continue
            listing = self.adb.sh(
                "find %s -maxdepth %d -type f 2>/dev/null" % (_q(base), max_depth),
                check=False,
            )
            for line in listing.splitlines():
                line = line.strip()
                if not line:
                    continue
                ext = os.path.splitext(line)[1].lower()
                if sys["exts"] and ext not in sys["exts"]:
                    continue
                if line in seen:
                    continue
                seen.add(line)
                games.append(Game(rom=line, system=sys["name"],
                                  filename=posixpath.basename(line)))
        return games

    def list_games(self, include_all=True, max_depth=2):
        """
        Return games with their boxart state. Merges the manifest (games that
        already have a cover) with a scan of the ROM folders (games that do not).
        """
        idx = self.read_index()
        names = self.read_names()
        by_rom = {}
        for it in idx.get("items", []):
            rom = it.get("rom")
            if not rom:
                continue
            g = Game(rom=rom, filename=posixpath.basename(rom),
                     title=it.get("title", ""), box=it.get("box", ""),
                     fan=it.get("fan", ""),
                     scraper=it.get("scraper", ""), when=it.get("when", 0))
            g.system = _system_of(rom)
            by_rom[_norm(rom)] = g
        if include_all:
            for g in self.enumerate_games(max_depth=max_depth):
                key = _norm(g.rom)
                if key not in by_rom:
                    by_rom[key] = g
        # apply name overrides for display
        for g in by_rom.values():
            if not g.title:
                ov = names.get(g.rom) or names.get(_swap_alias(g.rom))
                if ov:
                    g.title = ov
        return sorted(by_rom.values(), key=lambda g: (g.system.lower(), g.display.lower()))

    def find_entry(self, idx, rom):
        """Locate a manifest item for rom, honouring alias normalization."""
        want = _norm(rom)
        for it in idx.get("items", []):
            if _norm(it.get("rom", "")) == want:
                return it
        return None

    # -- operations ---------------------------------------------------------
    def get_art(self, rom, out_path, kind="box"):
        """Pull a game's current cover or background to a local file."""
        a = ART[kind]
        idx = self.read_index()
        it = self.find_entry(idx, rom)
        p = it.get(a["field"]) if it else ""
        if not p:
            p = "%s/%s.%s" % (NANO_DIR, cache_key(self.canonical_rom(rom)), a["ext"])
        if not self.adb.exists(p):
            return False
        self.adb.pull(p, out_path)
        return True

    def set_art(self, rom, image_path, tmpdir, kind="box", title=None, scraper="manual"):
        """Add or replace a game's cover ('box') or background ('fan')."""
        if not os.path.isfile(image_path):
            raise AdbError("image not found: %s" % image_path)
        a = ART[kind]
        rom = self.canonical_rom(rom)
        dest = "%s/%s.%s" % (NANO_DIR, cache_key(rom), a["ext"])
        self.adb.sh("mkdir -p %s" % _q(NANO_DIR), check=False)
        self.adb.put_file(image_path, dest)
        idx = self.read_index()
        it = self.find_entry(idx, rom)
        if it is None:
            it = {"rom": rom}
            idx["items"].append(it)
        it[a["field"]] = dest
        it["scraper"] = scraper
        it["when"] = int(time.time())
        if title:
            it["title"] = title
        elif not it.get("title"):
            it["title"] = os.path.splitext(posixpath.basename(rom))[0]
        self.write_index(idx, tmpdir)
        return dest

    def remove_art(self, rom, tmpdir, kind=None):
        """Remove a game's cover, background, or both (kind=None)."""
        rom = self.canonical_rom(rom)
        idx = self.read_index()
        it = self.find_entry(idx, rom)
        kinds = [kind] if kind else ["box", "fan"]
        removed = False
        for k in kinds:
            a = ART[k]
            if it and it.get(a["field"]):
                self.adb.rm(it[a["field"]])
                removed = True
            self.adb.rm("%s/%s.%s" % (NANO_DIR, cache_key(rom), a["ext"]))
            if it:
                it.pop(a["field"], None)
        if it:
            keep = any(it.get(x) for x in ("box", "fan", "desc", "genre", "players",
                                           "rating", "date", "dev", "pub"))
            if not keep:
                idx["items"] = [x for x in idx["items"] if x is not it]
            self.write_index(idx, tmpdir)
        return removed

    # backward-compatible cover helpers
    def get_cover(self, rom, out_path):
        return self.get_art(rom, out_path, "box")

    def set_cover(self, rom, image_path, tmpdir, title=None):
        return self.set_art(rom, image_path, tmpdir, "box", title)

    def remove_cover(self, rom, tmpdir):
        return self.remove_art(rom, tmpdir, "box")

    def export_all(self, out_dir, progress=None):
        """
        Pull every cover and background into out_dir/<system>/ plus a manifest.
        Covers are <name>.png, backgrounds are <name>.fan.png.
        """
        os.makedirs(out_dir, exist_ok=True)
        idx = self.read_index()
        manifest = {"version": 2, "covers": []}
        items = [it for it in idx.get("items", []) if it.get("box") or it.get("fan")]
        for i, it in enumerate(items):
            rom = it["rom"]
            sysname = _system_of(rom)
            base = os.path.splitext(posixpath.basename(rom))[0]
            sysdir = os.path.join(out_dir, _safe(sysname))
            os.makedirs(sysdir, exist_ok=True)
            entry = {"rom": rom, "system": sysname, "title": it.get("title", "")}
            if it.get("box") and self.adb.exists(it["box"]):
                local = os.path.join(sysdir, _safe(base) + ".png")
                self.adb.pull(it["box"], local)
                entry["box"] = os.path.relpath(local, out_dir)
            if it.get("fan") and self.adb.exists(it["fan"]):
                local = os.path.join(sysdir, _safe(base) + ".fan.png")
                self.adb.pull(it["fan"], local)
                entry["fan"] = os.path.relpath(local, out_dir)
            if entry.get("box") or entry.get("fan"):
                manifest["covers"].append(entry)
            if progress:
                progress(i + 1, len(items), rom)
        with open(os.path.join(out_dir, "boxart_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        return len(manifest["covers"])

    def import_dir(self, in_dir, tmpdir, mode="auto", progress=None):
        """
        Bulk import covers and backgrounds. Two modes:
          manifest: read boxart_manifest.json (from export) and re-apply by rom.
          filename: match images to games by base filename. A file named
                    <name>.fan.<ext> sets the background; otherwise the cover.
        Returns (applied, skipped).
        """
        jobs = []  # (rom, image_local, kind, title)
        man = os.path.join(in_dir, "boxart_manifest.json")
        if mode == "manifest" or (mode == "auto" and os.path.isfile(man)):
            with open(man, encoding="utf-8") as f:
                m = json.load(f)
            for c in m.get("covers", []):
                for kind in ("box", "fan"):
                    rel = c.get(kind) or (c.get("file") if kind == "box" else None)
                    if rel:
                        img = os.path.join(in_dir, rel)
                        if os.path.isfile(img):
                            jobs.append((c["rom"], img, kind, c.get("title", "")))
        else:
            lib = {}
            for g in self.list_games(include_all=True):
                lib.setdefault(os.path.splitext(g.filename)[0].lower(), g.rom)
            for root, _dirs, files in os.walk(in_dir):
                for fn in files:
                    stem, ext = os.path.splitext(fn)
                    if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                        continue
                    kind = "box"
                    if stem.lower().endswith(".fan"):
                        kind = "fan"
                        stem = stem[:-4]
                    rom = lib.get(stem.lower())
                    if rom:
                        jobs.append((rom, os.path.join(root, fn), kind, ""))
        applied = 0
        for i, (rom, img, kind, title) in enumerate(jobs):
            self.set_art(rom, img, tmpdir, kind=kind, title=title or None)
            applied += 1
            if progress:
                progress(i + 1, len(jobs), rom)
        return applied, 0


    # -- scraping (ScreenScraper via the PC) -------------------------------
    def scrape_game(self, rom, scraper, tmpdir, want_box=True, want_fan=True,
                    overwrite=False, use_crc=True, title_override=None):
        """
        Scrape one game on the PC and push the art to the device. Returns a small
        dict: {"matched", "box", "fan", "title", "skipped", "error"}.
        scraper is a gammaos_boxart.scraper.ScreenScraper instance.
        """
        rom = self.canonical_rom(rom)
        romdir = _system_of(rom)
        romnom = posixpath.basename(rom)

        if not overwrite:
            idx = self.read_index()
            it = self.find_entry(idx, rom)
            have_box = bool(it and it.get("box") and self.adb.exists(it["box"]))
            have_fan = bool(it and it.get("fan") and self.adb.exists(it["fan"]))
            want_box = want_box and not have_box
            want_fan = want_fan and not have_fan
            if not want_box and not want_fan:
                return {"matched": False, "skipped": True, "box": False,
                        "fan": False, "title": "", "error": ""}

        crc = None
        size = self.adb.file_size(rom)
        if use_crc and 0 < size <= 128 * 1024 * 1024:
            from .scraper import crc32_hex
            crc = crc32_hex(self.adb.read_rom_head(rom))

        result = scraper.scrape(title_override or romnom, romdir, crc=crc, size=size or None,
                                want_box=want_box, want_fan=want_fan)
        out = {"matched": result.matched, "skipped": False, "box": False,
               "fan": False, "title": result.title, "error": result.error}
        if not result.matched:
            return out
        for kind, data in (("box", result.box), ("fan", result.fan)):
            if not data:
                continue
            local = os.path.join(tmpdir, "%s.%s" % (cache_key(rom), ART[kind]["ext"]))
            with open(local, "wb") as f:
                f.write(data)
            self.set_art(rom, local, tmpdir, kind=kind,
                         title=result.title or None, scraper="screenscraper")
            out[kind] = True
        return out

    def scrape_missing(self, scraper, tmpdir, systems=None, want_box=True,
                       want_fan=True, overwrite=False, use_crc=True, progress=None):
        """
        Scrape every game (optionally limited to a set of system names/romDirs).
        By default only games missing the requested art are scraped; overwrite
        re-scrapes all. Returns (matched, scanned).
        """
        games = self.list_games(include_all=True)
        if systems:
            want = set(s.lower() for s in systems)
            games = [g for g in games
                     if g.system.lower() in want or _system_of(g.rom).lower() in want]
        matched = 0
        for i, g in enumerate(games):
            try:
                r = self.scrape_game(g.rom, scraper, tmpdir, want_box=want_box,
                                     want_fan=want_fan, overwrite=overwrite,
                                     use_crc=use_crc)
                if r.get("box") or r.get("fan"):
                    matched += 1
            except Exception as e:
                r = {"error": str(e)}
            if progress:
                progress(i + 1, len(games), g.display, r)
        return matched, len(games)


def _norm(rom):
    """Fold storage-alias prefixes to a single identity for matching."""
    for a in STORAGE_ALIASES:
        if rom.startswith(a + "/"):
            return "/storage/emulated/0" + rom[len(a):]
    return rom


def _swap_alias(rom):
    return _norm(rom)


def _system_of(rom):
    """Best-effort system name from a .../ROMs/<system>/... path."""
    parts = rom.split("/ROMs/", 1)
    if len(parts) == 2:
        seg = parts[1].split("/", 1)[0]
        return seg
    return posixpath.basename(posixpath.dirname(rom))


def _safe(name):
    keep = "".join(c if c.isalnum() or c in " ._-" else "_" for c in name)
    return keep.strip() or "unnamed"
