"""Deterministic static pre-pass.

Why this exists
---------------
An LLM asked to "review this code" will happily invent line numbers and
metrics. This module computes the countable facts first - function length,
nesting depth, parameter counts, cyclomatic complexity, ignored errors,
duplicated blocks - and feeds them to the model as *grounding facts*.

The model then does the part it is genuinely good at: judgement, naming,
explaining why something will hurt the next reader, and proposing a fix.
Every metric the report quotes is computed here, not guessed there.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import LANGUAGE_BY_EXTENSION, SEVERITY_ORDER, Thresholds

# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class Finding:
    """A single review observation, from the static pass or from the model."""

    rule: str
    severity: str  # blocker | major | minor | nit
    category: str  # readability | structure | maintainability | ...
    line: int
    message: str
    file: str = ""
    symbol: str = ""
    evidence: str = ""
    suggestion: str = ""
    source: str = "static"  # static | ai

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def sort_key(self) -> tuple:
        return (SEVERITY_ORDER.get(self.severity, 9), self.file, self.line)


@dataclass
class FunctionSpan:
    """A parsed function/method with its computed metrics."""

    name: str
    start: int  # 1-based, inclusive
    end: int  # 1-based, inclusive
    params: str
    body: list[str] = field(default_factory=list)
    exported: bool = False

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def param_count(self) -> int:
        return _count_params(self.params)


@dataclass
class FileAnalysis:
    """Everything the static pass knows about one file."""

    path: str
    language: str
    source: str
    loc: int
    functions: list[FunctionSpan] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def metrics(self) -> dict:
        lengths = [f.length for f in self.functions] or [0]
        return {
            "lines_of_code": self.loc,
            "function_count": len(self.functions),
            "longest_function_lines": max(lengths),
            "average_function_lines": round(sum(lengths) / len(lengths), 1),
            "static_findings": len(self.findings),
        }


# --------------------------------------------------------------------------- #
# Lexical helpers
# --------------------------------------------------------------------------- #

_STRING_RE = re.compile(r"""(".*?"|'.*?'|`.*?`)""")
_LINE_COMMENT_RE = re.compile(r"(//.*$|#.*$)")

_C_LIKE = {"go", "java", "kotlin", "csharp", "javascript", "typescript", "rust", "c", "cpp", "php"}


def detect_language(path: str) -> str:
    return LANGUAGE_BY_EXTENSION.get(Path(path).suffix.lower(), "unknown")


def strip_noise(line: str) -> str:
    """Remove string literals and line comments so regexes don't match inside them."""
    line = _STRING_RE.sub('""', line)
    return _LINE_COMMENT_RE.sub("", line)


def _count_params(params: str) -> int:
    """Count top-level comma-separated parameters, ignoring nested generics/parens."""
    params = params.strip()
    if not params:
        return 0
    depth = 0
    count = 1
    for ch in params:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count


def _indent_width(line: str, tab_size: int = 4) -> int:
    width = 0
    for ch in line:
        if ch == " ":
            width += 1
        elif ch == "\t":
            width += tab_size
        else:
            break
    return width


# --------------------------------------------------------------------------- #
# Function extraction
# --------------------------------------------------------------------------- #

_GO_FUNC_RE = re.compile(
    r"^func\s+(?:\((?P<recv>[^)]*)\)\s*)?(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)?\((?P<params>.*)$"
)
_PY_FUNC_RE = re.compile(r"^(?P<indent>[ \t]*)(?:async\s+)?def\s+(?P<name>\w+)\s*\((?P<params>.*)$")
_CLIKE_FUNC_RE = re.compile(
    r"^\s*(?:public|private|protected|internal|static|final|async|export|func|fn|function|def)"
    r"[\w\s<>,\[\]]*?\b(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^;]*)$"
)


def _balance(line: str) -> int:
    clean = strip_noise(line)
    return clean.count("{") - clean.count("}")


def _extract_go_functions(lines: list[str]) -> list[FunctionSpan]:
    spans: list[FunctionSpan] = []
    i = 0
    while i < len(lines):
        match = _GO_FUNC_RE.match(lines[i])
        if not match:
            i += 1
            continue
        name = match.group("name")
        start = i
        depth = _balance(lines[i])
        j = i
        # A one-line signature may not open a brace yet (multi-line params).
        while depth <= 0 and j + 1 < len(lines) and "{" not in strip_noise(lines[j]):
            j += 1
            depth += _balance(lines[j])
        while depth > 0 and j + 1 < len(lines):
            j += 1
            depth += _balance(lines[j])
        spans.append(
            FunctionSpan(
                name=name,
                start=start + 1,
                end=j + 1,
                params=match.group("params").rsplit(")", 1)[0],
                body=lines[start : j + 1],
                exported=name[:1].isupper(),
            )
        )
        i = j + 1
    return spans


