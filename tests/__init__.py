"""Test package bootstrap: put `src/` on the import path.

Keeps `python -m unittest discover -s tests -t .` working straight from a clone,
with no install step and no third-party test runner.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
