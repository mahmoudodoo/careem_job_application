"""Offline mock provider.

`--mock` exists so the whole toolkit is runnable, testable and screenshot-able with no
API key, no network and no dependencies — which also makes it usable as a CI smoke
test and keeps the unit tests hermetic.

Everything here is derived deterministically from the static pass in `analyzers.py`.
It is not a simulation of the model: it is the floor the model builds on. Reports produced
this way are labelled as mock output everywhere they surface.
"""

from __future__ import annotations

from .analyzers import FileAnalysis, Finding, cyclomatic_complexity

MOCK_BANNER = "offline mock mode - deterministic static analysis only, no model call"

_SEVERITY_WEIGHT = {"blocker": 4, "major": 2, "minor": 1, "nit": 0.25}

#: Human titles for the static rules. Truncating the message mid-sentence reads badly,
#: and the title is the only part that always gets read.
_RULE_TITLES = {
    "off_by_one_loop": "Loop reads one element past the end",
    "divide_by_length": "Division by zero on empty input",
    "ignored_error": "Error discarded with the blank identifier",
    "missing_context": "I/O call takes no context.Context",
    "long_function": "Function is doing several jobs",
    "deep_nesting": "Nesting hides the happy path",
    "high_complexity": "Too many independent paths to test",
    "too_many_params": "Parameter list has become a positional puzzle",
    "duplicated_block": "Duplicated block will drift apart",
    "magic_number": "Unexplained numeric literal",
    "blocking_sleep": "Blocking sleep on a request path",
    "panic_in_library": "panic() where an error belongs",
    "tracked_todo": "Untracked TODO left in the code",
    "long_line": "Line too long to scan",
    "missing_doc_comment": "Exported symbol has no doc comment",
}


def _title_for(finding: Finding) -> str:
    if finding.rule in _RULE_TITLES:
        return _RULE_TITLES[finding.rule]
    if finding.rule.endswith("_repeated"):
        base = finding.rule[: -len("_repeated")]
        return f"More {_RULE_TITLES.get(base, base.replace('_', ' '))} occurrences"
    return finding.rule.replace("_", " ").capitalize()


def _after_block(finding: Finding) -> str:
    """A code-shaped 'after' block, so the diff reads like a diff."""
    if finding.rule == "off_by_one_loop" and finding.evidence:
        return finding.evidence.replace("<=", "<")
    if finding.evidence:
        return f"// {finding.suggestion}\n{finding.evidence}"
    return finding.suggestion or "See the description above."
_CATEGORY_TO_SCORE = {
    "readability": "readability",
    "structure": "structure",
    "maintainability": "maintainability",
    "reliability": "maintainability",
    "correctness": "maintainability",
    "testing": "test_readiness",
    "performance": "maintainability",
}


def _clamp(value: int, low: int = 1, high: int = 5) -> int:
    return max(low, min(high, value))


def _all_findings(analyses: list[FileAnalysis]) -> list[Finding]:
    findings: list[Finding] = []
    for analysis in analyses:
        findings.extend(analysis.findings)
    findings.sort(key=lambda f: f.sort_key)
    return findings


def _total_loc(analyses: list[FileAnalysis]) -> int:
    return max(1, sum(a.loc for a in analyses))


# --------------------------------------------------------------------------- #
# Challenge 1 - review
# --------------------------------------------------------------------------- #


def _scores(analyses: list[FileAnalysis]) -> dict:
    loc = _total_loc(analyses)
    penalty = {"readability": 0.0, "structure": 0.0, "maintainability": 0.0, "test_readiness": 0.0}
    for finding in _all_findings(analyses):
        bucket = _CATEGORY_TO_SCORE.get(finding.category, "maintainability")
        penalty[bucket] += _SEVERITY_WEIGHT.get(finding.severity, 1)

    # Long, complex functions are the strongest signal for testability.
    for analysis in analyses:
        for fn in analysis.functions:
            if cyclomatic_complexity(fn.body) > 10 or fn.length > 60:
                penalty["test_readiness"] += 2

    scale = max(1.0, loc / 100)
    return {key: _clamp(5 - round(value / scale)) for key, value in penalty.items()}


