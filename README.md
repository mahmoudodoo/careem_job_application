# Careem AI Code Review Toolkit

**Careem "Optional AI Challenge" submission** — all three challenges, built as one tool.

Repository: <https://github.com/mahmoudodoo/careem_job_application>
Full manual: **[DOCUMENTATION.md](DOCUMENTATION.md)** · Design notes: **[ARCHITECTURE.md](ARCHITECTURE.md)** · 100-word summary: **[SUBMISSION.md](SUBMISSION.md)**

---

## The idea in one paragraph

Ask an LLM to "review this code" and it will confidently cite line 47 of a 30-line file.
So this tool **measures first and reasons second**. A deterministic static pass parses the
source, computes function spans, cyclomatic complexity, nesting depth and duplication,
and detects a set of concrete defects. Those measurements are handed to the model as
*grounding facts*, and the model is told to treat them as truth and spend its own effort
on the part it is actually good at: what the consequence is, what the root cause is, and
what to change. Every finding in the output cites a line number that exists.

## The three challenges

| # | Challenge | Command | Output |
|---|---|---|---|
| 1 | **Smart Code Reviewer** | `review` | Verdict, four scores, ranked findings, a CI gate that exits non-zero |
| 2 | **The AI Pair Engineer** | `pair` | Design flaws, runnable proposed tests, refactors as unified diffs |
| 3 | **Code Review Assistant** | `snippet` | Exactly three improvements plus one positive note |

Challenge 3's deliverable is a *prompt*, so all three system prompts live as readable
Markdown in [`prompts/`](prompts/) rather than buried in Python — including a
[copy-paste version for any chat model](prompts/03_snippet_review_3plus1.md#appendix-a--portable-single-message-version).

## Run it in 30 seconds

No API key. No `pip install`. No network. Python 3.10+ only.

```bash
git clone https://github.com/mahmoudodoo/careem_job_application.git
cd careem_job_application

python review.py demo --mock     # runs all three challenges -> out/
python review.py serve --mock    # web UI at http://127.0.0.1:8000
```

For live model-backed reviews:

```bash
pip install -r requirements.txt
export LLM_API_KEY="..."      # PowerShell: $env:LLM_API_KEY="..."
python review.py review samples --gate
```

Windows-specific instructions are in **[DOCUMENTATION.md](DOCUMENTATION.md)**.

## Read the output without running anything

Committed example reports are in **[`examples/`](examples/)** —
[review](examples/01_review.md) · [pair](examples/02_pair.md) · [snippet 3+1](examples/03_snippet.md).
[`examples/README.md`](examples/README.md) explains which findings only appear in live
mode, and why.

## Screenshots

> Drop the images into `docs/screenshots/` using exactly these filenames and they will
> appear here. [DOCUMENTATION.md](DOCUMENTATION.md#appendix-a--screenshots) lists the
> command to run for each one.

| Web UI — Smart Code Reviewer | Web UI — Snippet 3+1 |
|---|---|
| ![Review tab](docs/screenshots/01-web-ui-review.png) | ![Snippet tab](docs/screenshots/03-web-ui-snippet.png) |

| CLI — static pass | CLI — CI gate failing |
|---|---|
| ![scan](docs/screenshots/04-cli-scan.png) | ![gate](docs/screenshots/06-cli-gate-fail.png) |

## What it looks like

`python review.py scan samples` — the deterministic layer, no model involved:

```
samples/eta_service.go  [go]
  loc=126 functions=4 longest=61 avg=26.0
    fn GetTrafficFactor    L33-46  len=14  params=3 cx=2   nest=1
    fn ComputeETA          L48-108 len=61  params=2 cx=18  nest=5
  [blocker] L44   ignored_error     Return value discarded with `_` - a failure here is silent.
  [major  ] L33   missing_context   `GetTrafficFactor` looks like an I/O call but takes no context.Context...
  [major  ] L48   high_complexity   `ComputeETA` has cyclomatic complexity 18 (limit 12); that is 18 paths to cover.
```

`python review.py snippet samples/snippet.go --mock` — the 3+1 contract:

```
### 1. Loop reads one element past the end
Loop bound uses `<= len(...)`, so the final iteration indexes one past the end and panics.

**Before**            **After**
for i := 0; i <= len(etas); i++ {     ->     for i := 0; i < len(etas); i++ {
```

## Design decisions worth defending

- **Zero required dependencies.** The whole toolkit — CLI, static analysis, web UI,
  tests — is the Python standard library. the API client is an optional extra, imported
  lazily. That is why `--mock` can be the default path in CI and in this README.
- **`--mock` is a real mode, not a stub.** It runs the full pipeline and returns the
  static findings, clearly labelled. It makes the tool demoable offline and the test
  suite hermetic — 51 tests, no network, no cost, same result everywhere.
- **Structured outputs, not prompt-and-pray.** Every model call pins a JSON schema via
  `output_config.format`, so the CLI never regexes JSON out of prose. A test asserts the
  schemas stay within the API's supported subset.
- **The system prompt is byte-stable and cached.** Per-request content goes in the user
  turn, behind the `cache_control` breakpoint, so reviewing ten files pays for the rubric
  once.
- **Findings are capped per rule.** Twelve identical `magic_number` notes bury the one
  blocker, so repeats past the fifth collapse into a single summary line.
- **A rule that cries wolf is worse than no rule.** `i <= len(xs)` is flagged as a
  blocker; `i <= len(xs)-1` is not. There is a test for the second case.

## Repository layout

```
prompts/          the three system prompts, as readable Markdown
samples/          deliberately flawed Go fixtures (ETA + routing domain)
src/              the package - see ARCHITECTURE.md for a file-by-file map
tests/            51 hermetic unittest cases
docs/screenshots/ put screenshots here
.github/workflows/ai-code-review.yml   the reviewer gating its own pull requests
```

## Tests

```bash
python -m unittest discover -s tests -t .
```

---

Built by **Mahmoud Al-Qudah** for the Careem Marketplace ETA & Routing team application.
Licensed MIT. All sample code is fictional and deliberately flawed; no Careem code,
data or internal information is used anywhere in this repository.
