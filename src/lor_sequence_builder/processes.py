"""Starting helper programs (FFmpeg) without flashing a window.

On Windows a console program started from the windowed app opens its own black
console window for a moment. Their output is always captured, so the window shows
nothing; this flag stops it from appearing at all. Elsewhere it is 0, the default.
"""

from __future__ import annotations

import subprocess
import sys

NO_WINDOW = 0
if sys.platform == "win32":
    NO_WINDOW = subprocess.CREATE_NO_WINDOW
