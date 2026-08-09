"""End-to-end tests for the three challenge pipelines, plus the CI gate.

All of these run in `--mock` mode, so the suite is hermetic: no key, no network,
no cost, and the same result on every machine.
"""

import json
import unittest

from careem_ai_reviewer.analyzers import analyze_source
from careem_ai_reviewer.config import GatePolicy, Settings
from careem_ai_reviewer.llm import LLMError
from careem_ai_reviewer.pipeline import collect_sources, run_pair, run_review, run_snippet
from careem_ai_reviewer.reporters import (
    evaluate_gate,
    render_json,
    render_pair_markdown,
    render_review_markdown,
    render_snippet_markdown,
)
from careem_ai_reviewer.schemas import SCHEMAS

BUGGY_GO = """package eta

func AverageETA(etas []int) int {
\ttotal := 0
\tfor i := 0; i <= len(etas); i++ {
\t\ttotal += etas[i]
\t}
\treturn total / len(etas)
}
"""

CLEAN_GO = """package eta

// AverageETA returns the mean ETA in seconds, or 0 for an empty input.
func AverageETA(etas []int) (int, error) {
\tif len(etas) == 0 {
\t\treturn 0, errEmpty
\t}
\ttotal := 0
\tfor _, v := range etas {
\t\ttotal += v
\t}
\treturn total / len(etas), nil
}
"""

MOCK = Settings(mock=True)


