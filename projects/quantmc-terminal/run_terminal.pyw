"""
Double-clickable launcher (no console window).

Equivalent to ``python -m quantmc``.  The .pyw extension makes Windows use
pythonw.exe, so no terminal appears behind the app.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quantmc.__main__ import main

if __name__ == "__main__":
    sys.exit(main([]))
