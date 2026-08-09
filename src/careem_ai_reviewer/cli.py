"""Command-line interface.

    python -m careem_ai_reviewer <command> [options]

Commands
    review    Challenge 1 - Smart Code Reviewer (pre-human-review gate)
    pair      Challenge 2 - The AI Pair Engineer (flaws, tests, refactors)
    snippet   Challenge 3 - Code Review Assistant (3 improvements + 1 positive note)
    scan      Deterministic static pass only - no model call, no key needed
    serve     Local web UI on http://127.0.0.1:8000
    demo      Run all three challenges over samples/ in offline mock mode

Exit codes: 0 success, 1 CI gate failed, 2 execution error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .analyzers import cyclomatic_complexity, max_nesting_depth
from .config import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    VALID_EFFORTS,
    Settings,
)
from .llm import LLMError
from .pipeline import (
    changed_files,
    collect_sources,
    display_path,
    run_pair,
    run_review,
    run_snippet,
)
from .reporters import (
    render_json,
    render_pair_markdown,
    render_review_markdown,
    render_snippet_markdown,
)

EXIT_OK, EXIT_GATE_FAILED, EXIT_ERROR = 0, 1, 2


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252; reports are ASCII but paths may not be."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
            pass


def _emit(text: str, out: str | None) -> None:
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path}")
    else:
        print(text)


def _settings_from_args(args) -> Settings:
    return Settings(
        model=args.model,
        provider=args.provider,
        max_tokens=args.max_tokens,
        effort=args.effort,
        mock=args.mock,
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_review(args) -> int:
    settings = _settings_from_args(args)
    paths = changed_files(args.changed_since) if args.changed_since else args.paths
    analyses = collect_sources(paths, settings)
    result, gate = run_review(analyses, settings, context=args.context or "")

    if args.format == "json":
        _emit(render_json("review", result, analyses, gate), args.out)
    else:
        _emit(render_review_markdown(result, analyses, gate), args.out)

    if args.gate and not gate.passed:
        print("\nCI gate FAILED:", file=sys.stderr)
        for reason in gate.reasons:
            print(f"  - {reason}", file=sys.stderr)
        return EXIT_GATE_FAILED
    return EXIT_OK


def cmd_pair(args) -> int:
    settings = _settings_from_args(args)
    analyses = collect_sources(args.paths, settings)
    result = run_pair(analyses, settings, task=args.task or "")

    if args.format == "json":
        _emit(render_json("pair", result, analyses), args.out)
    else:
        _emit(render_pair_markdown(result, analyses), args.out)
    return EXIT_OK


def cmd_snippet(args) -> int:
    settings = _settings_from_args(args)

    if args.code:
        source, filename = args.code, args.filename or "snippet.txt"
    elif args.stdin or not args.path:
        source = sys.stdin.read()
        filename = args.filename or "snippet.txt"
        if not source.strip():
            raise LLMError("No snippet on stdin. Pass a file path, --code, or pipe input.")
    else:
        path = Path(args.path)
        if not path.is_file():
            raise LLMError(f"Not a file: {path}")
        source = path.read_text(encoding="utf-8", errors="replace")
        filename = args.filename or display_path(path)

    result, analysis = run_snippet(source, settings, filename)

    if args.format == "json":
        _emit(render_json("snippet", result, [analysis]), args.out)
    else:
        _emit(render_snippet_markdown(result, [analysis]), args.out)
    return EXIT_OK


def cmd_scan(args) -> int:
    """Static pass only - the grounding layer, with no model involved."""
    settings = _settings_from_args(args)
    settings.mock = True  # scan never reaches the model layer; make that explicit
    analyses = collect_sources(args.paths, settings)

    total = 0
    for analysis in analyses:
        metrics = analysis.metrics()
        print(f"\n{analysis.path}  [{analysis.language}]")
        print(
            f"  loc={metrics['lines_of_code']} functions={metrics['function_count']} "
            f"longest={metrics['longest_function_lines']} "
            f"avg={metrics['average_function_lines']}"
        )
        for fn in analysis.functions:
            print(
                f"    fn {fn.name:<28} L{fn.start}-{fn.end} "
                f"len={fn.length:<4} params={fn.param_count} "
                f"cx={cyclomatic_complexity(fn.body):<3} "
                f"nest={max_nesting_depth(fn.body, analysis.language)}"
            )
        for finding in analysis.findings:
            total += 1
            print(
                f"  [{finding.severity:<7}] L{finding.line:<4} {finding.rule:<20} "
                f"{finding.message}"
            )
    print(f"\n{total} static finding(s) across {len(analyses)} file(s).")
    return EXIT_OK


def cmd_serve(args) -> int:
    from .server import serve  # imported lazily: only this command needs http.server

    settings = _settings_from_args(args)
    serve(host=args.host, port=args.port, settings=settings)
    return EXIT_OK


def cmd_demo(args) -> int:
    """Run all three challenges over samples/ so a reviewer can see output instantly."""
    root = Path(__file__).resolve().parents[2]
    samples = root / "samples"
    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    settings = _settings_from_args(args)

    eta = samples / "eta_service.go"
    routing = samples / "routing.go"
    snippet = samples / "snippet.go"
    for required in (eta, routing, snippet):
        if not required.exists():
            raise LLMError(f"Missing sample file: {required}")

    print(f"[1/3] review   -> {eta.name}, {routing.name}")
    analyses = collect_sources([eta, routing], settings)
    review_result, gate = run_review(
        analyses, settings, context="Adding multi-vertical ETA support."
    )
    (outdir / "01_review.md").write_text(
        render_review_markdown(review_result, analyses, gate), encoding="utf-8"
    )

    print(f"[2/3] pair     -> {eta.name}")
    pair_analyses = collect_sources([eta], settings)
    pair_result = run_pair(
        pair_analyses, settings, task="Make ETA computation testable and add a timeout."
    )
    (outdir / "02_pair.md").write_text(
        render_pair_markdown(pair_result, pair_analyses), encoding="utf-8"
    )

    print(f"[3/3] snippet  -> {snippet.name}")
    snippet_result, snippet_analysis = run_snippet(
        snippet.read_text(encoding="utf-8"), settings, display_path(snippet)
    )
    (outdir / "03_snippet.md").write_text(
        render_snippet_markdown(snippet_result, [snippet_analysis]), encoding="utf-8"
    )

    print(f"\nDone. Reports written to {outdir}/")
    print(f"  gate: {'PASS' if gate.passed else 'FAIL'} "
          f"({gate.counts.get('blocker', 0)} blocker, {gate.counts.get('major', 0)} major)")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="careem-ai-reviewer",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default=DEFAULT_MODEL, help=f"default: {DEFAULT_MODEL}")
    common.add_argument("--provider", default=DEFAULT_PROVIDER,
                        help=f"backend adapter (default: {DEFAULT_PROVIDER})")
    common.add_argument("--effort", default=DEFAULT_EFFORT, choices=VALID_EFFORTS,
                        help=f"thinking/effort level (default: {DEFAULT_EFFORT})")
    common.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        dest="max_tokens", help=f"default: {DEFAULT_MAX_TOKENS}")
    common.add_argument("--mock", action="store_true",
                        help="run offline with deterministic heuristics; no API key needed")

    output = argparse.ArgumentParser(add_help=False)
    output.add_argument("--format", choices=("md", "json"), default="md")
    output.add_argument("--out", help="write the report to this file instead of stdout")

    sub = parser.add_subparsers(dest="command", required=True)

    p_review = sub.add_parser("review", parents=[common, output],
                              help="Challenge 1 - Smart Code Reviewer")
    p_review.add_argument("paths", nargs="*", default=["samples"],
                          help="files or directories (default: samples)")
    p_review.add_argument("--context", help="what the change is meant to do")
    p_review.add_argument("--changed-since", metavar="REF",
                          help="review only files changed against a git ref, e.g. origin/main")
    p_review.add_argument("--gate", action="store_true",
                          help="exit 1 when the findings breach the CI policy")
    p_review.set_defaults(func=cmd_review)

    p_pair = sub.add_parser("pair", parents=[common, output],
                            help="Challenge 2 - The AI Pair Engineer")
    p_pair.add_argument("paths", nargs="*", default=["samples/eta_service.go"])
    p_pair.add_argument("--task", help="what you are trying to build right now")
    p_pair.set_defaults(func=cmd_pair)

    p_snippet = sub.add_parser("snippet", parents=[common, output],
                               help="Challenge 3 - Code Review Assistant (3 + 1)")
    p_snippet.add_argument("path", nargs="?", help="file to review; omit to read stdin")
    p_snippet.add_argument("--code", help="pass the snippet inline instead of a file")
    p_snippet.add_argument("--stdin", action="store_true", help="force reading from stdin")
    p_snippet.add_argument("--filename", help="name used for language detection")
    p_snippet.set_defaults(func=cmd_snippet)

    p_scan = sub.add_parser("scan", parents=[common],
                            help="static pass only - no model call, no API key")
    p_scan.add_argument("paths", nargs="*", default=["samples"])
    # NB: do not pass `mock=True` to set_defaults here. `parents=[common]` shares one
    # Action object across every subparser, and set_defaults mutates `action.default`
    # in place - which would silently flip --mock on for `review`, `pair` and `snippet`
    # too, making live mode quietly return mock reports. `cmd_scan` sets it locally.
    p_scan.set_defaults(func=cmd_scan)

    p_serve = sub.add_parser("serve", parents=[common], help="local web UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    p_demo = sub.add_parser("demo", parents=[common],
                            help="run all three challenges over samples/")
    p_demo.add_argument("--out-dir", default="out", dest="out_dir")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LLMError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
