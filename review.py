#!/usr/bin/env python3
"""Zero-install launcher.

Lets you run the toolkit straight from a clone, with no `pip install` step:

    python review.py demo --mock
    python review.py review samples --mock
    python review.py serve --mock

Everything it does is put `src/` on the import path and hand over to the CLI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from careem_ai_reviewer.cli import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    raise SystemExit(main())
