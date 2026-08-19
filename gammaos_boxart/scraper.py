"""ScreenScraper.fr client for the GammaOS Boxart Tool (pure standard library).

Mirrors the gammaos-nano on-device scraper (NanoScraper.cpp), which is itself
modelled on EmulationStation-DE, so the PC tool matches what the device would fetch:

  * endpoint api2/jeuInfos.php, output=json
  * match by CRC32 (No-Intro standard) + romnom (filename) + systemeid + romtaille
  * cover  = media "box-2D" (fallback "box-3D")
  * fanart = media "fanart" (fallback in-game "ss", then title screen "sstitle")
  * region preference, requested region first then wor, us, ss, eu, jp, cus
  * English-region title preference so we never default to the French community name

Credentials: the built-in GammaOS developer account is used by default (see
_devcreds). A user may pass their own ScreenScraper account (ssid/sspassword),
which is sent alongside for quota and takes over when no built-in creds are baked in.
"""

import json
import urllib.parse
import urllib.request
import zlib

from ._devcreds import builtin_credentials

API_URL = "https://api.screenscraper.fr/api2/jeuInfos.php"

# CRC is only sent for files up to this size (matches nano's kHashMaxBytes). Covers
# cartridge ROMs exactly; larger disc images fall back to romnom + systemeid search.
HASH_MAX_BYTES = 128 * 1024 * 1024

DEFAULT_SOFTNAME = "gammaos-nano"

# romDir / shortname -> ScreenScraper systemeid. Extracted from NanoScraper.cpp
# (es-de-verified). A system not listed here is queried by romnom only.
SYSTEMEID = {
    "nes": 3, "famicom": 3, "fds": 106, "famicomdisksystem": 106,
    "snes": 4, "sfc": 4, "superfamicom": 4, "satellaview": 107,
    "n64": 14, "nintendo64": 14,
    "gb": 9, "gameboy": 9,
    "gbc": 10, "gameboycolor": 10,
    "gba": 12, "gameboyadvance": 12,
    "nds": 15, "ds": 15, "nintendods": 15,
    "3ds": 17, "n3ds": 17,
    "gamecube": 13, "gc": 13, "ngc": 13,
    "wii": 16, "wiiu": 18,
    "virtualboy": 11, "vb": 11, "pokemini": 211,
    "megadrive": 1, "genesis": 1, "md": 1,
    "mastersystem": 2, "sms": 2,
    "gamegear": 21, "gg": 21,
    "segacd": 20, "megacd": 20,
    "sega32x": 19, "32x": 19,
    "saturn": 22, "segasaturn": 22,
    "dreamcast": 23, "dc": 23,
    "sg1000": 109, "naomi": 56,
    "psx": 57, "ps1": 57, "playstation": 57, "psone": 57,
    "ps2": 58, "playstation2": 58,
    "psp": 61, "playstationportable": 61,
    "psvita": 62, "vita": 62, "ps3": 59, "playstation3": 59,
    "pcengine": 31, "tg16": 31, "turbografx16": 31, "pce": 31,
    "pcenginecd": 114, "tg16cd": 114, "turbografxcd": 114,
    "supergrafx": 105, "pcfx": 72,
    "neogeo": 142, "neogeoaes": 142, "neogeomvs": 142, "neogeocd": 70,
    "ngp": 25, "neogeopocket": 25, "ngpc": 82, "neogeopocketcolor": 82,
    "atari2600": 26, "a2600": 26, "atari5200": 40, "a5200": 40,
    "atari7800": 41, "a7800": 41, "atarilynx": 28, "lynx": 28,
    "atarijaguar": 27, "jaguar": 27, "atarijaguarcd": 171,
    "atarist": 42, "atari800": 43, "atari8bit": 43,
    "wonderswan": 45, "ws": 45, "wonderswancolor": 46, "wsc": 46,
    "c64": 66, "commodore64": 66, "amiga": 64, "amigacd32": 130,
    "msx": 113, "msx2": 116,
    "zxspectrum": 76, "spectrum": 76, "amstradcpc": 65, "cpc": 65,
    "x68000": 79, "dos": 135, "pc": 135, "scummvm": 123,
    "3do": 29, "colecovision": 48, "coleco": 48, "intellivision": 115,
    "vectrex": 102, "odyssey2": 104, "o2em": 104, "channelf": 80,
    "pico8": 234, "openbor": 214,
    "arcade": 75, "mame": 75, "fbneo": 75, "fba": 75,
    "cps1": 75, "cps2": 75, "cps3": 75,
}

REGIONS = ["us", "eu", "jp", "wor", "world", "ss", "cus"]


class ScrapeError(RuntimeError):
    pass


class CredentialsError(ScrapeError):
    """Auth / quota failure reported by ScreenScraper (bad creds, over quota)."""


class ScrapeResult:
    def __init__(self):
        self.matched = False
        self.title = ""
        self.box = None      # bytes
        self.fan = None      # bytes
        self.error = ""

    @property
    def got_any(self):
        return bool(self.box or self.fan)


def region_order(region):
    """Requested region first, then the universal fallbacks (mirrors nano)."""
    region = (region or "wor").lower()
    if region == "world":
        region = "wor"
    base = ["wor", "us", "ss", "eu", "jp", "cus"]
    out = [region]
    out += [b for b in base if b != region]
    return out


