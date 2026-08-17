"""Command-line interface for the GammaOS Boxart Tool."""

import argparse
import os
import sys
import tempfile

from .core import Adb, AdbError, Boxart, cache_key, NANO_DIR


def _adb(args):
    a = Adb(serial=args.serial, adb=args.adb)
    devs = a.list_devices()
    if not devs:
        _die("no device connected. Plug in your GammaOS handheld and enable USB debugging.")
    if not args.serial and len(devs) > 1:
        _die("multiple devices: %s. Pass --serial <id>." % ", ".join(devs))
    a.ensure_root()
    return a


def _die(msg):
    sys.stderr.write("error: %s\n" % msg)
    sys.exit(1)


def cmd_devices(args):
    a = Adb(serial=args.serial, adb=args.adb)
    devs = a.list_devices()
    if not devs:
        print("no devices")
        return
    for d in devs:
        b = Adb(serial=d, adb=args.adb)
        root = "root" if b.is_root() else "not-root (run needs 'adb root')"
        print("%s  [%s]" % (d, root))


def cmd_list(args):
    bx = Boxart(_adb(args))
    games = bx.list_games(include_all=not args.with_boxart_only)
    if args.with_boxart_only:
        games = [g for g in games if g.has_box]
    width = max((len(g.system) for g in games), default=6)
    print("%-3s %-*s %s" % ("BOX", width, "SYSTEM", "GAME"))
    for g in games:
        mark = "[x]" if g.has_box else " . "
        print("%-3s %-*s %s" % (mark, width, g.system, g.display))
    have = sum(1 for g in games if g.has_box)
    print("\n%d games, %d with custom/scraped boxart" % (len(games), have))


def cmd_get(args):
    bx = Boxart(_adb(args))
    out = args.out or (os.path.splitext(os.path.basename(args.rom))[0] + ".png")
    if bx.get_cover(args.rom, out):
        print("saved current cover -> %s" % out)
    else:
        _die("no cover on the device for %s" % args.rom)


def cmd_set(args):
    bx = Boxart(_adb(args))
    with tempfile.TemporaryDirectory() as td:
        rom = bx.canonical_rom(args.rom)
        dest = bx.set_cover(rom, args.image, td, title=args.title)
        print("rom : %s" % rom)
        print("key : %s" % cache_key(rom))
        print("cover -> %s" % dest)
        if not args.no_restart:
            bx.adb.restart_nano()
            print("restarted Nano")
        else:
            print("run with a Nano restart to see it (or: adb shell setprop ctl.stop gammaos-nano; setprop ctl.start gammaos-nano)")


def cmd_remove(args):
    bx = Boxart(_adb(args))
    with tempfile.TemporaryDirectory() as td:
        ok = bx.remove_cover(args.rom, td)
        print("removed cover" if ok else "no cover was set")
        if not args.no_restart:
            bx.adb.restart_nano()
            print("restarted Nano")


def cmd_export(args):
    bx = Boxart(_adb(args))
    n = bx.export_all(args.out, progress=_bar("export"))
    print("\nexported %d covers to %s (with boxart_manifest.json)" % (n, args.out))


def cmd_import(args):
    bx = Boxart(_adb(args))
    with tempfile.TemporaryDirectory() as td:
        applied, _ = bx.import_dir(args.dir, td, mode=args.match, progress=_bar("import"))
        print("\nimported %d covers" % applied)
        if applied and not args.no_restart:
            bx.adb.restart_nano()
            print("restarted Nano")


def cmd_restart(args):
    _adb(args).restart_nano()
    print("restarted Nano")


def cmd_info(args):
    a = _adb(args)
    print("cache dir : %s" % NANO_DIR)
    print("owner     : %s" % a.owner(NANO_DIR))
    for f in ("index.json", "names.json"):
        p = "%s/%s" % (NANO_DIR, f)
        sz = a.sh("stat -c %%s %s 2>/dev/null || echo -" % ("'" + p + "'"), check=False).strip()
        print("%-10s: %s bytes" % (f, sz))
    if args.rom:
        print("rom       : %s" % args.rom)
        print("cache key : %s" % cache_key(Boxart(a).canonical_rom(args.rom)))


def _bar(label):
    def p(done, total, rom):
        pct = int(done * 100 / max(total, 1))
        sys.stdout.write("\r%s %3d%% (%d/%d)  " % (label, pct, done, total))
        sys.stdout.flush()
    return p


def build_parser():
    ap = argparse.ArgumentParser(
        prog="gammaos-boxart",
        description="Manage GammaOS Nano game boxart over ADB: view, replace, add, "
                    "bulk import and export. Needs root ADB (GammaOS userdebug builds).",
    )
    ap.add_argument("--serial", help="target a specific device serial")
    ap.add_argument("--adb", default="adb", help="path to the adb binary")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="list connected devices and root status").set_defaults(func=cmd_devices)

    p = sub.add_parser("list", help="list games and whether they have boxart")
    p.add_argument("--with-boxart-only", action="store_true", help="only games that already have a cover")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("get", help="save a game's current cover to a local file")
    p.add_argument("rom", help="ROM path (e.g. /storage/emulated/0/ROMs/nes/Game.nes) or 'system/file'")
    p.add_argument("-o", "--out", help="output image path")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set", help="add or replace a game's cover from a local image")
    p.add_argument("rom", help="ROM path or 'system/file'")
    p.add_argument("image", help="local image file (png/jpg/...)")
    p.add_argument("--title", help="also set the displayed title")
    p.add_argument("--no-restart", action="store_true", help="do not restart Nano afterwards")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("remove", help="remove a game's custom cover")
    p.add_argument("rom", help="ROM path or 'system/file'")
    p.add_argument("--no-restart", action="store_true")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("export", help="pull every cover into a folder (+ manifest)")
    p.add_argument("out", help="output folder")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="bulk import covers from a folder")
    p.add_argument("dir", help="input folder")
    p.add_argument("--match", choices=["filename", "manifest", "auto"], default="auto",
                   help="match by filename, by an export manifest, or auto")
    p.add_argument("--no-restart", action="store_true")
    p.set_defaults(func=cmd_import)

    sub.add_parser("restart", help="restart Nano so on-disk changes load").set_defaults(func=cmd_restart)

    p = sub.add_parser("info", help="show the cache location and a rom's cache key")
    p.add_argument("rom", nargs="?", help="optional ROM path to print the cache key for")
    p.set_defaults(func=cmd_info)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except AdbError as e:
        _die(str(e))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