def _extract_python_functions(lines: list[str]) -> list[FunctionSpan]:
    spans: list[FunctionSpan] = []
    for i, line in enumerate(lines):
        match = _PY_FUNC_RE.match(line)
        if not match:
            continue
        base = _indent_width(match.group("indent"))
        j = i
        for k in range(i + 1, len(lines)):
            candidate = lines[k]
            if not candidate.strip():
                continue
            if _indent_width(candidate) <= base:
                break
            j = k
        else:
            j = len(lines) - 1
        name = match.group("name")
        spans.append(
            FunctionSpan(
                name=name,
                start=i + 1,
                end=j + 1,
                params=match.group("params").rsplit(")", 1)[0],
                body=lines[i : j + 1],
                exported=not name.startswith("_"),
            )
        )
    return spans


def _extract_clike_functions(lines: list[str]) -> list[FunctionSpan]:
    spans: list[FunctionSpan] = []
    i = 0
    while i < len(lines):
        match = _CLIKE_FUNC_RE.match(lines[i])
        if not match or "{" not in strip_noise(lines[i]):
            i += 1
            continue
        start = i
        depth = _balance(lines[i])
        j = i
        while depth > 0 and j + 1 < len(lines):
            j += 1
            depth += _balance(lines[j])
        name = match.group("name")
        spans.append(
            FunctionSpan(
                name=name,
                start=start + 1,
                end=j + 1,
                params=match.group("params").rsplit(")", 1)[0],
                body=lines[start : j + 1],
                exported=True,
            )
        )
        i = j + 1
    return spans


def extract_functions(source: str, language: str) -> list[FunctionSpan]:
    lines = source.splitlines()
    if language == "go":
        return _extract_go_functions(lines)
    if language == "python":
        return _extract_python_functions(lines)
    if language in _C_LIKE:
        return _extract_clike_functions(lines)
    return []


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

_BRANCH_RE = re.compile(r"\b(if|for|while|case|catch|elif|switch)\b|&&|\|\||\?\?")


def cyclomatic_complexity(body: list[str]) -> int:
    """Approximate McCabe complexity: 1 + number of decision points."""
    return 1 + sum(len(_BRANCH_RE.findall(strip_noise(line))) for line in body)


def max_nesting_depth(body: list[str], language: str) -> int:
    """Deepest block nesting inside a function body."""
    if language == "python":
        if len(body) < 2:
            return 0
        base = _indent_width(body[0])
        levels = [
            (_indent_width(line) - base) // 4 for line in body[1:] if line.strip()
        ]
        # A statement at indent level 1 sits directly in the function body, inside zero
        # blocks - so subtract one to match the Go/brace definition of "nesting".
        return max(0, max(levels, default=0) - 1)

    depth = 0
    peak = 0
    for line in body:
        clean = strip_noise(line)
        for ch in clean:
            if ch == "{":
                depth += 1
                peak = max(peak, depth)
            elif ch == "}":
                depth = max(0, depth - 1)
    # The function's own brace is depth 1; report nesting *inside* it.
    return max(0, peak - 1)


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

#: How many findings of the same rule to report per file before summarising the rest.
#: Real linters do this too - twelve identical magic-number notes bury the one blocker.
MAX_FINDINGS_PER_RULE = 5

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
_MAGIC_NUMBER_RE = re.compile(r"(?<![\w.])(\d{2,}(?:\.\d+)?)(?![\w.])")
_GO_IGNORED_ERR_RE = re.compile(r"(^|\s)_\s*(:?=)\s*\w")
_GO_PANIC_RE = re.compile(r"\bpanic\(")
_SLEEP_RE = re.compile(r"\b(time\.Sleep|Thread\.sleep|time\.sleep)\b")
_ALLOWED_NUMBERS = {"0", "1", "2", "10", "100", "200", "404", "500", "1000", "24", "60", "1024"}
_GO_IO_VERB_RE = re.compile(r"^(Get|Fetch|Load|Query|Call|Send|Post|Read|Write|Sync|Push|Pull)")
#: `i <= len(xs)` walks one past the end - a classic index-out-of-range panic.
#: The lookahead keeps the correct `i <= len(xs)-1` form out of the results; a rule
#: that cries wolf on valid code is worse than no rule.
_OFF_BY_ONE_RE = re.compile(
    r"<=\s*(?:len\([^)]*\)|\w+\.length\b|\w+\.size\(\))\s*(?![-+]\s*\d)"
)
_DIVIDE_BY_LEN_RE = re.compile(r"/\s*(?:len\(|\w+\.length\b|\w+\.size\(\))")
_EMPTY_GUARD_RE = re.compile(r"(len\([^)]*\)\s*(==|<=|<)\s*(0|1)|is\s+empty|IsEmpty\(\))")


