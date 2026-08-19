"""Scraper clients for the GammaOS Boxart Tool (pure standard library).

Two sources, mirroring the gammaos-nano on-device scraper (NanoScraper.cpp, itself
modelled on EmulationStation-DE) so the PC tool matches what the device would fetch:

  * ScreenScraper.fr - jeuInfos.php (CRC + filename match) and jeuRecherche.php
    (keyword search). GammaOS's developer account is built in (see _devcreds);
    a user account (ssid/sspassword) can be added for quota. Cover = box-2D
    (fallback box-3D); fanart = fanart (fallback ss, sstitle). Region-preferred,
    requested region first then wor, us, ss, eu, jp, cus. English-region title.
  * TheGamesDB - Games/ByGameName + Games/Images. Requires the user's own API key
    (no key is bundled, to respect TheGamesDB's quota). Cover = boxart side=front;
    fanart = fanart.

Both expose the same interface:
  scrape(romnom, romdir, crc, size, want_box, want_fan) -> ScrapeResult   (auto match)
  search(query, romdir, limit) -> [Candidate]                             (keyword search)
  fetch_media(candidate, want_box, want_fan) -> ScrapeResult              (a chosen result)
"""

import json
import urllib.parse
import urllib.request
import zlib

from ._devcreds import builtin_credentials

SS_INFO_URL = "https://api.screenscraper.fr/api2/jeuInfos.php"
SS_SEARCH_URL = "https://api.screenscraper.fr/api2/jeuRecherche.php"
TGDB_BYNAME_URL = "https://api.thegamesdb.net/v1/Games/ByGameName"
TGDB_IMAGES_URL = "https://api.thegamesdb.net/v1/Games/Images"

HASH_MAX_BYTES = 128 * 1024 * 1024
DEFAULT_SOFTNAME = "gammaos-nano"

# Selectable sources: (label, id).
SOURCES = [("ScreenScraper", "screenscraper"), ("TheGamesDB", "thegamesdb")]

# romDir / shortname -> ScreenScraper systemeid (extracted from NanoScraper.cpp).
SYSTEMEID = {
    "nes": 3, "famicom": 3, "fds": 106, "famicomdisksystem": 106,
    "snes": 4, "sfc": 4, "superfamicom": 4, "satellaview": 107,
    "n64": 14, "nintendo64": 14, "gb": 9, "gameboy": 9, "gbc": 10, "gameboycolor": 10,
    "gba": 12, "gameboyadvance": 12, "nds": 15, "ds": 15, "nintendods": 15,
    "3ds": 17, "n3ds": 17, "gamecube": 13, "gc": 13, "ngc": 13, "wii": 16, "wiiu": 18,
    "virtualboy": 11, "vb": 11, "pokemini": 211, "megadrive": 1, "genesis": 1, "md": 1,
    "mastersystem": 2, "sms": 2, "gamegear": 21, "gg": 21, "segacd": 20, "megacd": 20,
    "sega32x": 19, "32x": 19, "saturn": 22, "segasaturn": 22, "dreamcast": 23, "dc": 23,
    "sg1000": 109, "naomi": 56, "psx": 57, "ps1": 57, "playstation": 57, "psone": 57,
    "ps2": 58, "playstation2": 58, "psp": 61, "playstationportable": 61,
    "psvita": 62, "vita": 62, "ps3": 59, "playstation3": 59,
    "pcengine": 31, "tg16": 31, "turbografx16": 31, "pce": 31,
    "pcenginecd": 114, "tg16cd": 114, "turbografxcd": 114, "supergrafx": 105, "pcfx": 72,
    "neogeo": 142, "neogeoaes": 142, "neogeomvs": 142, "neogeocd": 70,
    "ngp": 25, "neogeopocket": 25, "ngpc": 82, "neogeopocketcolor": 82,
    "atari2600": 26, "a2600": 26, "atari5200": 40, "a5200": 40, "atari7800": 41, "a7800": 41,
    "atarilynx": 28, "lynx": 28, "atarijaguar": 27, "jaguar": 27, "atarijaguarcd": 171,
    "atarist": 42, "atari800": 43, "atari8bit": 43, "wonderswan": 45, "ws": 45,
    "wonderswancolor": 46, "wsc": 46, "c64": 66, "commodore64": 66, "amiga": 64, "amigacd32": 130,
    "msx": 113, "msx2": 116, "zxspectrum": 76, "spectrum": 76, "amstradcpc": 65, "cpc": 65,
    "x68000": 79, "dos": 135, "pc": 135, "scummvm": 123, "3do": 29,
    "colecovision": 48, "coleco": 48, "intellivision": 115, "vectrex": 102,
    "odyssey2": 104, "o2em": 104, "channelf": 80, "pico8": 234, "openbor": 214,
    "arcade": 75, "mame": 75, "fbneo": 75, "fba": 75, "cps1": 75, "cps2": 75, "cps3": 75,
}