def _verdict(findings: list[Finding]) -> str:
    if any(f.severity == "blocker" for f in findings):
        return "request_changes"
    if sum(1 for f in findings if f.severity == "major") >= 2:
        return "request_changes"
    if findings:
        return "comment"
    return "approve"


def _positive_notes(analyses: list[FileAnalysis]) -> list[str]:
    notes: list[str] = []
    for analysis in analyses:
        short = [fn for fn in analysis.functions if fn.length <= 20]
        if short:
            names = ", ".join(f"`{fn.name}`" for fn in short[:3])
            notes.append(
                f"{analysis.path}: {names} stay small enough to hold in your head, "
                "which is what makes them cheap to unit test."
            )
        documented = [
            fn for fn in analysis.functions if fn.exported and _has_doc_comment(analysis, fn)
        ]
        if documented:
            notes.append(
                f"{analysis.path}: exported symbols such as `{documented[0].name}` carry "
                "doc comments, so the package reads correctly in godoc."
            )
    if not notes:
        notes.append(
            "The files parse cleanly and follow a consistent layout, so the review "
            "could focus on behaviour rather than formatting."
        )
    return notes[:3]


def _has_doc_comment(analysis: FileAnalysis, fn) -> bool:
    lines = analysis.source.splitlines()
    return fn.start >= 2 and lines[fn.start - 2].strip().startswith("//")


def _finding_to_schema(finding: Finding) -> dict:
    return {
        "rule": finding.rule.replace("_", "-"),
        "severity": finding.severity,
        "category": finding.category,
        "file": finding.file,
        "line": finding.line,
        "symbol": finding.symbol,
        "message": finding.message,
        "suggestion": finding.suggestion or "Address the issue described above.",
        "confidence": "high" if finding.severity in ("blocker", "major") else "medium",
    }


def build_review(analyses: list[FileAnalysis]) -> dict:
    findings = _all_findings(analyses)
    counts = {sev: sum(1 for f in findings if f.severity == sev) for sev in
              ("blocker", "major", "minor", "nit")}
    files = ", ".join(a.path for a in analyses)

    summary = (
        f"Static review of {len(analyses)} file(s) ({_total_loc(analyses)} LOC): {files}. "
        f"Found {counts['blocker']} blocker(s), {counts['major']} major, "
        f"{counts['minor']} minor and {counts['nit']} nit issue(s). "
        f"Generated in {MOCK_BANNER}; run without --mock for reasoning about intent, "
        "root causes and suggested fixes."
    )

    return {
        "summary": summary,
        "verdict": _verdict(findings),
        "scores": _scores(analyses),
        "findings": [_finding_to_schema(f) for f in findings],
        "positive_notes": _positive_notes(analyses),
        "review_checklist": [
            "Does the change keep the ETA contract intact for every vertical it touches?",
            "Is every new I/O path covered by a context deadline and a retry policy?",
            "Which of these findings are pre-existing, and which did this change introduce?",
        ],
    }


# --------------------------------------------------------------------------- #
# Challenge 2 - pair
# --------------------------------------------------------------------------- #

_GO_TEST_TEMPLATE = """func {test_name}(t *testing.T) {{
\ttests := []struct {{
\t\tname    string
\t\twantErr bool
\t}}{{
\t\t{{name: "{case_name}", wantErr: true}},
\t}}

\tfor _, tc := range tests {{
\t\tt.Run(tc.name, func(t *testing.T) {{
\t\t\t// Arrange the input that triggers the condition, call {target},
\t\t\t// then assert on the result rather than on the implementation.
\t\t\tt.Skip("fill in: exercise {target} for {case_name}")
\t\t}})
\t}}
}}"""

