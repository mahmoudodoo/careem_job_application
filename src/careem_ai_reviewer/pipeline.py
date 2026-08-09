"""Orchestration: gather sources, run the static pass, call the model, render."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import mock as mock_provider
from .analyzers import FileAnalysis, analyze_source, detect_language
from .config import IGNORED_DIRS, SOURCE_EXTENSIONS, Settings
from .llm import LLMError, LLMResult, complete
from .prompts import build_pair_turn, build_review_turn, build_snippet_turn, load_system_prompt
from .reporters import GateDecision, evaluate_gate
from .schemas import SCHEMAS

MAX_FILE_BYTES = 400_000


def display_path(path: Path) -> str:
    """Report paths relative to the working directory when we can.

    Reports get pasted into PR comments; an absolute path from someone's laptop is
    noise at best and leaks a directory layout at worst.
    """
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --------------------------------------------------------------------------- #
# Source collection
# --------------------------------------------------------------------------- #


def _iter_files(target: Path):
    if target.is_file():
        yield target
        return
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SOURCE_EXTENSIONS:
            yield path


def collect_sources(paths, settings: Settings) -> list[FileAnalysis]:
    """Read every source file under `paths` and run the deterministic static pass."""
    analyses: list[FileAnalysis] = []
    seen: set[Path] = set()

    for raw in paths:
        target = Path(raw)
        if not target.exists():
            raise LLMError(f"Path not found: {target}")
        for path in _iter_files(target):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            analyses.append(
                analyze_source(display_path(path), source, settings.thresholds)
            )

    if not analyses:
        raise LLMError(
            "No reviewable source files found. Supported extensions: "
            + ", ".join(sorted(SOURCE_EXTENSIONS))
        )
    return analyses


def changed_files(ref: str = "HEAD~1") -> list[str]:
    """Files changed against a git ref - lets the reviewer run on a diff in CI."""
    try:
        output = subprocess.run(
            ["git", "diff", "--name-only", ref],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise LLMError(f"Could not read changed files from git ({ref}): {exc}") from exc

    files = [
        line.strip()
        for line in output.splitlines()
        if line.strip()
        and Path(line.strip()).suffix.lower() in SOURCE_EXTENSIONS
        and Path(line.strip()).exists()
    ]
    if not files:
        raise LLMError(f"No reviewable source files changed against {ref}.")
    return files


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #


def run_review(
    analyses: list[FileAnalysis], settings: Settings, context: str = ""
) -> tuple[LLMResult, GateDecision]:
    """Challenge 1: pre-human-review quality gate."""
    result = complete(
        mode="review",
        system=load_system_prompt("review"),
        user=build_review_turn(analyses, context),
        schema=SCHEMAS["review"],
        settings=settings,
        mock_builder=lambda: mock_provider.build_review(analyses),
    )
    gate = evaluate_gate(result.data.get("findings") or [], settings.gate)
    return result, gate


def run_pair(
    analyses: list[FileAnalysis], settings: Settings, task: str = ""
) -> LLMResult:
    """Challenge 2: design flaws, proposed tests, refactors."""
    return complete(
        mode="pair",
        system=load_system_prompt("pair"),
        user=build_pair_turn(analyses, task),
        schema=SCHEMAS["pair"],
        settings=settings,
        mock_builder=lambda: mock_provider.build_pair(analyses, task),
    )


def run_snippet(
    source: str, settings: Settings, filename: str = "snippet.txt"
) -> tuple[LLMResult, FileAnalysis]:
    """Challenge 3: exactly three improvements plus one positive note."""
    analysis = analyze_source(filename, source, settings.thresholds)
    language = detect_language(filename)

    result = complete(
        mode="snippet",
        system=load_system_prompt("snippet"),
        user=build_snippet_turn(source, language, filename),
        schema=SCHEMAS["snippet"],
        settings=settings,
        mock_builder=lambda: mock_provider.build_snippet(analysis),
    )
    _enforce_three(result)
    return result, analysis


def _enforce_three(result: LLMResult) -> None:
    """The '3 + 1' shape is the contract; schemas cannot express array lengths."""
    improvements = result.data.get("improvements") or []
    if len(improvements) > 3:
        result.data["improvements"] = improvements[:3]
        result.notes.append(
            f"Model returned {len(improvements)} improvements; kept the first three "
            "to honour the 3+1 contract."
        )
    elif len(improvements) < 3:
        result.notes.append(
            f"Model returned only {len(improvements)} improvement(s) - fewer than the "
            "3+1 contract asks for."
        )
