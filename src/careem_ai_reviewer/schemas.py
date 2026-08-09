"""JSON schemas used for structured model outputs.

Structured outputs constrain the model's response to a schema at decode time, so the
CLI never has to regex JSON out of prose or retry a parse. The API's schema subset is
strict: every object needs `additionalProperties: false` and a `required` list naming
every property. Numeric/length constraints (minItems, minLength, ...) are not
supported, so "exactly three improvements" is enforced in the prompt and validated in
`snippet.py` after the fact.
"""

from __future__ import annotations

from .config import CATEGORIES, SEVERITIES


def _obj(properties: dict, *, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


def _str(description: str) -> dict:
    return {"type": "string", "description": description}


def _enum(values, description: str) -> dict:
    return {"type": "string", "enum": list(values), "description": description}


# --------------------------------------------------------------------------- #
# Challenge 1 - Smart Code Reviewer
# --------------------------------------------------------------------------- #

FINDING_SCHEMA = _obj(
    {
        "rule": _str("Short kebab-case identifier for the kind of issue, e.g. 'ignored-error'."),
        "severity": _enum(SEVERITIES, "blocker | major | minor | nit, judged by consequence."),
        "category": _enum(CATEGORIES, "Which review dimension this belongs to."),
        "file": _str("Path of the file the finding is in, exactly as given."),
        "line": {"type": "integer", "description": "1-based line number that exists in the input."},
        "symbol": _str("Enclosing function or type name, or an empty string."),
        "message": _str("One or two sentences: the problem and its consequence."),
        "suggestion": _str("The concrete change that resolves it."),
        "confidence": _enum(("high", "medium", "low"), "How sure you are this is a real defect."),
    }
)

REVIEW_SCHEMA = _obj(
    {
        "summary": _str("2-4 sentences a human reviewer can read before opening the diff."),
        "verdict": _enum(
            ("approve", "comment", "request_changes"),
            "approve = merge as is; comment = merge after author's judgement; "
            "request_changes = something must change first.",
        ),
        "scores": _obj(
            {
                "readability": {"type": "integer", "description": "1 (poor) to 5 (exemplary)."},
                "structure": {"type": "integer", "description": "1 (poor) to 5 (exemplary)."},
                "maintainability": {"type": "integer", "description": "1 (poor) to 5 (exemplary)."},
                "test_readiness": {
                    "type": "integer",
                    "description": "1 (untestable without the world) to 5 (clean seams).",
                },
            }
        ),
        "findings": {"type": "array", "items": FINDING_SCHEMA},
        "positive_notes": {
            "type": "array",
            "items": _str("Something specific the author did well, and why it pays off."),
        },
        "review_checklist": {
            "type": "array",
            "items": _str("A question the human reviewer should still answer themselves."),
        },
    }
)

# --------------------------------------------------------------------------- #
# Challenge 2 - The AI Pair Engineer
# --------------------------------------------------------------------------- #

DESIGN_FLAW_SCHEMA = _obj(
    {
        "title": _str("The flaw in under ten words."),
        "where": _str("file:line, or file:line-line for a range."),
        "why_it_matters": _str("The concrete consequence for this system."),
        "severity": _enum(SEVERITIES, "blocker | major | minor | nit."),
        "recommended_change": _str("The smallest change that removes the flaw."),
    }
)

PROPOSED_TEST_SCHEMA = _obj(
    {
        "name": _str("Test function name, e.g. TestAverageETA_EmptySlice."),
        "kind": _enum(("unit", "integration", "e2e"), "Level the test operates at."),
        "target": _str("The function or behaviour under test."),
        "catches": _str("One line: the bug this test fails on."),
        "code": _str("Runnable test source in the same language as the reviewed file."),
    }
)

REFACTOR_SCHEMA = _obj(
    {
        "title": _str("What the refactor does, in under ten words."),
        "rationale": _str("Why it is worth doing now."),
        "risk": _enum(("low", "medium", "high"), "Honest risk of changing behaviour."),
        "unified_diff": _str("A unified diff a human can read and apply."),
    }
)

PAIR_SCHEMA = _obj(
    {
        "design_review": _obj(
            {
                "summary": _str("2-4 sentences on the shape of the code as it stands."),
                "flaws": {"type": "array", "items": DESIGN_FLAW_SCHEMA},
            }
        ),
        "proposed_tests": {"type": "array", "items": PROPOSED_TEST_SCHEMA},
        "refactors": {"type": "array", "items": REFACTOR_SCHEMA},
        "keep_doing": {
            "type": "array",
            "items": _str("A decision in the current code worth preserving."),
        },
        "open_questions": {
            "type": "array",
            "items": _str("Something you had to assume, phrased as a question for the author."),
        },
    }
)

# --------------------------------------------------------------------------- #
# Challenge 3 - Code Review Assistant (3 improvements + 1 positive note)
# --------------------------------------------------------------------------- #

IMPROVEMENT_SCHEMA = _obj(
    {
        "title": _str("The problem in under ten words."),
        "why": _str("One or two sentences on what actually goes wrong."),
        "before": _str("The exact lines from the snippet."),
        "after": _str("The same lines rewritten, in the same language and style."),
    }
)

SNIPPET_SCHEMA = _obj(
    {
        "language": _str("Language of the snippet as you detected it."),
        "improvements": {
            "type": "array",
            "items": IMPROVEMENT_SCHEMA,
            "description": "Exactly three, ordered by consequence.",
        },
        "positive_note": _str("One specific thing done well, and why it pays off later."),
        "verdict": _str("A single line summarising the snippet's state."),
    }
)

SCHEMAS = {
    "review": REVIEW_SCHEMA,
    "pair": PAIR_SCHEMA,
    "snippet": SNIPPET_SCHEMA,
}
