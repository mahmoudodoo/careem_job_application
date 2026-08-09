"""Prompt loading and user-turn assembly.

The three system prompts live in `prompts/*.md` at the repo root rather than as
string literals in Python, for two reasons:

* Challenge 3's deliverable *is* a prompt, so a reviewer should be able to read it
  without reading Python.
* The system prompt stays byte-stable across requests, which is what makes the
  prompt cache work (see `llm.py`). All per-request content goes in the user turn.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .analyzers import FileAnalysis, grounding_facts

_START = "<!-- SYSTEM PROMPT START -->"
_END = "<!-- SYSTEM PROMPT END -->"

PROMPT_FILES = {
    "review": "01_smart_code_reviewer.md",
    "pair": "02_ai_pair_engineer.md",
    "snippet": "03_snippet_review_3plus1.md",
}


def prompts_dir() -> Path:
    """Locate `prompts/`, honouring CAREEM_PROMPTS_DIR for unusual installs."""
    override = os.environ.get("CAREEM_PROMPTS_DIR")
    if override:
        return Path(override)
    # src/careem_ai_reviewer/prompts.py -> repo root is two levels up.
    return Path(__file__).resolve().parents[2] / "prompts"


@lru_cache(maxsize=8)
def load_system_prompt(mode: str) -> str:
    """Return the system prompt for a mode, stripped of the surrounding markdown."""
    try:
        filename = PROMPT_FILES[mode]
    except KeyError:  # pragma: no cover - guarded by argparse choices
        raise ValueError(f"unknown mode {mode!r}") from None

    path = prompts_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {path}\n"
            "Run the CLI from the repository root, or set CAREEM_PROMPTS_DIR."
        )

    text = path.read_text(encoding="utf-8")
    if _START in text and _END in text:
        text = text.split(_START, 1)[1].split(_END, 1)[0]
    return text.strip()


# --------------------------------------------------------------------------- #
# User turns
# --------------------------------------------------------------------------- #


def _render_files(analyses: list[FileAnalysis], numbered: bool = True) -> str:
    blocks = []
    for analysis in analyses:
        lines = analysis.source.splitlines()
        if numbered:
            width = len(str(len(lines)))
            body = "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))
        else:
            body = analysis.source
        blocks.append(
            f"----- BEGIN FILE {analysis.path} -----\n"
            f"```{analysis.language}\n{body}\n```\n"
            f"----- END FILE {analysis.path} -----"
        )
    return "\n\n".join(blocks)


def build_review_turn(analyses: list[FileAnalysis], context: str = "") -> str:
    """User turn for Challenge 1 (Smart Code Reviewer)."""
    parts = [
        "Review the following change. Line numbers are shown to the left of each "
        "line; use them verbatim in your findings.",
    ]
    if context:
        parts.append(f"AUTHOR CONTEXT\n{context}")
    parts.append("GROUNDING FACTS (measured by a deterministic static pass)\n" + grounding_facts(analyses))
    parts.append("CODE UNDER REVIEW\n" + _render_files(analyses))
    parts.append(
        "Produce the review report. Report root causes rather than every symptom, "
        "and keep the finding count proportional to the size of the change."
    )
    return "\n\n".join(parts)


def build_pair_turn(analyses: list[FileAnalysis], task: str = "") -> str:
    """User turn for Challenge 2 (AI Pair Engineer)."""
    parts = []
    if task:
        parts.append(f"WHAT I AM WORKING ON\n{task}")
    else:
        parts.append(
            "WHAT I AM WORKING ON\nNo task description was supplied. Infer the intent "
            "from the code and say what you inferred in `open_questions`."
        )
    parts.append("GROUNDING FACTS (measured by a deterministic static pass)\n" + grounding_facts(analyses))
    parts.append("CURRENT CODE\n" + _render_files(analyses))
    parts.append(
        "Give me the design flaws, the tests you would write, and the refactors you "
        "would make. Rank each list by consequence and keep the refactors independently "
        "mergeable."
    )
    return "\n\n".join(parts)


def build_snippet_turn(snippet: str, language: str = "", filename: str = "") -> str:
    """User turn for Challenge 3 (Code Review Assistant)."""
    header = "Review this snippet."
    if filename:
        header += f" It comes from `{filename}`."
    if language and language != "unknown":
        header += f" The language is {language}."
    fence = language if language and language != "unknown" else ""
    return f"{header}\n\n```{fence}\n{snippet.rstrip()}\n```"