def _file_level_rules(analysis: FileAnalysis, thresholds: Thresholds) -> list[Finding]:
    out: list[Finding] = []
    lines = analysis.source.splitlines()
    lang = analysis.language

    for idx, raw in enumerate(lines, start=1):
        clean = strip_noise(raw)

        if len(raw.rstrip("\n")) > thresholds.max_line_length:
            out.append(
                Finding(
                    rule="long_line",
                    severity="nit",
                    category="readability",
                    line=idx,
                    file=analysis.path,
                    message=(
                        f"Line is {len(raw.rstrip())} characters "
                        f"(limit {thresholds.max_line_length})."
                    ),
                    evidence=raw.strip()[:160],
                    suggestion="Break the expression across lines or extract a named local.",
                )
            )

        todo = _TODO_RE.search(raw)
        if todo:
            out.append(
                Finding(
                    rule="tracked_todo",
                    severity="minor",
                    category="maintainability",
                    line=idx,
                    file=analysis.path,
                    message=f"{todo.group(1)} comment left in code with no linked ticket.",
                    evidence=raw.strip()[:160],
                    suggestion="Link a ticket ID or resolve before merge.",
                )
            )

        for number in _MAGIC_NUMBER_RE.findall(clean):
            if number in _ALLOWED_NUMBERS:
                continue
            out.append(
                Finding(
                    rule="magic_number",
                    severity="minor",
                    category="maintainability",
                    line=idx,
                    file=analysis.path,
                    message=f"Unexplained literal `{number}` - the reader cannot tell what it means.",
                    evidence=clean.strip()[:160],
                    suggestion="Promote it to a named constant or a config field.",
                )
            )
            break  # one finding per line is enough signal

        if _OFF_BY_ONE_RE.search(clean):
            out.append(
                Finding(
                    rule="off_by_one_loop",
                    severity="blocker",
                    category="correctness",
                    line=idx,
                    file=analysis.path,
                    message=(
                        "Loop bound uses `<= len(...)`, so the final iteration indexes one "
                        "past the end and panics at runtime."
                    ),
                    evidence=clean.strip()[:160],
                    suggestion="Use `<` instead of `<=`, or range over the collection directly.",
                )
            )

        if _SLEEP_RE.search(clean):
            out.append(
                Finding(
                    rule="blocking_sleep",
                    severity="major",
                    category="reliability",
                    line=idx,
                    file=analysis.path,
                    message="Blocking sleep on a request path stalls the goroutine/thread.",
                    evidence=clean.strip()[:160],
                    suggestion="Use a context deadline, a ticker, or a backoff helper instead.",
                )
            )

        if lang == "go":
            if _GO_IGNORED_ERR_RE.search(clean):
                out.append(
                    Finding(
                        rule="ignored_error",
                        severity="blocker",
                        category="reliability",
                        line=idx,
                        file=analysis.path,
                        message="Return value discarded with `_` - a failure here is silent.",
                        evidence=clean.strip()[:160],
                        suggestion="Handle the error, or comment why discarding it is safe.",
                    )
                )
            if _GO_PANIC_RE.search(clean):
                out.append(
                    Finding(
                        rule="panic_in_library",
                        severity="major",
                        category="reliability",
                        line=idx,
                        file=analysis.path,
                        message="panic() in service code takes down the whole process.",
                        evidence=clean.strip()[:160],
                        suggestion="Return an error and let the caller decide.",
                    )
                )

    out.extend(_duplicate_block_rule(analysis, thresholds))
    return out


