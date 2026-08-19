"""Built-in (obfuscated) ScreenScraper developer credentials loader.

The real developer credentials are NEVER committed to this public repo. The
generator gen_devcreds.py turns a gitignored devcreds.local.txt into a gitignored
_devcreds_gen.py that holds only XOR-obfuscated bytes (so the raw values are not
readable via `strings`). Official release binaries bake that generated module in
at build time (via a CI secret); a plain from-source checkout has neither the raw
nor the generated file, so builtin_credentials() returns None and the user must
supply their own ScreenScraper account. A user-supplied account always overrides
the built-in developer credentials anyway.

This is obfuscation, not unbreakable secrecy: any client-side credential can be
recovered by a determined reverser. The softname is ours (rotatable) and users can
add their own account for quota, matching how gammaos-nano itself bakes the creds.
"""

import base64


def _xor(data, key):
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def builtin_credentials():
    """Return (devid, devpassword, softname) if baked in, else None."""
    try:
        from . import _devcreds_gen as g   # gitignored / injected at release time
    except Exception:
        return None
    try:
        key = base64.b64decode(g.K)
        devid = _xor(base64.b64decode(g.D), key).decode("utf-8")
        devpw = _xor(base64.b64decode(g.P), key).decode("utf-8")
        soft = _xor(base64.b64decode(g.S), key).decode("utf-8") or "gammaos-nano"
    except Exception:
        return None
    if devid and devpw:
        return (devid, devpw, soft)
    return None
