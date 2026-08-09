# Architecture and design notes

Design rationale for the Careem AI Code Review Toolkit — why it is built the way it is,
what the constraints are, and which decisions are load-bearing.

For usage, see [DOCUMENTATION.md](DOCUMENTATION.md). For the submission summary, see
[SUBMISSION.md](SUBMISSION.md).

---

## The problem being solved

A code-review assistant is only useful if a reviewer can trust it. The failure mode that
destroys trust fastest is not a missed bug — it is a confident, well-written finding that
cites a line number that does not exist, or quotes a complexity metric it estimated
rather than computed. One hallucinated citation and the reviewer starts checking
everything by hand, at which point the tool is worse than useless because it also costs
time.

So the central design decision is: **measure first, reason second.**

`analyzers.py` runs a deterministic static pass that computes everything countable —
function spans, cyclomatic complexity, nesting depth, parameter counts, duplicated
blocks — and detects the mechanical defects a parser can be certain about: ignored
errors, off-by-one loop bounds, division by a length with no empty guard, blocking
sleeps, panics in library code.

Those measurements are injected into the model prompt as a `GROUNDING FACTS` block, and
the prompt instructs the model to treat them as measured truth. The model is then free to
do the part it is genuinely better at than a linter: explain what will actually go wrong,
collapse three symptoms into one root cause, and write the fix.

Two invariants follow, and both are enforced by tests:

- Every finding cites a line number that exists in the input.
- Offline mode is **opt-in**. `--mock` makes the whole tool usable with no API key, but a
  live run that cannot find one fails loudly rather than quietly returning offline
  results. A report that silently means something other than it says is the same
  trust failure as a hallucinated line number, so `TestMockIsOptIn` guards it.

## Why the three challenges are one tool

The Careem challenge offered three options. They are three views of the same pipeline —
parse, measure, ground, reason, render — differing only in the prompt, the output schema,
and the renderer. Building them as three separate scripts would have meant three copies
of the static pass. The shared spine is `pipeline.py`; the differences live in
`prompts/`, `schemas.py` and `reporters.py`.

| Challenge | Command | Output shape |
|---|---|---|
| 1. Smart Code Reviewer | `review` | Verdict, four scores, ranked findings, CI gate |
| 2. The AI Pair Engineer | `pair` | Design flaws, runnable tests, refactor diffs |
| 3. Code Review Assistant | `snippet` | Exactly three improvements + one positive note |

## Layout

```
prompts/                      the three system prompts, as readable Markdown
                              (Challenge 3's deliverable IS a prompt, so it lives here
                              rather than as a string literal in Python)
samples/                      deliberately flawed Go fixtures, ETA/routing domain

src/careem_ai_reviewer/
  analyzers.py                deterministic static pass - parsing, metrics, 15 rules
  schemas.py                  JSON schemas for structured model output
  prompts.py                  prompt loading + user-turn assembly
  llm.py                      the single model call site; caching, refusal handling
  mock.py                     offline provider derived from the static pass
  pipeline.py                 orchestration for the three modes
  reporters.py                Markdown / JSON rendering + the CI gate decision
  server.py                   stdlib-only local web UI
  cli.py                      argparse entry point

tests/                        51 hermetic unittest cases, no network
.github/workflows/            the reviewer gating its own pull requests
```

## Load-bearing decisions

**Zero required runtime dependencies.** The standard library is the budget — CLI, static
analysis, web UI and tests all run on a bare Python install. The API SDK is an optional
extra, imported lazily inside `llm.py`. This is what lets `--mock` be the default path in
CI and in the README, and it means the tool runs anywhere Python does. Adding a hard
dependency changes what this project is.

**`--mock` is a real mode, not a stub.** It runs the full pipeline and returns the static
findings, labelled as such in every report. Three things fall out of it: the tool demos
offline with no key, the test suite is hermetic and free, and pull requests from forks
(which cannot read secrets) still get a gate rather than a skipped check.

**Structured outputs, not prompt-and-pray.** Every model call pins a JSON schema, so the
response is valid JSON by construction and the CLI never salvages JSON out of prose. The
API's schema subset is strict — every object needs `additionalProperties: false` and a
`required` list naming every property, and length constraints are unsupported — so
`TestSchemaHygiene` asserts the schemas stay inside it rather than discovering it at
runtime. The "exactly three improvements" contract is therefore enforced twice: in the
prompt, and again in `pipeline.py` after the response arrives.