def _duplicate_block_rule(analysis: FileAnalysis, thresholds: Thresholds) -> list[Finding]:
    """Flag runs of identical consecutive lines repeated elsewhere in the file."""
    window = thresholds.duplicate_window
    lines = [line.strip() for line in analysis.source.splitlines()]
    seen: dict[str, int] = {}
    out: list[Finding] = []
    reported: set[str] = set()

    for i in range(len(lines) - window + 1):
        chunk = lines[i : i + window]
        if sum(1 for line in chunk if len(line) > 3) < window:
            continue  # mostly blank/short lines - not a meaningful clone
        key = "\n".join(chunk)
        if key in seen and key not in reported:
            reported.add(key)
            out.append(
                Finding(
                    rule="duplicated_block",
                    severity="major",
                    category="structure",
                    line=i + 1,
                    file=analysis.path,
                    message=(
                        f"{window} identical lines also appear at line {seen[key] + 1}. "
                        "Two copies drift apart the first time only one is fixed."
                    ),
                    evidence=chunk[0][:160],
                    suggestion="Extract the shared logic into one helper.",
                )
            )
        seen.setdefault(key, i)
    return out


def _function_level_rules(analysis: FileAnalysis, thresholds: Thresholds) -> list[Finding]:
    out: list[Finding] = []
    lines = analysis.source.splitlines()

    for fn in analysis.functions:
        if fn.length > thresholds.max_function_lines:
            out.append(
                Finding(
                    rule="long_function",
                    severity="major",
                    category="structure",
                    line=fn.start,
                    file=analysis.path,
                    symbol=fn.name,
                    message=(
                        f"`{fn.name}` is {fn.length} lines "
                        f"(limit {thresholds.max_function_lines}) - it does several jobs at once."
                    ),
                    suggestion="Split the distinct steps into named helpers so each can be tested alone.",
                )
            )

        depth = max_nesting_depth(fn.body, analysis.language)
        if depth > thresholds.max_nesting_depth:
            out.append(
                Finding(
                    rule="deep_nesting",
                    severity="major",
                    category="readability",
                    line=fn.start,
                    file=analysis.path,
                    symbol=fn.name,
                    message=(
                        f"`{fn.name}` nests {depth} levels deep "
                        f"(limit {thresholds.max_nesting_depth})."
                    ),
                    suggestion="Use early returns / guard clauses to flatten the happy path.",
                )
            )

        complexity = cyclomatic_complexity(fn.body)
        if complexity > thresholds.max_cyclomatic:
            out.append(
                Finding(
                    rule="high_complexity",
                    severity="major",
                    category="maintainability",
                    line=fn.start,
                    file=analysis.path,
                    symbol=fn.name,
                    message=(
                        f"`{fn.name}` has cyclomatic complexity {complexity} "
                        f"(limit {thresholds.max_cyclomatic}); that is {complexity} paths to cover in tests."
                    ),
                    suggestion="Extract branches into helpers or replace the chain with a lookup table.",
                )
            )

        body_text = "\n".join(strip_noise(line) for line in fn.body)
        if _DIVIDE_BY_LEN_RE.search(body_text) and not _EMPTY_GUARD_RE.search(body_text):
            offset = next(
                (
                    i
                    for i, line in enumerate(fn.body)
                    if _DIVIDE_BY_LEN_RE.search(strip_noise(line))
                ),
                0,
            )
            out.append(
                Finding(
                    rule="divide_by_length",
                    severity="blocker",
                    category="correctness",
                    line=fn.start + offset,
                    file=analysis.path,
                    symbol=fn.name,
                    message=(
                        f"`{fn.name}` divides by a collection length with no empty-input "
                        "guard; an empty input divides by zero."
                    ),
                    evidence=fn.body[offset].strip()[:160],
                    suggestion=(
                        "Return early for the empty case with a typed error or a "
                        "documented zero value."
                    ),
                )
            )

        if fn.param_count > thresholds.max_params:
            out.append(
                Finding(
                    rule="too_many_params",
                    severity="minor",
                    category="structure",
                    line=fn.start,
                    file=analysis.path,
                    symbol=fn.name,
                    message=(
                        f"`{fn.name}` takes {fn.param_count} parameters "
                        f"(limit {thresholds.max_params}); call sites become positional puzzles."
                    ),
                    suggestion="Group related parameters into a request struct.",
                )
            )

        if analysis.language == "go":
            out.extend(_go_function_rules(analysis, fn, lines))

    return out


