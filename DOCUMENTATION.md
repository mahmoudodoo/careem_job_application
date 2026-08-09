# Careem AI Code Review Toolkit — Full Documentation

**Repository:** <https://github.com/mahmoudodoo/careem_job_application>
**Submission for:** Careem *Optional AI Challenge* — Senior Software Engineer I, Backend
(Marketplace ETA & Routing)
**Author:** Mahmoud Al-Qudah

This document covers everything: what the tool is, how to run every part of it on a
Windows machine, what each command produces, and how to run it against a live model
API.

---

## Table of contents

1. [What this is](#1-what-this-is)
2. [How it works](#2-how-it-works)
3. [Prerequisites](#3-prerequisites)
4. [Quick start — 60 seconds, offline](#4-quick-start--60-seconds-offline)
5. [Command reference](#5-command-reference)
6. [The web UI](#6-the-web-ui)
7. [Live mode — running against a model](#7-live-mode--running-against-a-model)
8. [Using it as a CI gate](#8-using-it-as-a-ci-gate)
9. [Reviewing your own code](#9-reviewing-your-own-code)
10. [Tests](#10-tests)
11. [Configuration reference](#11-configuration-reference)
12. [Architecture](#12-architecture)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What this is

The challenge offered three options. This repository implements **all three**, as one
tool, because they are three views of the same pipeline rather than three products:

| # | Challenge as stated | Implemented as | Command |
|---|---|---|---|
| 1 | *"Create an AI assistant that reviews code for readability, structure, and maintainability before human review."* | A pre-human-review gate: verdict, four scores, ranked findings with fixes, and a non-zero exit code when policy is breached. | `review` |
| 2 | *"Design an AI that codes alongside developers — detecting design flaws, proposing tests, and refactoring."* | A pair-programming navigator: design flaws with consequences, runnable test code, refactors as unified diffs, and open questions instead of silent assumptions. | `pair` |
| 3 | *"Write a prompt that reviews short code snippets and recommends three improvements plus one positive note."* | A prompt (the deliverable is literally the prompt file) plus the tool that runs it under a schema that enforces the 3+1 shape. | `snippet` |

The domain is deliberately Careem's: the sample code is Go, and it computes delivery
ETAs and multi-stop routes across Food, Groceries, Taxi and Hala.

---

## 2. How it works

```
                  ┌──────────────────────────┐
   source file →  │  Deterministic static    │  measures: function spans, cyclomatic
                  │  pass (analyzers.py)     │  complexity, nesting, params, clones
                  └───────────┬──────────────┘  detects: ignored errors, off-by-one,
                              │                          divide-by-zero, panics, sleeps
                              ▼
                  ┌──────────────────────────┐
                  │  GROUNDING FACTS block   │  real line numbers, real metrics
                  └───────────┬──────────────┘
                              ▼
     stable system prompt  →  ┌──────────────────────┐
     (cached, from prompts/)  │   the model, under   │  judgement: consequence,
     + user turn (the code)   │  a strict JSON schema│  root cause, the fix
                              └───────────┬──────────┘
                                          ▼
                  ┌──────────────────────────────────────┐
                  │  Markdown report · JSON · CI verdict  │
                  └──────────────────────────────────────┘
```

**Why the static pass exists.** An LLM asked to review code will estimate metrics and
invent line numbers. Everything countable is therefore computed in Python and handed to
the model as measured truth, and the model is told so explicitly. The model's job is the
part it is genuinely better at than a linter: explaining what will actually go wrong,
merging three symptoms into one root cause, and writing the fix.

**Why `--mock` exists.** With `--mock`, the pipeline runs end to end using only the
static pass — clearly labelled as such in every report. This means the tool demonstrates
itself with no API key, the test suite is hermetic and free, and CI has a gate even on
pull requests from forks that cannot see secrets.

---

## 3. Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.10+** | Confirmed on 3.13. `python --version` |
| **Git** | Only for cloning and for `--changed-since`. |
| Model API key | **Optional.** Live mode only. Everything in sections 4–6 runs without it. |

There is nothing to install for offline use — no `pip install`, no virtualenv, no Go
toolchain. The samples are Go, but the tool reads them as text; it never compiles them.

---

## 4. Quick start — 60 seconds, offline

Open **PowerShell** and run:

```powershell
cd "e:\Careem Software Engineer Job Opportunity\careem_job_application"

# 1. Everything at once: all three challenges, reports written to out\
python review.py demo --mock

# 2. The deterministic layer on its own - no model involved
python review.py scan samples

# 3. The web UI
python review.py serve --mock
```

Then open <http://127.0.0.1:8000> and press **Run**. `Ctrl+C` stops the server.

`python review.py demo --mock` prints:

```
[1/3] review   -> eta_service.go, routing.go
[2/3] pair     -> eta_service.go
[3/3] snippet  -> snippet.go

Done. Reports written to out/
  gate: FAIL (1 blocker, 6 major)
```

and writes three Markdown reports:

| File | Challenge |
|---|---|
| `out\01_review.md` | 1 — Smart Code Reviewer |
| `out\02_pair.md` | 2 — The AI Pair Engineer |
| `out\03_snippet.md` | 3 — Code Review Assistant (3+1) |

The same three reports are committed under [`examples/`](examples/) so anyone browsing
the repository on GitHub can read real output without running anything. `out/` is
gitignored; `examples/` is not.

Open them in VS Code and press `Ctrl+Shift+V` for the rendered preview.

> **If you cloned somewhere else**, replace the `cd` path. If `python` is not found, try
> `py -3` in place of `python` in every command below.

---

## 5. Command reference

Every command works as `python review.py <command>` from a clone. If you run
`pip install -e .`, the same commands are available as `careem-ai-reviewer <command>`.

### Global options

| Flag | Default | Meaning |
|---|---|---|
| `--mock` | off | Run offline with the deterministic pass only. No API key needed. |
| `--model` | from `LLM_MODEL` | Model ID passed to the backend. |
| `--provider` | `messages-api` | Backend adapter (see the registry in `llm.py`). |
| `--effort` | `medium` | `low` / `medium` / `high` / `xhigh` / `max`. The cost-vs-depth dial. |
| `--max-tokens` | `16000` | Output budget. On reasoning models, thinking counts against it. |
| `--format` | `md` | `md` or `json`. |
| `--out FILE` | stdout | Write the report to a file instead. |

### `review` — Challenge 1

```powershell
python review.py review samples --mock
python review.py review samples --mock --gate                 # exit 1 on policy breach
python review.py review src\ --context "Adding batch ETA support" --out review.md
python review.py review --changed-since origin/main --gate    # only what the PR changed
python review.py review samples --mock --format json --out review.json
```

Produces a verdict (`APPROVE` / `COMMENT` / `REQUEST CHANGES`), four scores out of five,
findings ranked by severity with a fix for each, what the author got right, and a short
list of questions only a human can answer.

**Exit codes:** `0` clean · `1` gate failed (only with `--gate`) · `2` execution error.

### `pair` — Challenge 2

```powershell
python review.py pair samples\eta_service.go --mock
python review.py pair src\service.go --task "Add a timeout to the traffic call" --out pair.md
```

Produces three sections: design flaws (what, where, why it matters here, smallest fix),
proposed tests (real code, plus one line on the bug each would catch), and refactors
(unified diffs with an honest risk rating) — followed by what to keep doing and the
questions it had to guess at.

### `snippet` — Challenge 3

```powershell
python review.py snippet samples\snippet.go --mock
python review.py snippet --code "def f(x): return x/len(x)" --filename f.py --mock
Get-Content myfile.go | python review.py snippet --mock          # from a pipe
```

Always exactly three improvements and one positive note. The shape is enforced twice:
in the prompt, and again in `pipeline.py` after the response arrives.

### `scan` — the static pass alone

```powershell
python review.py scan samples
python review.py scan src\
```

No model, no key, no network — the grounding layer made visible. Useful for showing what
is measured rather than inferred.

### `serve` — the web UI

```powershell
python review.py serve --mock
python review.py serve --port 9000 --host 0.0.0.0
```

### `demo` — all three at once

```powershell
python review.py demo --mock
python review.py demo --out-dir reports        # live mode, needs a key
```

---

## 6. The web UI

`python review.py serve --mock` → <http://127.0.0.1:8000>

- **Left panel:** the three challenge modes as tabs, a sample loader, the code box, a
  filename field (drives language detection), the effort dial, and the offline toggle.
- **Right panel:** three views of the same result — a rendered **Report**, the raw
  **Markdown** (copy straight into a PR comment), and the **JSON** the model returned
  under schema.

The whole UI is `http.server` plus one HTML page. No Flask, no Streamlit, no npm.

> Untick **Offline mock mode** to send the request to the model — the server must have been
> started in a shell where `LLM_API_KEY` is set.

---

## 7. Live mode — running against a model

### One-time setup

```powershell
pip install -r requirements.txt
```

Set the key for the current PowerShell session:

```powershell
$env:LLM_API_KEY = "..."
```

Or persist it for future sessions:

```powershell
setx LLM_API_KEY "..."
```

(`setx` only affects **new** terminals — close and reopen PowerShell afterwards.)

Verify:

```powershell
python -c "import os; print('key set:', bool(os.environ.get('LLM_API_KEY')))"
```

### Run it

```powershell
python review.py review samples
python review.py pair samples\eta_service.go --effort high
python review.py snippet samples\snippet.go
python review.py serve                      # then untick 'Offline mock mode'
```

Drop `--mock` and that is the only change.

### What live mode adds over `--mock`

The static pass finds symptoms. The model finds the things that need reading
comprehension — and the sample files were written to contain both kinds:

- `cache` in `samples/routing.go` is a package-level `map` written from request handlers
  with no mutex. That is a data race in production and no regex will find it.
- `haversine` in `samples/eta_service.go` is not a haversine — it is a flat Euclidean
  approximation with a misleading name, which is a correctness bug in a routing system.
- `ComputeBatch` swallows every per-order error with `continue`, so a caller cannot tell
  a filtered order from a failed one.

`--mock` reports none of these three. That contrast is the point of the design: the
static pass buys precision, the model buys comprehension.

### Cost and tuning

Requests are small. `--effort low` is the cheapest useful setting, `medium` is the
default, `high`/`xhigh` are worth it for the `pair` command on real code. The system
prompt is cached, so a multi-file run pays for the rubric once.

---

## 8. Using it as a CI gate

[`.github/workflows/ai-code-review.yml`](.github/workflows/ai-code-review.yml) runs two
jobs on every pull request:

1. **tests** — the unit suite plus a `demo --mock` smoke test. No secrets, always runs.
2. **review** — reviews only the files the PR changed, posts the Markdown report as a PR
   comment, uploads it as an artifact, and fails the build if the gate rejects it.

If `LLM_API_KEY` is not configured as a repository secret, the review job falls
back to `--mock` automatically, so forked PRs still get a gate instead of a skipped
check.

To enable live reviews: **Settings → Secrets and variables → Actions → New repository
secret**, named `LLM_API_KEY`.

The policy lives in `GatePolicy` in [`src/careem_ai_reviewer/config.py`](src/careem_ai_reviewer/config.py):

```python
fail_on_blocker: bool = True   # any blocker fails the build
max_major: int = 3
max_total: int = 25
```

---

## 9. Reviewing your own code

Point it at any file or directory. Language support comes in three tiers:

| Tier | Languages | What you get |
|---|---|---|
| Precise | Go, Python | Exact function spans, per-function metrics, and the language-specific rules |
| Brace-based | Java, Kotlin, C#, JavaScript, TypeScript, Rust, C, C++, PHP | Approximate function spans plus per-function metrics and all file-level rules |
| File-level only | Ruby, anything else with a supported extension | Line-length, TODOs, magic numbers, off-by-one, duplication, blocking sleeps |

In live mode the model reads the source regardless of tier — the tiers describe how much
*measured* grounding it gets, not what it can review.

```powershell
python review.py review C:\path\to\your\project\src --mock
python review.py review C:\path\to\file.py --mock --gate
python review.py pair C:\path\to\service.go --task "what you are building"
```

Directory walks skip `.git`, `node_modules`, `vendor`, `venv`, `__pycache__`, `dist`,
`build` and `target`, and ignore files over 400 KB.

---

## 10. Tests

```powershell
python -m unittest discover -s tests -t .
python -m unittest discover -s tests -t . -v      # per-test output
```

51 tests, no network, no API key, no third-party runner. They cover the Go and Python
parsers, every static rule (including negative cases proving the rules stay quiet on
correct code), the finding cap, the CI gate policy, all three pipelines end to end, the
renderers, and a meta-test asserting the JSON schemas stay inside the subset the
model API accepts.

---

## 11. Configuration reference

All thresholds live in [`src/careem_ai_reviewer/config.py`](src/careem_ai_reviewer/config.py).

| Setting | Default | What it controls |
|---|---|---|
| `max_function_lines` | 60 | `long_function` |
| `max_nesting_depth` | 4 | `deep_nesting` |
| `max_line_length` | 120 | `long_line` |
| `max_params` | 5 | `too_many_params` |
| `max_cyclomatic` | 12 | `high_complexity` |
| `duplicate_window` | 5 | Identical consecutive lines that count as a clone |
| `MAX_FINDINGS_PER_RULE` | 5 | Repeats past this collapse into one summary line (`analyzers.py`) |

Environment variables:

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | Live mode. Absent + no `--mock` = a clear error, never a silent downgrade. |
| `LLM_MODEL` | Default model ID, overridable per run with `--model`. |
| `LLM_PROVIDER` | Default backend adapter, overridable per run with `--provider`. |
| `CAREEM_PROMPTS_DIR` | Override the prompt directory if you run from outside the repo. |

The model layer is provider-neutral: nothing outside
[`llm.py`](src/careem_ai_reviewer/llm.py) imports an SDK or knows which backend is in
use. Adding a backend is one function plus one entry in the registry at the bottom of
that file. `LLM_API_KEY` is the credential the toolkit reads; if it is unset, the
vendor-specific variable the installed client library uses is accepted as a fallback.

---

## 12. Architecture

The design rationale — why each of these choices was made, and which are load-bearing —
is in **[ARCHITECTURE.md](ARCHITECTURE.md)**. This section is the file-by-file map.

```
prompts/
  01_smart_code_reviewer.md      Challenge 1 system prompt
  02_ai_pair_engineer.md         Challenge 2 system prompt
  03_snippet_review_3plus1.md    Challenge 3 system prompt + portable copy-paste version

samples/
  eta_service.go                 flawed ETA service (ignored error, deep nesting, magic
                                 numbers, blocking sleep, panic, misnamed haversine)
  routing.go                     flawed nearest-neighbour router (unsynchronised global
                                 cache, awkward loop bound)
  snippet.go                     7-line snippet with three real bugs

src/careem_ai_reviewer/
  analyzers.py    Static pass: Go/Python/C-like function extraction, metrics, 15 rules,
                  per-rule finding cap, and the GROUNDING FACTS renderer.
  schemas.py      JSON schemas for structured outputs. Constrained to the API's subset.
  prompts.py      Loads prompts from disk; assembles the user turn with numbered source.
  llm.py          The single model call site. Prompt caching, refusal fallbacks,
                  max_tokens / refusal / empty-response handling.
  mock.py         Offline provider derived from the static pass.
  pipeline.py     Source collection, git-diff scoping, the three mode runners.
  reporters.py    Markdown and JSON rendering, plus the CI gate decision.
  server.py       Standard-library web UI (page + /api/run + /api/samples).
  cli.py          argparse entry point, exit codes, UTF-8 console handling.

tests/            51 hermetic unittest cases
review.py         zero-install launcher
```

### Notable implementation choices

- **Prompt caching.** System prompts are byte-stable and carry a `cache_control`
  breakpoint; everything per-request goes in the user turn after it.
- **Structured outputs.** `output_config.format` pins a JSON schema, so the response is
  valid JSON by construction. A test keeps the schemas inside the API's supported subset
  (`additionalProperties: false`, complete `required`, no `minItems`).
- **Refusal handling.** Opus 5 can decline with `stop_reason: "refusal"` on an HTTP 200,
  so `stop_reason` is checked before `content` is read. Server-side fallbacks are opted
  into by default and degrade gracefully on older SDK versions.
- **ASCII-only reports.** They land in PR comments, CI logs and `cp1252` Windows
  consoles. A test asserts it.
- **Per-rule finding cap.** Twelve `magic_number` notes bury the one blocker, so repeats
  past the fifth collapse into a summary line.

---

## 13. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `'python' is not recognized` | Use `py -3` instead of `python`, or install Python from python.org and tick "Add to PATH". |
| `error: No API key found` | Either set the key (section 7) or add `--mock`. The tool refuses to silently downgrade. |
| `error: The API client library is not installed` | `pip install -r requirements.txt`, or use `--mock`. |
| `Prompt file not found` | Run from the repository root, or set `CAREEM_PROMPTS_DIR` to the absolute path of `prompts/`. |
| `error: No reviewable source files found` | The path has no files with a supported extension. Check with `python review.py scan <path>`. |
| Web UI port already in use | `python review.py serve --mock --port 8123` |
| `The response hit max_tokens before finishing` | `--max-tokens 32000`, or `--effort low`, or fewer files per run. |
| `The model declined this request` | A safety classifier fired. Retry with a smaller excerpt. |
| Report shows `provider: mock` unexpectedly | `--mock` is still on the command line, or the web UI checkbox is still ticked. |
| Garbled characters in PowerShell | The reports are ASCII; if paths render oddly, run `chcp 65001` first. |