**System prompts are byte-stable and cached.** They sit behind a `cache_control`
breakpoint; everything per-request goes in the user turn after it. Reviewing ten files in
one run pays for the rubric once. Interpolating anything per-request into a system prompt
silently destroys this, which is why the prompts are loaded from disk unmodified.

**ASCII-only output.** Reports land in PR comments, CI logs and Windows `cp1252`
consoles, where a stray box-drawing character is a crash rather than a cosmetic problem.
`test_markdown_renders` asserts it. For the same reason every file operation passes
`encoding="utf-8"` explicitly — Python on Windows otherwise defaults to the locale
codepage.

**Findings are capped per rule.** Twelve identical `magic_number` notes bury the one
blocker, so repeats past the fifth collapse into a single summary line. Real linters do
this too, and for the same reason: a review nobody reads to the bottom of is a review
that missed the thing at the bottom.

**A rule that cries wolf is worse than no rule.** `i <= len(xs)` is flagged as a blocker;
`i <= len(xs)-1` is correct code and is not. Every heuristic has a negative test proving
it stays quiet on valid input — see `test_correct_loop_bound_is_not_flagged`.

**The vendor surface is one adapter.** Nothing outside `llm.py` imports an SDK or knows
which backend is in use. The pipeline calls `complete()` with a system prompt, a user
turn and a schema, and receives a validated dict. The adapter is chosen by `--provider`
against a registry, the model by `--model` or `LLM_MODEL`, and the credential by
`LLM_API_KEY`. Swapping backends is one function plus one registry entry — which also
means the reviewer, the pair engineer and the snippet reviewer are not coupled to any
vendor's request shape.

## Model API specifics

- Structured outputs via `output_config.format`; effort via `output_config.effort`,
  exposed as `--effort` and defaulting to `medium`.
- Extended thinking is on by default on the target model and counts against
  `max_tokens`, which is why `max_tokens` defaults to 16000 rather than something tight.
- `stop_reason` is checked before `content` is read: a safety refusal arrives as an
  HTTP 200, not an exception, so code that indexes `content[0]` unconditionally breaks.
- Server-side refusal fallbacks are opted into by default and degrade gracefully on older
  SDK versions (`llm.py::_is_unsupported_parameter_error`).
- `max_tokens` exhaustion and empty responses produce actionable errors naming the flag
  to change, rather than a stack trace.

## Deliberately not done

## A bug worth keeping in the record

`argparse.set_defaults()` mutates `action.default` in place. Because every subparser
shared one `--mock` Action via `parents=[common]`, setting `mock=True` on the `scan`
subcommand silently turned mock mode on for `review`, `pair` and `snippet` too: live
runs returned offline reports and said nothing. Every test passed, because the pipeline
tests build `Settings` directly and never go through the parser.

It is fixed (`cmd_scan` sets the flag locally) and `tests/test_cli.py` now asserts that
`--mock` defaults to off for every subcommand. Recording it here because the lesson
generalises: the tests covered the layer that was easy to test, not the seam where the
layers meet, and the failure mode was silence rather than a crash.

## Deliberately not done

- **No Go toolchain requirement.** The samples are Go because that is the target team's
  stack, but the tool analyses source as text and calls an API; it never compiles
  anything. Requiring Go would have made the submission unrunnable for most reviewers.
- **No vendored linter** (`golangci-lint`, `ruff`). The static pass is small on purpose
  so the grounding idea is legible in one readable file rather than hidden behind a
  subprocess call.
- **No web framework.** `http.server` plus one HTML page keeps the install at zero. Flask
  or Streamlit would have added a dependency to save perhaps forty lines.
- **No dependency-injection container or plugin loader.** The provider registry in
  `llm.py` is a dict of functions. Adding a backend means writing one function and adding
  one line; anything more ceremonious would be machinery in place of code.

## Known limits

- Function extraction is precise for Go and Python, brace-based and approximate for other
  C-like languages, and absent for the rest — those still get all file-level rules.
- The duplication detector matches identical consecutive lines; it will not catch
  structurally duplicated code with different identifiers.
- Cyclomatic complexity is a keyword-count approximation, not a control-flow graph.
- `--mock` cannot find anything requiring comprehension rather than measurement. That is
  the point, and `examples/README.md` names three defects in the samples that only live
  mode reports.
