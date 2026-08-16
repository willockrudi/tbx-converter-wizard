"""PyInstaller entry point - a plain script (not `-m` package invocation,
which PyInstaller's Analysis doesn't take directly) that just calls the
real app. Not meant to be run directly outside of a packaged build; use
./run_gui.sh or `python3 -m tbx_converter_wizard.gui` for that.
"""
from tbx_converter_wizard.gui import main

if __name__ == "__main__":
    main()