# romDir / shortname -> TheGamesDB platform id (extracted from NanoScraper.cpp).
TGDB_PLATFORM = {
    "nes": 7, "famicom": 7, "fds": 4936, "famicomdisksystem": 4936, "snes": 6, "sfc": 6,
    "superfamicom": 6, "satellaview": 6, "n64": 3, "nintendo64": 3, "gb": 4, "gameboy": 4,
    "gbc": 41, "gameboycolor": 41, "gba": 5, "gameboyadvance": 5, "nds": 8, "ds": 8,
    "nintendods": 8, "3ds": 4912, "n3ds": 4912, "gamecube": 2, "gc": 2, "ngc": 2, "wii": 9,
    "wiiu": 38, "virtualboy": 4918, "vb": 4918, "pokemini": 4957, "megadrive": 36,
    "genesis": 18, "md": 36, "mastersystem": 35, "sms": 35, "gamegear": 20, "gg": 20,
    "segacd": 21, "megacd": 21, "sega32x": 33, "32x": 33, "saturn": 17, "segasaturn": 17,
    "dreamcast": 16, "dc": 16, "sg1000": 4949, "naomi": 23, "psx": 10, "ps1": 10,
    "playstation": 10, "psone": 10, "ps2": 11, "playstation2": 11, "psp": 13,
    "playstationportable": 13, "psvita": 39, "vita": 39, "ps3": 12, "playstation3": 12,
    "pcengine": 34, "tg16": 34, "turbografx16": 34, "pce": 34, "pcenginecd": 4955,
    "tg16cd": 4955, "turbografxcd": 4955, "supergrafx": 34, "pcfx": 4930, "neogeo": 24,
    "neogeoaes": 24, "neogeomvs": 24, "neogeocd": 4956, "ngp": 4922, "neogeopocket": 4922,
    "ngpc": 4923, "neogeopocketcolor": 4923, "atari2600": 22, "a2600": 22, "atari5200": 26,
    "a5200": 26, "atari7800": 27, "a7800": 27, "atarilynx": 4924, "lynx": 4924,
    "atarijaguar": 28, "jaguar": 28, "atarijaguarcd": 29, "atarist": 4937, "atari800": 4943,
    "atari8bit": 4943, "wonderswan": 4925, "ws": 4925, "wonderswancolor": 4926, "wsc": 4926,
    "c64": 40, "commodore64": 40, "amiga": 4911, "amigacd32": 4947, "msx": 4929, "msx2": 4929,
    "zxspectrum": 4913, "spectrum": 4913, "amstradcpc": 4914, "cpc": 4914, "x68000": 4931,
    "dos": 1, "pc": 1, "scummvm": 1, "3do": 25, "colecovision": 31, "coleco": 31,
    "intellivision": 32, "vectrex": 4939, "odyssey2": 4927, "o2em": 4927,
    "arcade": 23, "mame": 23, "fbneo": 23, "fba": 23, "cps1": 23, "cps2": 23, "cps3": 23,
}


class ScrapeError(RuntimeError):
    pass


class CredentialsError(ScrapeError):
    """Auth / quota failure (bad creds, over quota, missing key)."""


class Candidate:
    """One search hit the user can choose from."""
    def __init__(self, source, ident, title, system="", raw=None):
        self.source = source
        self.ident = ident
        self.title = title
        self.system = system
        self.raw = raw

    def __repr__(self):
        return "<Candidate %s %s '%s'>" % (self.source, self.ident, self.title)


class ScrapeResult:
    def __init__(self):
        self.matched = False
        self.title = ""
        self.box = None
        self.fan = None
        self.error = ""

    @property
    def got_any(self):
        return bool(self.box or self.fan)


def region_order(region):
    region = (region or "wor").lower()
    if region == "world":
        region = "wor"
    base = ["wor", "us", "ss", "eu", "jp", "cus"]
    return [region] + [b for b in base if b != region]


def _key(romdir):
    return (romdir or "").lower().replace(" ", "")


def systemeid_for(romdir):
    return SYSTEMEID.get(_key(romdir))


def tgdb_platform_for(romdir):
    p = TGDB_PLATFORM.get(_key(romdir))
    return p if p and p > 0 else None


def crc32_hex(data):
    if not data:
        return ""
    return "%08x" % (zlib.crc32(data[:HASH_MAX_BYTES]) & 0xFFFFFFFF)


