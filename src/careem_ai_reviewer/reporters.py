"""Rendering: Markdown reports, JSON payloads, and the CI gate decision.

Output is ASCII-only on purpose - these reports get pasted into PR comments, CI logs
and Windows terminals, and a stray box-drawing character in a cp1252 console is a
crash rather than a cosmetic problem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .analyzers import FileAnalysis
from .config import GatePolicy, SEVERITY_ORDER
from .llm import LLMResult

SEVERITY_LABEL = {
    "blocker": "BLOCKER",
    "major": "MAJOR",
    "minor": "minor",
    "nit": "nit",
}

VERDICT_LABEL = {
    "approve": "APPROVE",
    "comment": "COMMENT",
    "request_changes": "REQUEST CHANGES",
}


# --------------------------------------------------------------------------- #
# CI gate
# --------------------------------------------------------------------------- #


@dataclass
class GateDecision:
    passed: bool
    reasons: list[str]
    counts: dict

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1


def evaluate_gate(findings: list[dict], policy: GatePolicy) -> GateDecision:
    counts = {sev: 0 for sev in SEVERITY_ORDER}
    for finding in findings:
        severity = finding.get("severity", "minor")
        counts[severity] = counts.get(severity, 0) + 1
    counts["total"] = len(findings)

    reasons: list[str] = []
    if policy.fail_on_blocker and counts.get("blocker", 0) > 0:
        reasons.append(f"{counts['blocker']} blocker finding(s); policy allows 0.")
    if counts.get("major", 0) > policy.max_major:
        reasons.append(
            f"{counts['major']} major finding(s); policy allows {policy.max_major}."
        )
    if counts["total"] > policy.max_total:
        reasons.append(
            f"{counts['total']} findings in total; policy allows {policy.max_total}."
        )
    return GateDecision(passed=not reasons, reasons=reasons, counts=counts)


# --------------------------------------------------------------------------- #
# Shared pieces
# --------------------------------------------------------------------------- #


def _provenance(result: LLMResult, analyses: list[FileAnalysis]) -> list[str]:
    files = ", ".join(f"`{a.path}`" for a in analyses) if analyses else "n/a"
    rows = [
        "| | |",
        "|---|---|",
        f"| Reviewed | {files} |",
        f"| Provider | `{result.provider}` |",
        f"| Model | `{result.model}` |",
        f"| Elapsed | {result.elapsed_s}s |",
    ]
    if result.usage:
        usage = result.usage
        rows.append(
            "| Tokens | in {inp}, out {out}, cache-read {cr}, cache-write {cw} |".format(
                inp=usage.get("input_tokens", 0),
                out=usage.get("output_tokens", 0),
                cr=usage.get("cache_read_input_tokens", 0),
                cw=usage.get("cache_creation_input_tokens", 0),
            )
        )
    return rows


def _notes_block(result: LLMResult) -> list[str]:
    if not result.notes:
        return []
    return ["", "> " + "  \n> ".join(result.notes)]


def _bullets(items, empty: str = "_None._") -> list[str]:
    if not items:
        return [empty]
    return [f"- {item}" for item in items]


# --------------------------------------------------------------------------- #
# Challenge 1 - review
# --------------------------------------------------------------------------- #


def render_review_markdown(
    result: LLMResult, analyses: list[FileAnalysis], gate: GateDecision | None = None
) -> str:
    data = result.data
    lines: list[str] = ["# Smart Code Reviewer report", ""]
    lines += _provenance(result, analyses)
    lines += _notes_block(result)

    verdict = VERDICT_LABEL.get(data.get("verdict", ""), data.get("verdict", "unknown"))
    lines += ["", f"**Verdict: {verdict}**", "", data.get("summary", ""), ""]

    scores = data.get("scores") or {}
    if scores:
        lines += ["## Scores", "", "| Dimension | Score |", "|---|---|"]
        for key in ("readability", "structure", "maintainability", "test_readiness"):
            if key in scores:
                value = scores[key]
                bar = "#" * int(value) + "." * (5 - int(value))
                lines.append(f"| {key.replace('_', ' ').title()} | {value}/5 `{bar}` |")
        lines.append("")

    findings = data.get("findings") or []
    counts = {sev: sum(1 for f in findings if f.get("severity") == sev) for sev in SEVERITY_ORDER}
    lines += [
        "## Findings",
        "",
        f"{len(findings)} total - "
        + ", ".join(f"{counts[sev]} {SEVERITY_LABEL[sev]}" for sev in SEVERITY_ORDER),
        "",
    ]

    if not findings:
        lines.append("_No findings. The change is clean against the current rubric._")
    for index, finding in enumerate(
        sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity"), 9), f.get("line", 0))),
        start=1,
    ):
        label = SEVERITY_LABEL.get(finding.get("severity", "minor"), "minor")
        symbol = f" in `{finding['symbol']}`" if finding.get("symbol") else ""
        lines += [
            f"### {index}. [{label}] {finding.get('rule', 'finding')}"
            f" - {finding.get('file', '')}:{finding.get('line', 0)}{symbol}",
            "",
            finding.get("message", ""),
            "",
            f"**Fix:** {finding.get('suggestion', '')}",
            "",
            f"<sub>category: {finding.get('category', '-')} | "
            f"confidence: {finding.get('confidence', '-')}</sub>",
            "",
        ]

    lines += ["## What the author got right", ""]
    lines += _bullets(data.get("positive_notes"))
    lines += ["", "## Still needs a human", ""]
    lines += _bullets(data.get("review_checklist"))

    if gate is not None:
        lines += ["", "## CI gate", ""]
        if gate.passed:
            lines.append("PASS - the change is within policy.")
        else:
            lines.append("FAIL - policy violations:")
            lines += [f"- {reason}" for reason in gate.reasons]

    lines += ["", "---", "", "<sub>Generated by careem-ai-reviewer.</sub>", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Challenge 2 - pair
# --------------------------------------------------------------------------- #


def render_pair_markdown(result: LLMResult, analyses: list[FileAnalysis]) -> str:
    data = result.data
    lines: list[str] = ["# AI Pair Engineer session", ""]
    lines += _provenance(result, analyses)
    lines += _notes_block(result)

    design = data.get("design_review") or {}
    lines += ["", "## 1. Design review", "", design.get("summary", ""), ""]

    flaws = design.get("flaws") or []
    if not flaws:
        lines.append("_No design flaws identified._")
    for index, flaw in enumerate(flaws, start=1):
        label = SEVERITY_LABEL.get(flaw.get("severity", "minor"), "minor")
        lines += [
            f"### {index}. [{label}] {flaw.get('title', '')}",
            "",
            f"**Where:** `{flaw.get('where', '')}`",
            "",
            flaw.get("why_it_matters", ""),
            "",
            f"**Change:** {flaw.get('recommended_change', '')}",
            "",
        ]

    lines += ["## 2. Tests I would write", ""]
    tests = data.get("proposed_tests") or []
    if not tests:
        lines.append("_No tests proposed._")
    for test in tests:
        lines += [
            f"### `{test.get('name', '')}` ({test.get('kind', 'unit')})",
            "",
            f"**Target:** `{test.get('target', '')}`  ",
            f"**Catches:** {test.get('catches', '')}",
            "",
            "```go" if _looks_like_go(test.get("code", "")) else "```python",
            test.get("code", ""),
            "```",
            "",
        ]

    lines += ["## 3. Refactors", ""]
    refactors = data.get("refactors") or []
    if not refactors:
        lines.append("_No refactors proposed._")
    for refactor in refactors:
        lines += [
            f"### {refactor.get('title', '')} (risk: {refactor.get('risk', 'unknown')})",
            "",
            refactor.get("rationale", ""),
            "",
        ]
        if refactor.get("unified_diff"):
            lines += ["```diff", refactor["unified_diff"], "```", ""]

    lines += ["## Keep doing", ""]
    lines += _bullets(data.get("keep_doing"))
    lines += ["", "## Open questions for you", ""]
    lines += _bullets(data.get("open_questions"))
    lines += ["", "---", "", "<sub>Generated by careem-ai-reviewer.</sub>", ""]
    return "\n".join(lines)


def _looks_like_go(code: str) -> bool:
    return "func " in code and "t *testing.T" in code


# --------------------------------------------------------------------------- #
# Challenge 3 - snippet
# --------------------------------------------------------------------------- #


def render_snippet_markdown(result: LLMResult, analyses: list[FileAnalysis]) -> str:
    data = result.data
    lines: list[str] = ["# Code Review Assistant", ""]
    lines += _provenance(result, analyses)
    lines += _notes_block(result)
    lines += ["", f"**Language:** {data.get('language', 'unknown')}", "", "## Three improvements", ""]

    for index, item in enumerate(data.get("improvements") or [], start=1):
        lines += [f"### {index}. {item.get('title', '')}", "", item.get("why", ""), ""]
        if item.get("before"):
            lines += ["**Before**", "", "```", item["before"], "```", ""]
        if item.get("after"):
            lines += ["**After**", "", "```", item["after"], "```", ""]

    lines += [
        "## One positive note",
        "",
        data.get("positive_note", ""),
        "",
        "---",
        "",
        f"**Verdict:** {data.get('verdict', '')}",
        "",
        "<sub>Generated by careem-ai-reviewer.</sub>",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #


def render_json(
    mode: str,
    result: LLMResult,
    analyses: list[FileAnalysis],
    gate: GateDecision | None = None,
) -> str:
    payload = {
        "mode": mode,
        "provider": result.provider,
        "model": result.model,
        "elapsed_s": result.elapsed_s,
        "usage": result.usage,
        "notes": result.notes,
        "files": [
            {"path": a.path, "language": a.language, "metrics": a.metrics()} for a in analyses
        ],
        "static_findings": [f.to_dict() for a in analyses for f in a.findings],
        "report": result.data,
    }
    if gate is not None:
        payload["gate"] = {
            "passed": gate.passed,
            "reasons": gate.reasons,
            "counts": gate.counts,
        }
    return json.dumps(payload, indent=2, ensure_ascii=False)


RENDERERS = {
    "review": render_review_markdown,
    "pair": render_pair_markdown,
    "snippet": render_snippet_markdown,
}
