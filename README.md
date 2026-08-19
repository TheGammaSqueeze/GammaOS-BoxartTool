# GammaOS Boxart Tool

View, replace, add, and bulk manage **GammaOS Nano** game boxart from your computer over ADB. Ships with a cross-platform **desktop GUI** and a full **command-line interface**.

GammaOS Nano has a built-in scraper and a per-game "Set Boxart" option, but there is no easy way to manage your covers in bulk, back them up, or drop in your own art from a PC. This tool does exactly that: it talks to the same on-device cover cache Nano uses, so anything you set here shows up in the XMB, DSi and Minima themes.

![The GUI with a game selected](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/gui.png)

## What it does

- **View** every game and whether it already has a cover and a background.
- **Scrape** covers and backgrounds automatically from [ScreenScraper.fr](https://screenscraper.fr), from your PC, for one game or the whole library. GammaOS's developer account is built in, so it works out of the box; the region defaults to World.
- **Add / replace** a game's **cover** (the thumbnail) or its **background** (the fan-art image Nano shows behind the game) from any local image (PNG, JPG, WebP, ...).
- **Remove** a custom cover or background (falls back to the generic cartridge icon).
- **Bulk export** every cover and background to a folder, with a manifest, so you can back them up.
- **Bulk import** a folder of images, matched to your games by filename or by a manifest.
- Works with the exact paths, hashing and JSON that Nano expects, so it is safe and reversible.

"Cover" is the boxart thumbnail. "Background" is the fan-art image Nano displays full-screen behind the game (its Hover Background Art / preview). You can set either or both.

## Download

Prebuilt standalone binaries for **Windows, macOS and Linux** are on the [Releases page](https://github.com/TheGammaSqueeze/GammaOS-BoxartTool/releases). No Python needed: download the one for your system and run it.

| System | File |
|--------|------|
| Windows (x64) | `gammaos-boxart-windows-x86_64.exe` |
| macOS (Apple Silicon) | `gammaos-boxart-macos-arm64` |
| macOS (Intel) | `gammaos-boxart-macos-x86_64` |
| Linux (x64) | `gammaos-boxart-linux-x86_64` |

Run it with **no arguments to open the GUI**, or pass a command (for example `list`) to use the CLI. You still need `adb` from [Android platform-tools](https://developer.android.com/tools/releases/platform-tools) on your PATH.

The binaries are unsigned, so the first launch needs one extra step:

- **Windows**: on the SmartScreen prompt, click "More info" then "Run anyway".
- **macOS**: right-click the file and choose "Open" (or run `xattr -dr com.apple.quarantine gammaos-boxart-macos-*`), then `chmod +x` it.
- **Linux**: `chmod +x gammaos-boxart-linux-x86_64` and run it.

Prefer to run from source instead? See [Install](#install) below.

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

Launch `gammaos-boxart-gui`. It connects to the first device, lists your games (games that already have a cover are marked with a star), and shows the current **cover** and **background** on the right. Pick a game and:

- **Scrape This Game** fetch a cover + background from ScreenScraper for the selected game.
- **Scrape Library...** scrape the whole library (only games missing art, unless you tick overwrite).
- **Set / Replace Cover...** choose any image for the boxart thumbnail.
- **Set / Replace Background...** choose the full-screen fan-art image Nano shows behind the game.
- **Save Cover As...** pull the existing cover to your PC.
- **Remove...** delete the cover, the background, or both.
- **Bulk Import... / Bulk Export...** manage the whole library at once.
- **Restart Nano** reload after external changes.

Pick the scrape **Region** (default World) and, optionally, add your own free ScreenScraper account under **Account...** for higher quota.

Every change pushes the image and restarts Nano so it shows immediately.

## Scrape from ScreenScraper

Instead of hunting for images yourself, the tool can scrape covers and backgrounds directly from [ScreenScraper.fr](https://screenscraper.fr) on your PC and push them to the device. It matches games the same way GammaOS Nano does on-device (by CRC and filename per system), so you get the same results without loading down the handheld.

![Scraping in the GUI](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/scrape_gui.png)

- **Built in and ready.** GammaOS's ScreenScraper developer account is bundled, so scraping works with no setup. You can add your own free ScreenScraper account (GUI: **Account...**, CLI: `--ss-user`/`--ss-pass`) for higher quota.
- **Region defaults to World**, so you get the widest set of art and international titles. Change it in the GUI dropdown or with `--region us|eu|jp|wor`.
- **Only missing art is scraped** by default; tick overwrite (GUI) or pass `--overwrite` (CLI) to re-scrape.

![Scraping from the command line](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/scrape_cli.png)

## CLI

![CLI usage](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/cli.png)

```
gammaos-boxart devices                      # list devices + root status
gammaos-boxart list                         # every game, boxart marked
gammaos-boxart list --with-boxart-only      # only games that have a cover
gammaos-boxart set nes/Spacegulls.nes cover.png       # add or replace the cover
gammaos-boxart set nes/Spacegulls.nes bg.jpg --fan    # add or replace the background (fan art)
gammaos-boxart get nes/Spacegulls.nes -o out.png      # pull the cover to your PC
gammaos-boxart get nes/Spacegulls.nes --fan -o bg.png # pull the background
gammaos-boxart remove nes/Spacegulls.nes              # remove the cover
gammaos-boxart remove nes/Spacegulls.nes --both       # remove cover and background
gammaos-boxart export ./my-covers                     # back up all art (+ manifest)
gammaos-boxart import ./my-covers                     # bulk import (filename or manifest match)
gammaos-boxart scrape nes/Spacegulls.nes              # scrape one game from ScreenScraper
gammaos-boxart scrape-all                             # scrape the whole library (missing art)
gammaos-boxart scrape-all nes --overwrite             # re-scrape one system
gammaos-boxart scrape-all --region us --covers-only   # region + only covers
gammaos-boxart scrape-all --ss-user NAME --ss-pass PW # use your own ScreenScraper account
gammaos-boxart info nes/Spacegulls.nes                # cache location + a rom's cache key
```

A ROM can be given as a full device path (`/storage/emulated/0/ROMs/nes/Game.nes`) or the short `system/file` form (`nes/Game.nes`); the tool resolves it to the exact path Nano uses. Add `--fan` to any `set`/`get`/`remove` to act on the background instead of the cover. Mutating commands restart Nano automatically; pass `--no-restart` to batch several and restart once at the end. In a bulk-import folder, name a background image `<GameName>.fan.png`.

Here is a tool-set **cover** and a tool-set **background** rendering on the device, in the XMB theme:

![Custom cover on the device](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/device.png)

![Custom background (fan art) on the device](https://raw.githubusercontent.com/TheGammaSqueeze/GammaOS-BoxartTool/main/docs/device-background.png)

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
