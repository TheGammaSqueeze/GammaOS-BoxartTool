# GammaOS Boxart Tool

View, replace, add, and bulk manage **GammaOS Nano** game boxart from your computer over ADB. Ships with a cross-platform **desktop GUI** and a full **command-line interface**.

GammaOS Nano has a built-in scraper and a per-game "Set Boxart" option, but there is no easy way to manage your covers in bulk, back them up, or drop in your own art from a PC. This tool does exactly that: it talks to the same on-device cover cache Nano uses, so anything you set here shows up in the XMB, DSi and Minima themes.

![The GUI with a game selected](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/gui.png)

## What it does

- **View** every game and whether it already has a cover.
- **Add / replace** a cover for any game from a local image (PNG, JPG, WebP, ...).
- **Remove** a custom cover (falls back to the generic cartridge icon).
- **Bulk export** every cover to a folder, with a manifest, so you can back them up.
- **Bulk import** a folder of covers, matched to your games by filename or by a manifest.
- Works with the exact paths, hashing and JSON that Nano expects, so it is safe and reversible.

## Requirements

- A GammaOS handheld running Nano, connected over USB with **USB debugging** enabled.
- **Root ADB.** The cover cache lives under `/data/system`, so the tool runs `adb root` first. This works on the userdebug GammaOS builds; it does not work on a locked user/release build.
- **Python 3.8+** on your computer. The CLI is pure standard library. The GUI uses Tkinter (bundled with Python) and, optionally, [Pillow](https://python-pillow.org/) for nicer cover previews (`pip install pillow`).
- The `adb` binary on your PATH ([platform-tools](https://developer.android.com/tools/releases/platform-tools)).

## Install

```bash
pip install .
# then:
gammaos-boxart --help          # CLI
gammaos-boxart-gui             # GUI
```

Or run it without installing:

```bash
python3 gammaos-boxart.py list         # CLI
python3 gammaos-boxart.py --gui        # GUI
```

## GUI

Launch `gammaos-boxart-gui`. It connects to the first device, lists your games (games that already have a cover are marked with a star), and shows the current cover on the right. Pick a game and:

- **Set / Replace Cover...** choose any image; the tool pushes it and restarts Nano so it shows immediately.
- **Save Current Cover As...** pull the existing cover to your PC.
- **Remove Cover** delete the custom cover.
- **Bulk Import... / Bulk Export...** manage the whole library at once.
- **Restart Nano** reload after external changes.

## CLI

![CLI usage](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/cli.png)

```
gammaos-boxart devices                      # list devices + root status
gammaos-boxart list                         # every game, boxart marked
gammaos-boxart list --with-boxart-only      # only games that have a cover
gammaos-boxart set nes/Spacegulls.nes cover.png       # add or replace a cover
gammaos-boxart set /storage/emulated/0/ROMs/gba/Game.gba art.jpg --title "My Game"
gammaos-boxart get nes/Spacegulls.nes -o out.png      # pull a cover to your PC
gammaos-boxart remove nes/Spacegulls.nes              # remove a custom cover
gammaos-boxart export ./my-covers                     # back up all covers (+ manifest)
gammaos-boxart import ./my-covers                     # bulk import (filename or manifest match)
gammaos-boxart info nes/Spacegulls.nes                # cache location + a rom's cache key
```

A ROM can be given as a full device path (`/storage/emulated/0/ROMs/nes/Game.nes`) or the short `system/file` form (`nes/Game.nes`); the tool resolves it to the exact path Nano uses. Mutating commands restart Nano automatically; pass `--no-restart` to batch several and restart once at the end.

Here is a tool-set cover rendering on the device, in the XMB theme:

![Custom boxart on the device](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/device.png)

## How it works

Nano keeps cover art in a private cache:

```
/data/system/nano_scrape/
    index.json        manifest (version 2)
    names.json        per-game title overrides (version 1)
    <key>.box.png     a game's cover image
    <key>.fan.jpg     a game's fan art
```

- `<key>` is the **64-bit FNV-1a** hash of the game's full ROM path, printed as 16 lowercase hex digits. Nano actually loads a cover from the absolute path stored in the manifest, so this is a naming convention the tool follows for clean interoperability.
- `index.json` maps each ROM to its art and metadata:

```json
{
  "version": 2,
  "items": [
    {
      "rom": "/data/media/0/ROMs/nes/Spacegulls.nes",
      "box": "/data/system/nano_scrape/5cbf8efabe804c89.box.png",
      "scraper": "manual",
      "when": 1786974787,
      "title": "Spacegulls"
    }
  ]
}
```

- The `rom` key is matched by Nano with storage-alias normalization across `/storage/emulated/0`, `/data/media/0`, `/sdcard` and `/storage/self/primary`, so a cover set under any of those resolves for the same game. The tool keys covers under the same view Nano's scanner uses (`/data/media/0` when present) so its files interoperate with Nano's own "Set Boxart" and "Reset Boxart".
- `scraper` is set to `manual` for a user-supplied cover.
- Nano loads `index.json` once at startup, so the tool restarts Nano after changes. Your covers are written to a temp path and copied into place with the correct owner and SELinux label so Nano can read them, and the tool never overwrites an `index.json` it cannot parse, so existing covers are never lost.

## Safety

- The tool refuses to touch a corrupt `index.json`, mirroring Nano's own no-data-loss behaviour.
- Everything is reversible: `remove` deletes a cover, and `export` backs the whole set up first.
- It only writes inside `/data/system/nano_scrape` and pushes temp files to `/data/local/tmp`.

## License

Apache License 2.0. See [LICENSE](LICENSE).

Not affiliated with or endorsed by the ROMs, cover art, or game publishers you use it with. Boxart you add is your responsibility.
