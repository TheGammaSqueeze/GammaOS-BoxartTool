#!/usr/bin/env python3
"""Generate the obfuscated built-in ScreenScraper credentials module.

Reads a gitignored ``devcreds.local.txt`` (raw secret) and writes a gitignored
``gammaos_boxart/_devcreds_gen.py`` holding only XOR-obfuscated bytes. Neither file
is committed; official release binaries bake the generated module in via a CI secret.

devcreds.local.txt format (key=value lines, '#' comments allowed):

    devid=YourScreenScraperDevId
    devpassword=YourScreenScraperDevPassword
    softname=gammaos-nano

Run from the repo root:  python3 gen_devcreds.py
To ship WITHOUT built-in creds, just delete gammaos_boxart/_devcreds_gen.py.
"""

import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, "devcreds.local.txt")
OUT = os.path.join(HERE, "gammaos_boxart", "_devcreds_gen.py")


def _xor(data, key):
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def main():
    if not os.path.isfile(LOCAL):
        sys.exit("no devcreds.local.txt next to this script (see the header for the format)")
    vals = {}
    with open(LOCAL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    devid = vals.get("devid", "")
    devpw = vals.get("devpassword", "")
    soft = vals.get("softname", "gammaos-nano")
    if not devid or not devpw:
        sys.exit("devcreds.local.txt must set both devid and devpassword")

    key = os.urandom(32)

    def enc(s):
        return base64.b64encode(_xor(s.encode("utf-8"), key)).decode("ascii")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# GENERATED FILE - DO NOT COMMIT. Obfuscated ScreenScraper developer creds.\n")
        f.write("# Regenerate with: python3 gen_devcreds.py\n")
        f.write("K = %r\n" % base64.b64encode(key).decode("ascii"))
        f.write("D = %r\n" % enc(devid))
        f.write("P = %r\n" % enc(devpw))
        f.write("S = %r\n" % enc(soft))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