def _http_get(url, params=None, binary=False, timeout=30):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "gammaos-boxart"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def _sniff_image(data):
    if not data or len(data) < 16:
        return None
    if (data[:8].startswith(b"\x89PNG") or data[:3] == b"\xff\xd8\xff"
            or data[:6] in (b"GIF87a", b"GIF89a")
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP") or data[:2] == b"BM"):
        return data
    return None


class ScreenScraper:
    name = "screenscraper"
    label = "ScreenScraper"
    uses_crc = True

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
    def ready(self):
        return bool(self.devid and self.devpw)

    def unready_reason(self):
        return ("No ScreenScraper credentials. This build has no built-in developer "
                "account; add your own with an account username and password.")

    def _base_params(self):
        p = [("devid", self.devid), ("devpassword", self.devpw),
             ("softname", self.softname or DEFAULT_SOFTNAME), ("output", "json")]
        if self.ssid and self.sspassword:
            p += [("ssid", self.ssid), ("sspassword", self.sspassword)]
        return p

    def _request(self, url, params):
        try:
            body = _http_get(url, params, timeout=self.timeout).strip()
        except Exception as e:
            raise ScrapeError("ScreenScraper request failed: %s" % e)
        if not body or body[0] not in "{[":
            low = body.lower()
            if any(w in low for w in ("identifiants", "login", "erreur", "maximum",
                                      "quota", "closed")):
                raise CredentialsError("ScreenScraper: " + body[:160])
            return None
        try:
            return json.loads(body)
        except ValueError:
            raise ScrapeError("ScreenScraper returned invalid JSON")

    def _jeu_infos(self, romnom=None, systemeid=None, crc=None, size=None, gameid=None):
        if not self.ready:
            raise CredentialsError(self.unready_reason())
        p = self._base_params()
        if gameid:
            p.append(("gameid", str(gameid)))
        if romnom:
            p.append(("romnom", romnom))
        if systemeid:
            p.append(("systemeid", str(systemeid)))
        if crc:
            p.append(("crc", crc))
        if size:
            p.append(("romtaille", str(size)))
        root = self._request(SS_INFO_URL, p)
        jeu = (root or {}).get("response", {}).get("jeu") if root else None
        return jeu if isinstance(jeu, dict) else None

    def scrape(self, romnom, romdir, crc=None, size=None, want_box=True, want_fan=True):
        res = ScrapeResult()
        jeu = self._jeu_infos(romnom=romnom, systemeid=systemeid_for(romdir), crc=crc, size=size)
        if not jeu:
            res.error = "no match"
            return res
        return self._media_from_jeu(jeu, want_box, want_fan)

    def search(self, query, romdir=None, limit=8):
        if not self.ready:
            raise CredentialsError(self.unready_reason())
        p = self._base_params() + [("recherche", query)]
        sid = systemeid_for(romdir)
        if sid:
            p.append(("systemeid", str(sid)))
        root = self._request(SS_SEARCH_URL, p)
        jeux = (root or {}).get("response", {}).get("jeux") if root else None
        out = []
        if isinstance(jeux, list):
            for jeu in jeux[:limit]:
                if not isinstance(jeu, dict):
                    continue
                gid = jeu.get("id")
                sysname = (jeu.get("systeme") or {}).get("text", "") if isinstance(jeu.get("systeme"), dict) else ""
                out.append(Candidate("screenscraper", str(gid) if gid else "",
                                     self._pick_title(jeu.get("noms")) or query,
                                     sysname, raw=jeu))
        return out

    def fetch_media(self, cand, want_box=True, want_fan=True):
        jeu = cand.raw if isinstance(cand.raw, dict) else None
        if not jeu or not isinstance(jeu.get("medias"), list):
            jeu = self._jeu_infos(gameid=cand.ident) if cand.ident else None
        if not jeu:
            r = ScrapeResult()
            r.error = "no media"
            return r
        return self._media_from_jeu(jeu, want_box, want_fan)

    def _media_from_jeu(self, jeu, want_box, want_fan):
        res = ScrapeResult()
        res.matched = True
        res.title = self._pick_title(jeu.get("noms"))
        medias = jeu.get("medias")
        if not isinstance(medias, list):
            res.error = "no media"
            return res
        if want_box:
            u = self._pick_media(medias, ["box-2D", "box-3D"])
            if u:
                res.box = _sniff_image(self._dl(u))
        if want_fan:
            u = self._pick_media(medias, ["fanart", "ss", "sstitle"])
            if u:
                res.fan = _sniff_image(self._dl(u))
        return res

    def _dl(self, url):
        try:
            return _http_get(url, binary=True, timeout=max(self.timeout, 60))
        except Exception:
            return None

    def _pick_media(self, medias, types):
        for want in region_order(self.region):
            for ty in types:
                for m in medias:
                    if m.get("type") == ty and m.get("region") == want and m.get("url"):
                        return m["url"]
        for ty in types:
            for m in medias:
                if m.get("type") == ty and m.get("url"):
                    return m["url"]
        return None

    def _pick_title(self, noms):
        if not isinstance(noms, list) or not noms:
            return ""
        regs = ["us", "wor", "eu", "uk", "au", "ca"]
        if self.region in ("eu", "us", "wor"):
            regs = [self.region] + [r for r in regs if r != self.region]
        for want in regs + ["wor", "us", "jp"]:
            for nm in noms:
                if nm.get("region") == want and nm.get("text"):
                    return nm["text"]
        for nm in noms:
            if nm.get("text"):
                return nm["text"]
        return ""


class TheGamesDB:
    name = "thegamesdb"
    label = "TheGamesDB"
    uses_crc = False

    def __init__(self, apikey=None, region="wor", timeout=30):
        self.apikey = (apikey or "").strip()
        self.region = region
        self.timeout = timeout

    @property
    def ready(self):
        return bool(self.apikey)

    def unready_reason(self):
        return ("TheGamesDB needs your own API key. Create a free account at "
                "thegamesdb.net and paste your public API key.")

    def _byname(self, name, romdir, limit):
        if not self.ready:
            raise CredentialsError(self.unready_reason())
        p = [("apikey", self.apikey),
             ("fields", "players,publishers,developers,genres,overview,platform,rating,release_date"),
             ("name", name)]
        plat = tgdb_platform_for(romdir)
        if plat:
            p.append(("filter[platform]", str(plat)))
        try:
            body = _http_get(TGDB_BYNAME_URL, p, timeout=self.timeout)
        except Exception as e:
            raise ScrapeError("TheGamesDB request failed: %s" % e)
        try:
            root = json.loads(body)
        except ValueError:
            raise ScrapeError("TheGamesDB returned invalid response")
        code = root.get("code")
        if code in (401, 403):
            raise CredentialsError("TheGamesDB: invalid API key")
        games = (root.get("data") or {}).get("games") or []
        cands = []
        for g in games[:limit]:
            gid = g.get("id")
            if gid is None:
                continue
            cands.append(Candidate("thegamesdb", int(gid), g.get("game_title") or name,
                                   romdir or str(g.get("platform", "")), raw=g))
        return cands

    def search(self, query, romdir=None, limit=8):
        return self._byname(query, romdir, limit)

    def scrape(self, romnom, romdir, crc=None, size=None, want_box=True, want_fan=True):
        res = ScrapeResult()
        cands = self._byname(romnom, romdir, 12)
        if not cands:
            res.error = "no match"
            return res
        plat = tgdb_platform_for(romdir)
        chosen = None
        if plat:
            for c in cands:
                if str(c.system) == str(plat):
                    chosen = c
                    break
        chosen = chosen or cands[0]
        return self.fetch_media(chosen, want_box, want_fan)

    def fetch_media(self, cand, want_box=True, want_fan=True):
        res = ScrapeResult()
        res.matched = True
        res.title = cand.title
        try:
            body = _http_get(TGDB_IMAGES_URL,
                             [("apikey", self.apikey), ("games_id", str(cand.ident))],
                             timeout=self.timeout)
            root = json.loads(body)
        except Exception:
            res.error = "images request failed"
            return res
        data = root.get("data") or {}
        base = ""
        bu = data.get("base_url") or {}
        for k in ("original", "large", "medium"):
            if bu.get(k):
                base = bu[k]
                break
        images = data.get("images") or {}
        arr = images.get(str(cand.ident)) or (next(iter(images.values()), None) if images else None)
        if not base or not isinstance(arr, list):
            res.error = "no media"
            return res

        def find(ty, side=None):
            anyt = None
            for im in arr:
                if im.get("type") != ty or not im.get("filename"):
                    continue
                if side and im.get("side") == side:
                    return base + im["filename"]
                if anyt is None:
                    anyt = base + im["filename"]
            return anyt

        if want_box:
            u = find("boxart", "front")
            if u:
                res.box = _sniff_image(self._dl(u))
        if want_fan:
            u = find("fanart")
            if u:
                res.fan = _sniff_image(self._dl(u))
        return res

    def _dl(self, url):
        try:
            return _http_get(url, binary=True, timeout=max(self.timeout, 60))
        except Exception:
            return None


def make_scraper(source="screenscraper", region="wor", ss_user=None, ss_pass=None,
                 tgdb_key=None, timeout=30):
    """Build the chosen scraper. Raises CredentialsError if it is not usable."""
    source = (source or "screenscraper").lower()
    if source in ("thegamesdb", "tgdb"):
        sc = TheGamesDB(apikey=tgdb_key, region=region, timeout=timeout)
    else:
        sc = ScreenScraper(ssid=ss_user or None, sspassword=ss_pass or None,
                           region=region, timeout=timeout)
    return sc
