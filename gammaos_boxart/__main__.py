"""Entry point: `python -m gammaos_boxart` runs the CLI; `--gui` launches the GUI."""

import sys


def main():
    if "--gui" in sys.argv[1:] or "gui" in sys.argv[1:2]:
        from .gui import main as gui_main
        gui_main()
    else:
        from .cli import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()
