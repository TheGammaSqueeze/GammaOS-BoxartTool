"""Entry point.

  gammaos-boxart               -> launches the GUI (friendly for a double-click)
  gammaos-boxart --gui | gui   -> launches the GUI
  gammaos-boxart <command> ... -> runs the CLI (list, set, export, ...)
  gammaos-boxart --help        -> CLI help
"""

import sys


def main():
    args = sys.argv[1:]
    gui = (not args) or args[0] in ("--gui", "gui")
    if gui:
        from .gui import main as gui_main
        return gui_main()
    from .cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    main()
