# Careem — Optional AI Challenge submission

**Applicant:** Mahmoud Al-Qudah
**Role:** Senior Software Engineer I, Backend — Marketplace ETA & Routing (Amman, Jordan)
**Repository:** <https://github.com/mahmoudodoo/careem_job_application>
**Challenges attempted:** all three (1. Smart Code Reviewer · 2. The AI Pair Engineer · 3. Code Review Assistant)

---

## 100-word summary

LLMs asked to review code invent line numbers and estimate metrics. My toolkit measures
first: a deterministic static pass parses Go and Python, computing function spans,
cyclomatic complexity, nesting and duplication, and detecting off-by-one loops, ignored
errors and divide-by-zero. Those measurements are given to the model as grounding facts, so
every finding cites a real line; the model spends its effort on consequence, root cause
and the fix. One CLI covers all three challenges — a pre-review CI gate, a pair engineer
proposing tests and refactor diffs, and a 3-improvements-plus-1-positive-note snippet
reviewer. Zero dependencies, 51 offline tests, runs without an API key.

*(102 words)*

---

## Verify it in 30 seconds

No API key, no install, no network — Python 3.10+ only:

```bash
git clone https://github.com/mahmoudodoo/careem_job_application.git
cd careem_job_application
python review.py demo --mock      # all three challenges -> out/
python review.py serve --mock     # web UI at http://127.0.0.1:8000
```

---

## Where each challenge lives

| Challenge | Prompt | Command | Sample output |
|---|---|---|---|
| 1. Smart Code Reviewer | [`prompts/01_smart_code_reviewer.md`](prompts/01_smart_code_reviewer.md) | `python review.py review samples --mock --gate` | `out/01_review.md` |
| 2. The AI Pair Engineer | [`prompts/02_ai_pair_engineer.md`](prompts/02_ai_pair_engineer.md) | `python review.py pair samples/eta_service.go --mock` | `out/02_pair.md` |
| 3. Code Review Assistant | [`prompts/03_snippet_review_3plus1.md`](prompts/03_snippet_review_3plus1.md) | `python review.py snippet samples/snippet.go --mock` | `out/03_snippet.md` |

Challenge 3's deliverable is the prompt itself; that file also contains a portable
copy-paste version for any chat model and a worked example.

---

## Dataset

**None required.** The inputs are self-authored, deliberately flawed Go fixtures in
[`samples/`](samples/), written for this submission in the ETA and routing domain. No
Careem code, data, or internal information is used anywhere in this repository.

---

## Approach, in a little more detail

**The problem I actually set out to solve.** A code-review assistant is only useful if a
reviewer can trust it. The failure mode that destroys trust fastest is not a missed bug
— it is a confident, well-written finding that cites a line that does not exist. So the
architecture puts a deterministic layer underneath the model: `analyzers.py` measures
everything countable and detects the mechanical defects, and those measurements go into
the prompt as facts the model is instructed to treat as ground truth. The model is then
freed to do the part a linter cannot: say what will go wrong, collapse three symptoms
into one root cause, and write the fix.

**Where the model earns its cost.** The sample files contain defects the static pass
provably cannot find — a package-level map written from request handlers with no mutex,
a function named `haversine` that computes flat Euclidean distance, a batch loop that
swallows every per-order error. Running with and without `--mock` shows exactly which
findings come from measurement and which come from comprehension.

**Engineering choices I would defend in review.** Zero required dependencies, so the
tool runs anywhere Python does. Structured outputs pinned to a JSON schema, so the CLI
never salvages JSON from prose. A byte-stable, cached system prompt with all volatile
content in the user turn. ASCII-only reports, because they end up in CI logs and Windows
consoles. Findings capped per rule, because twelve magic-number notes bury the one
blocker. And a negative test for every heuristic — a rule that cries wolf is worse than
no rule at all.
