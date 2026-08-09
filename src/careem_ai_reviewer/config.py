"""Central configuration: model defaults, thresholds, and the CI gate policy."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# --- Model -------------------------------------------------------------------

#: Backend adapter to use. See the provider registry in `llm.py`.
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "messages-api")

#: Model identifier passed straight through to the backend. Override per run with
#: `--model`, or globally with the LLM_MODEL environment variable.
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "claude-opus-5")

DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT = "medium"  # low | medium | high | xhigh | max
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")

# --- Severity ----------------------------------------------------------------

SEVERITIES = ("blocker", "major", "minor", "nit")
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}

CATEGORIES = (
    "readability",
    "structure",
    "maintainability",
    "reliability",
    "correctness",
    "testing",
    "performance",
)


@dataclass(frozen=True)
class Thresholds:
    """Tunable limits for the deterministic static pre-pass."""

    max_function_lines: int = 60
    max_nesting_depth: int = 4
    max_line_length: int = 120
    max_params: int = 5
    max_cyclomatic: int = 12
    duplicate_window: int = 5  # consecutive identical lines that count as a clone


@dataclass(frozen=True)
class GatePolicy:
    """When should the reviewer block a pull request?

    Used by `review --gate` so the tool can run as a CI step.
    """

    fail_on_blocker: bool = True
    max_major: int = 3
    max_total: int = 25


@dataclass
class Settings:
    model: str = DEFAULT_MODEL
    provider: str = DEFAULT_PROVIDER
    max_tokens: int = DEFAULT_MAX_TOKENS
    effort: str = DEFAULT_EFFORT
    mock: bool = False
    thresholds: Thresholds = field(default_factory=Thresholds)
    gate: GatePolicy = field(default_factory=GatePolicy)

    @staticmethod
    def has_api_key() -> bool:
        from .llm import resolve_api_key  # local import: avoids a circular import

        return bool(resolve_api_key())


#: File extensions the toolkit will read when walking a directory.
SOURCE_EXTENSIONS = {
    ".go",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".rs",
    ".php",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
}

#: Directories skipped when walking a tree.
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "__pycache__",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "target",
}

LANGUAGE_BY_EXTENSION = {
    ".go": "go",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".rb": "ruby",
    ".rs": "rust",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
}
