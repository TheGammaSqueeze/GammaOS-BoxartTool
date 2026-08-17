#!/usr/bin/env python3
"""Convenience launcher so you can run the tool without installing it.

  python3 gammaos-boxart.py list
  python3 gammaos-boxart.py --gui        # or:  gui
"""
import sys
from gammaos_boxart.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