def assert_matches_schema(case: unittest.TestCase, data, schema, path="root"):
    """A small structural check against the subset of JSON Schema we emit."""
    kind = schema.get("type")
    if kind == "object":
        case.assertIsInstance(data, dict, path)
        for key in schema.get("required", []):
            case.assertIn(key, data, f"{path}.{key} missing")
        for key, value in data.items():
            case.assertIn(key, schema["properties"], f"{path}.{key} not in schema")
            assert_matches_schema(case, value, schema["properties"][key], f"{path}.{key}")
    elif kind == "array":
        case.assertIsInstance(data, list, path)
        for index, item in enumerate(data):
            assert_matches_schema(case, item, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        case.assertIsInstance(data, str, path)
        if "enum" in schema:
            case.assertIn(data, schema["enum"], path)
    elif kind == "integer":
        case.assertIsInstance(data, int, path)


class TestSchemaHygiene(unittest.TestCase):
    """The API rejects schemas that omit these; catch it here rather than at runtime."""

    def _walk(self, node, path="root"):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            self.assertIs(node.get("additionalProperties"), False, f"{path}: needs additionalProperties=false")
            self.assertEqual(
                set(node.get("required", [])),
                set(node.get("properties", {})),
                f"{path}: required must name every property",
            )
            for key, value in node.get("properties", {}).items():
                self._walk(value, f"{path}.{key}")
        elif node.get("type") == "array":
            self._walk(node.get("items"), f"{path}[]")

    def test_all_schemas_are_api_compatible(self):
        for name, schema in SCHEMAS.items():
            with self.subTest(schema=name):
                self._walk(schema, name)

    def test_no_unsupported_keywords(self):
        unsupported = {"minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum"}
        blob = json.dumps(SCHEMAS)
        for keyword in unsupported:
            self.assertNotIn(f'"{keyword}"', blob)


class TestReviewPipeline(unittest.TestCase):
    def setUp(self):
        self.analyses = [analyze_source("eta.go", BUGGY_GO)]

    def test_result_matches_the_review_schema(self):
        result, _ = run_review(self.analyses, MOCK)
        assert_matches_schema(self, result.data, SCHEMAS["review"])

    def test_blocker_forces_request_changes(self):
        result, gate = run_review(self.analyses, MOCK)
        self.assertEqual(result.data["verdict"], "request_changes")
        self.assertFalse(gate.passed)
        self.assertEqual(gate.exit_code, 1)

    def test_clean_code_passes_the_gate(self):
        result, gate = run_review([analyze_source("eta.go", CLEAN_GO)], MOCK)
        self.assertTrue(gate.passed, gate.reasons)
        self.assertEqual(gate.exit_code, 0)
        self.assertEqual(result.data["verdict"], "approve")

    def test_findings_cite_real_lines(self):
        result, _ = run_review(self.analyses, MOCK)
        line_count = len(BUGGY_GO.splitlines())
        for finding in result.data["findings"]:
            self.assertGreaterEqual(finding["line"], 1)
            self.assertLessEqual(finding["line"], line_count)

    def test_markdown_renders(self):
        result, gate = run_review(self.analyses, MOCK)
        markdown = render_review_markdown(result, self.analyses, gate)
        self.assertIn("Smart Code Reviewer report", markdown)
        self.assertIn("REQUEST CHANGES", markdown)
        self.assertTrue(markdown.isascii(), "reports must stay ascii-safe for CI logs")

    def test_json_render_is_valid_json(self):
        result, gate = run_review(self.analyses, MOCK)
        payload = json.loads(render_json("review", result, self.analyses, gate))
        self.assertEqual(payload["mode"], "review")
        self.assertFalse(payload["gate"]["passed"])


class TestPairPipeline(unittest.TestCase):
    def test_result_matches_the_pair_schema(self):
        analyses = [analyze_source("eta.go", BUGGY_GO)]
        result = run_pair(analyses, MOCK, task="make it testable")
        assert_matches_schema(self, result.data, SCHEMAS["pair"])
        self.assertTrue(result.data["proposed_tests"])
        markdown = render_pair_markdown(result, analyses)
        self.assertIn("Tests I would write", markdown)


class TestSnippetPipeline(unittest.TestCase):
    def test_returns_exactly_three_plus_one(self):
        result, analysis = run_snippet(BUGGY_GO, MOCK, "eta.go")
        assert_matches_schema(self, result.data, SCHEMAS["snippet"])
        self.assertEqual(len(result.data["improvements"]), 3)
        self.assertTrue(result.data["positive_note"].strip())

    def test_three_plus_one_holds_for_a_clean_snippet(self):
        result, _ = run_snippet(CLEAN_GO, MOCK, "eta.go")
        self.assertEqual(len(result.data["improvements"]), 3)

    def test_markdown_renders(self):
        result, analysis = run_snippet(BUGGY_GO, MOCK, "eta.go")
        markdown = render_snippet_markdown(result, [analysis])
        self.assertIn("Three improvements", markdown)
        self.assertIn("One positive note", markdown)


class TestGatePolicy(unittest.TestCase):
    def test_policy_thresholds(self):
        findings = [{"severity": "major"} for _ in range(4)]
        strict = evaluate_gate(findings, GatePolicy(max_major=3))
        lenient = evaluate_gate(findings, GatePolicy(max_major=10))
        self.assertFalse(strict.passed)
        self.assertTrue(lenient.passed)

    def test_blocker_can_be_tolerated_if_policy_says_so(self):
        findings = [{"severity": "blocker"}]
        self.assertTrue(evaluate_gate(findings, GatePolicy(fail_on_blocker=False)).passed)

    def test_total_cap(self):
        findings = [{"severity": "nit"} for _ in range(40)]
        self.assertFalse(evaluate_gate(findings, GatePolicy(max_total=25)).passed)


class TestSourceCollection(unittest.TestCase):
    def test_missing_path_raises_a_useful_error(self):
        with self.assertRaises(LLMError) as ctx:
            collect_sources(["does/not/exist"], MOCK)
        self.assertIn("Path not found", str(ctx.exception))

    def test_samples_directory_is_reviewable(self):
        analyses = collect_sources(["samples"], MOCK)
        self.assertGreaterEqual(len(analyses), 3)
        self.assertTrue(all(a.language == "go" for a in analyses))


class TestLiveModeGuard(unittest.TestCase):
    def test_missing_key_without_mock_is_a_clear_error(self):
        import os

        saved = {k: os.environ.pop(k, None) for k in ("LLM_API_KEY", "ANTHROPIC_API_KEY")}
        try:
            with self.assertRaises(LLMError) as ctx:
                run_review([analyze_source("eta.go", BUGGY_GO)], Settings(mock=False))
            self.assertIn("--mock", str(ctx.exception))
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
