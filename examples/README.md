# Example output

Reports committed here so you can read real output without running anything.

| File | Challenge | Regenerate with |
|---|---|---|
| [`01_review.md`](01_review.md) | 1 — Smart Code Reviewer | `python review.py review samples --mock --gate` |
| [`02_pair.md`](02_pair.md) | 2 — The AI Pair Engineer | `python review.py pair samples/eta_service.go --mock` |
| [`03_snippet.md`](03_snippet.md) | 3 — Code Review Assistant (3+1) | `python review.py snippet samples/snippet.go --mock` |

All three regenerate at once with `python review.py demo --out-dir examples --mock`.

## These are offline (`--mock`) reports

Every report here was produced by the **deterministic static pass alone** — no model was
called, which is why each one carries the `offline mock mode` banner. That is deliberate:
these are reproducible byte-for-byte on any machine with Python and no API key.

Live mode (`--mock` dropped, `LLM_API_KEY` set) keeps the same structure but adds
the findings that need reading comprehension rather than measurement. The sample files
contain three of those on purpose, and none of them appear in the reports here:

- `samples/routing.go` — the package-level `cache` map is written from request handlers
  with no mutex. A data race no regex finds.
- `samples/eta_service.go` — `haversine` does not compute a haversine distance; it
  returns a flat squared-Euclidean approximation. The name lies, and in a routing system
  that is a correctness bug.
- `samples/eta_service.go` — `ComputeBatch` swallows every per-order error with
  `continue`, so a caller cannot distinguish a filtered order from a failed one.

Reading these files alongside a live run is the clearest way to see where the model earns
its cost and where the static pass already suffices.