def _go_function_rules(
    analysis: FileAnalysis, fn: FunctionSpan, lines: list[str]
) -> list[Finding]:
    out: list[Finding] = []

    if fn.exported:
        preceding = lines[fn.start - 2].strip() if fn.start >= 2 else ""
        if not preceding.startswith("//"):
            out.append(
                Finding(
                    rule="missing_doc_comment",
                    severity="nit",
                    category="readability",
                    line=fn.start,
                    file=analysis.path,
                    symbol=fn.name,
                    message=f"Exported `{fn.name}` has no doc comment.",
                    suggestion=f"Add a `// {fn.name} ...` comment describing the contract.",
                )
            )

        if _GO_IO_VERB_RE.match(fn.name) and "context.Context" not in fn.params:
            out.append(
                Finding(
                    rule="missing_context",
                    severity="major",
                    category="reliability",
                    line=fn.start,
                    file=analysis.path,
                    symbol=fn.name,
                    message=(
                        f"`{fn.name}` looks like an I/O call but takes no context.Context, "
                        "so callers cannot set a deadline or cancel it."
                    ),
                    suggestion="Make `ctx context.Context` the first parameter and honour it.",
                )
            )

    return out


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #


def cap_repetitive_findings(
    findings: list[Finding], limit: int = MAX_FINDINGS_PER_RULE
) -> list[Finding]:
    """Keep the first `limit` findings per rule and summarise the remainder.

    A review whose top twenty items are all `magic_number` is a review nobody reads
    to the bottom of - which is where the blocker was.
    """
    kept: list[Finding] = []
    counts: dict[str, int] = {}
    overflow: dict[str, list[Finding]] = {}

    for finding in findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
        if counts[finding.rule] <= limit:
            kept.append(finding)
        else:
            overflow.setdefault(finding.rule, []).append(finding)

    for rule, extras in overflow.items():
        first = extras[0]
        lines = ", ".join(f"L{f.line}" for f in extras[:12])
        kept.append(
            Finding(
                rule=f"{rule}_repeated",
                severity="minor" if first.severity in ("blocker", "major") else "nit",
                category=first.category,
                line=first.line,
                file=first.file,
                message=(
                    f"{len(extras)} further `{rule}` occurrence(s) in this file "
                    f"({lines}). Reported once so they do not bury the rest."
                ),
                suggestion=first.suggestion,
            )
        )
    return kept


def analyze_source(
    path: str, source: str, thresholds: Thresholds | None = None
) -> FileAnalysis:
    """Run the full static pass over one file's contents."""
    thresholds = thresholds or Thresholds()
    language = detect_language(path)
    analysis = FileAnalysis(
        path=path,
        language=language,
        source=source,
        loc=len([line for line in source.splitlines() if line.strip()]),
    )
    analysis.functions = extract_functions(source, language)
    findings = _file_level_rules(analysis, thresholds) + _function_level_rules(
        analysis, thresholds
    )
    analysis.findings = sorted(cap_repetitive_findings(findings), key=lambda f: f.sort_key)
    return analysis


def analyze_path(path: str | Path, thresholds: Thresholds | None = None) -> FileAnalysis:
    p = Path(path)
    return analyze_source(str(p), p.read_text(encoding="utf-8", errors="replace"), thresholds)


def grounding_facts(analyses: list[FileAnalysis]) -> str:
    """Render the static findings as a compact block for the model prompt."""
    chunks: list[str] = []
    for analysis in analyses:
        metrics = analysis.metrics()
        head = (
            f"FILE: {analysis.path} (language={analysis.language}, "
            f"loc={metrics['lines_of_code']}, functions={metrics['function_count']})"
        )
        rows = [head]
        for fn in analysis.functions:
            rows.append(
                f"  fn {fn.name} lines {fn.start}-{fn.end} "
                f"(len={fn.length}, params={fn.param_count}, "
                f"complexity={cyclomatic_complexity(fn.body)}, "
                f"nesting={max_nesting_depth(fn.body, analysis.language)})"
            )
        if analysis.findings:
            rows.append("  static findings:")
            for finding in analysis.findings:
                rows.append(
                    f"    [{finding.severity}] L{finding.line} {finding.rule}: {finding.message}"
                )
        else:
            rows.append("  static findings: none")
        chunks.append("\n".join(rows))
    return "\n\n".join(chunks)