def systemeid_for(romdir):
    if not romdir:
        return None
    return SYSTEMEID.get(romdir.lower().replace(" ", ""))


def crc32_hex(data):
    """No-Intro-style CRC32 of up to HASH_MAX_BYTES of ROM data, 8 lowercase hex."""
    if not data:
        return ""
    return "%08x" % (zlib.crc32(data[:HASH_MAX_BYTES]) & 0xFFFFFFFF)


class ScreenScraper:
    def __init__(self, devid=None, devpw=None, softname=None,
                 ssid=None, sspassword=None, region="wor", timeout=30):
        builtin = builtin_credentials()
        if devid and devpw:
            self.devid, self.devpw = devid, devpw
            self.softname = softname or (builtin[2] if builtin else DEFAULT_SOFTNAME)
        elif builtin:
            self.devid, self.devpw, self.softname = builtin
            if softname:
                self.softname = softname
        else:
            self.devid = self.devpw = ""
            self.softname = softname or DEFAULT_SOFTNAME
        self.ssid = ssid
        self.sspassword = sspassword
        self.region = (region or "wor").lower()
        self.timeout = timeout

    @property
    def has_dev_creds(self):
        return bool(self.devid and self.devpw)

    # -- low-level ----------------------------------------------------------
    def _get(self, url, params=None, binary=False):
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "gammaos-boxart"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = r.read()
        return data if binary else data.decode("utf-8", "replace")

    def query(self, romnom, systemeid=None, crc=None, size=None):
        """Call jeuInfos and return the parsed 'jeu' dict, or None on no match."""
        if not self.has_dev_creds:
            raise CredentialsError(
                "no ScreenScraper credentials. This build has no built-in developer "
                "account; provide your own with --ss-user/--ss-pass."
            )
        params = [
            ("devid", self.devid), ("devpassword", self.devpw),
            ("softname", self.softname or DEFAULT_SOFTNAME),
            ("output", "json"), ("romnom", romnom),
        ]
        if self.ssid and self.sspassword:
            params += [("ssid", self.ssid), ("sspassword", self.sspassword)]
        if systemeid:
            params.append(("systemeid", str(systemeid)))
        if crc:
            params.append(("crc", crc))
        if size:
            params.append(("romtaille", str(size)))
        try:
            body = self._get(API_URL, params)
        except Exception as e:
            raise ScrapeError("ScreenScraper request failed: %s" % e)
        body = body.strip()
        # ScreenScraper returns plain text (not JSON) on auth / quota / no-game.
        if not body or body[0] not in "{[":
            low = body.lower()
            if "identifiants" in low or "login" in low or "erreur" in low \
                    or "maximum" in low or "quota" in low or "closed" in low:
                raise CredentialsError("ScreenScraper: " + body[:160])
            return None   # no match
        try:
            root = json.loads(body)
        except ValueError:
            raise ScrapeError("ScreenScraper returned invalid JSON")
        jeu = (root.get("response") or {}).get("jeu")
        return jeu if isinstance(jeu, dict) else None

    # -- media / title selection -------------------------------------------
    def _pick_media(self, medias, types):
        regs = region_order(self.region)
        for want in regs:
            for ty in types:
                for m in medias:
                    if m.get("type") == ty and m.get("region") == want and m.get("url"):
                        return m["url"]
        for ty in types:            # any region
            for m in medias:
                if m.get("type") == ty and m.get("url"):
                    return m["url"]
        return None

    def _pick_title(self, noms):
        if not isinstance(noms, list) or not noms:
            return ""
        title_regs = ["us", "wor", "eu", "uk", "au", "ca"]
        if self.region in ("eu", "us", "wor"):
            title_regs = [self.region] + [r for r in title_regs if r != self.region]
        for want in title_regs:
            for nm in noms:
                if nm.get("region") == want and nm.get("text"):
                    return nm["text"]
        for want in ("wor", "us", "jp"):
            for nm in noms:
                if nm.get("region") == want and nm.get("text"):
                    return nm["text"]
        for nm in noms:             # anything non-empty
            if nm.get("text"):
                return nm["text"]
        return ""

    def scrape(self, romnom, romdir, crc=None, size=None,
               want_box=True, want_fan=True):
        """Query for one game and download the selected cover + fan art."""
        res = ScrapeResult()
        jeu = self.query(romnom, systemeid_for(romdir), crc, size)
        if not jeu:
            res.error = "no match"
            return res
        res.matched = True
        res.title = self._pick_title(jeu.get("noms"))
        medias = jeu.get("medias")
        if not isinstance(medias, list):
            res.error = "no media"
            return res
        if want_box:
            url = self._pick_media(medias, ["box-2D", "box-3D"])
            if url:
                res.box = self._download_image(url)
        if want_fan:
            url = self._pick_media(medias, ["fanart", "ss", "sstitle"])
            if url:
                res.fan = self._download_image(url)
        return res

    def _download_image(self, url):
        try:
            data = self._get(url, binary=True)
        except Exception:
            return None
        # Sniff: PNG / JPEG / GIF / WEBP magic. Reject HTML/text error bodies.
        if len(data) < 16:
            return None
        if data[:8].startswith(b"\x89PNG") or data[:3] == b"\xff\xd8\xff" \
                or data[:6] in (b"GIF87a", b"GIF89a") \
                or (data[:4] == b"RIFF" and data[8:12] == b"WEBP") \
                or data[:2] == b"BM":
            return data
        return None