_PY_TEST_TEMPLATE = """def {test_name}():
    # Arrange the input that triggers the condition, call {target},
    # then assert on the result rather than on the implementation.
    raise AssertionError("fill in: exercise {target} for {case_name}")"""


def _test_code(language: str, test_name: str, target: str, case_name: str) -> str:
    template = _GO_TEST_TEMPLATE if language == "go" else _PY_TEST_TEMPLATE
    return template.format(test_name=test_name, target=target, case_name=case_name)


def _proposed_tests(analyses: list[FileAnalysis]) -> list[dict]:
    tests: list[dict] = []
    for analysis in analyses:
        for fn in analysis.functions:
            if len(tests) >= 4:
                break
            complexity = cyclomatic_complexity(fn.body)
            if complexity < 3 and fn.length < 15:
                continue
            prefix = "Test" if analysis.language == "go" else "test"
            test_name = f"{prefix}{fn.name}_BoundaryInput" if analysis.language == "go" \
                else f"test_{fn.name}_boundary_input"
            tests.append(
                {
                    "name": test_name,
                    "kind": "unit",
                    "target": f"{analysis.path}:{fn.name}",
                    "catches": (
                        f"`{fn.name}` has {complexity} independent paths; the boundary "
                        "path is the one most likely to be wrong and least likely to be "
                        "exercised by hand."
                    ),
                    "code": _test_code(
                        analysis.language, test_name, fn.name, "empty or boundary input"
                    ),
                }
            )
    if not tests:
        tests.append(
            {
                "name": "test_placeholder",
                "kind": "unit",
                "target": "n/a",
                "catches": "No function in the input was complex enough to warrant a "
                "generated test in mock mode.",
                "code": "# run without --mock for model-authored tests",
            }
        )
    return tests


def _refactors(analyses: list[FileAnalysis]) -> list[dict]:
    refactors: list[dict] = []
    for finding in _all_findings(analyses):
        if len(refactors) >= 3:
            break
        if finding.rule == "magic_number" and finding.evidence:
            refactors.append(
                {
                    "title": "Name the magic value",
                    "rationale": finding.message,
                    "risk": "low",
                    "unified_diff": (
                        f"--- a/{finding.file}\n+++ b/{finding.file}\n"
                        f"@@ -{finding.line},1 +{finding.line},1 @@\n"
                        f"-{finding.evidence}\n"
                        f"+// replace the literal with a named constant\n"
                        f"+{finding.evidence}"
                    ),
                }
            )
        elif finding.rule == "long_function":
            refactors.append(
                {
                    "title": f"Split `{finding.symbol}` into named steps",
                    "rationale": finding.message,
                    "risk": "medium",
                    "unified_diff": (
                        f"--- a/{finding.file}\n+++ b/{finding.file}\n"
                        f"@@ -{finding.line},0 +{finding.line},0 @@\n"
                        f"# extract the distinct phases of {finding.symbol} into helpers\n"
                        f"# so each can be tested without the others"
                    ),
                }
            )
        elif finding.rule == "duplicated_block":
            refactors.append(
                {
                    "title": "Collapse the duplicated block",
                    "rationale": finding.message,
                    "risk": "low",
                    "unified_diff": (
                        f"--- a/{finding.file}\n+++ b/{finding.file}\n"
                        f"@@ -{finding.line},0 +{finding.line},0 @@\n"
                        f"# hoist the repeated lines into a single helper and call it twice"
                    ),
                }
            )
    if not refactors:
        refactors.append(
            {
                "title": "No mechanical refactor found",
                "rationale": "The static pass found nothing it can rewrite safely. "
                "Run without --mock for design-level suggestions.",
                "risk": "low",
                "unified_diff": "",
            }
        )
    return refactors


