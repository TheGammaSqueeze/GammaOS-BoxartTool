"""PyInstaller entry point for the GammaOS Boxart Tool (bundles CLI + GUI)."""
import sys
from gammaos_boxart.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
