"""Careem AI Challenge - AI Code Review Toolkit.

Three challenge deliverables behind one CLI:

  1. `review`  - Smart Code Reviewer (pre-human-review quality gate)
  2. `pair`    - The AI Pair Engineer (design flaws, tests, refactors)
  3. `snippet` - Code Review Assistant (3 improvements + 1 positive note)

The toolkit runs fully offline in `--mock` mode (zero dependencies) and
against a live model when an API key is set.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