def build_pair(analyses: list[FileAnalysis], task: str = "") -> dict:
    findings = _all_findings(analyses)
    serious = [f for f in findings if f.severity in ("blocker", "major")][:6]

    flaws = [
        {
            "title": _title_for(finding),
            "where": f"{finding.file}:{finding.line}",
            "why_it_matters": finding.message,
            "severity": finding.severity,
            "recommended_change": finding.suggestion or "See the message above.",
        }
        for finding in serious
    ] or [
        {
            "title": "No structural flaw detected by the static pass",
            "where": analyses[0].path if analyses else "n/a",
            "why_it_matters": "Every measured metric is inside its threshold.",
            "severity": "nit",
            "recommended_change": "Run without --mock for a design-level opinion.",
        }
    ]

    summary = (
        f"{MOCK_BANNER}. Measured {sum(len(a.functions) for a in analyses)} function(s) "
        f"across {len(analyses)} file(s); {len(serious)} of them breach a structural or "
        "reliability threshold."
    )
    if task:
        summary += f" Stated task: {task}"

    return {
        "design_review": {"summary": summary, "flaws": flaws},
        "proposed_tests": _proposed_tests(analyses),
        "refactors": _refactors(analyses),
        "keep_doing": _positive_notes(analyses),
        "open_questions": [
            "Which of these functions are on the hot request path versus a background job?",
            "Is there an existing helper for this that the static pass cannot see?",
        ],
    }


# --------------------------------------------------------------------------- #
# Challenge 3 - snippet
# --------------------------------------------------------------------------- #

_GENERIC_IMPROVEMENTS = [
    {
        "title": "No test covers this behaviour",
        "why": "Nothing here pins the current behaviour down, so the next change to it "
        "is unverifiable and any regression reaches production silently.",
        "before": "(no test file alongside this code)",
        "after": "Add one table-driven test covering the empty input, the single-element "
        "input, and the failure path.",
    },
    {
        "title": "Names describe mechanism, not intent",
        "why": "A reader has to trace the body to learn what the code is for, which is "
        "the cost paid on every future visit to this file.",
        "before": "(identifiers in the snippet)",
        "after": "Rename to the domain concept the value represents, e.g. `etaSeconds` "
        "rather than `t`.",
    },
    {
        "title": "No boundary handling for empty input",
        "why": "The happy path assumes at least one element; an empty collection reaches "
        "the same code and produces a divide-by-zero or an out-of-range read.",
        "before": "(entry point of the snippet)",
        "after": "Guard the empty case explicitly and return a typed error or a "
        "documented zero value.",
    },
]


def build_snippet(analysis: FileAnalysis) -> dict:
    findings = analysis.findings[:3]
    improvements = [
        {
            "title": _title_for(finding),
            "why": finding.message,
            "before": finding.evidence or f"line {finding.line}",
            "after": _after_block(finding),
        }
        for finding in findings
    ]

    index = 0
    while len(improvements) < 3:
        improvements.append(_GENERIC_IMPROVEMENTS[index % len(_GENERIC_IMPROVEMENTS)])
        index += 1

    if analysis.functions:
        shortest = min(analysis.functions, key=lambda fn: fn.length)
        positive = (
            f"`{shortest.name}` is only {shortest.length} lines and takes its inputs as "
            "plain parameters, so it can be tested without standing anything up. That is "
            "the property that makes every other issue here cheap to fix."
        )
    else:
        positive = (
            "The snippet is short enough to read in one pass, which is what makes a "
            "review like this possible at all."
        )

    severities = {f.severity for f in analysis.findings}
    if "blocker" in severities:
        verdict = "Do not merge yet - at least one issue here will fail at runtime."
    elif "major" in severities:
        verdict = "Mergeable after the structural issues above are addressed."
    else:
        verdict = "Solid; the improvements above are polish rather than defects."

    return {
        "language": analysis.language,
        "improvements": improvements[:3],
        "positive_note": positive,
        "verdict": f"{verdict} ({MOCK_BANNER})",
    }
