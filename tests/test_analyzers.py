"""Tests for the deterministic static pass.

These matter more than they look: the whole design rests on the claim that the
numbers handed to the model are measured rather than guessed. If the parser is wrong,
the model is confidently grounded in nonsense.
"""

import unittest

from careem_ai_reviewer.analyzers import (
    analyze_source,
    cyclomatic_complexity,
    extract_functions,
    max_nesting_depth,
    strip_noise,
)
from careem_ai_reviewer.config import Thresholds

GO_SAMPLE = """package eta

// Add sums two numbers.
func Add(a, b int) int {
\treturn a + b
}

func average(values []int) int {
\ttotal := 0
\tfor i := 0; i <= len(values); i++ {
\t\ttotal += values[i]
\t}
\treturn total / len(values)
}
"""

PY_SAMPLE = '''def outer(a, b):
    if a:
        for _ in range(b):
            if b > 2:
                return 1
    return 0


def other():
    return 2
'''


def rules(analysis) -> set:
    return {finding.rule for finding in analysis.findings}


class TestLexer(unittest.TestCase):
    def test_strip_noise_removes_comments_and_strings(self):
        self.assertNotIn("secret", strip_noise('x := "secret" // also secret'))
        self.assertIn("x :=", strip_noise('x := "secret" // also secret'))


class TestGoParsing(unittest.TestCase):
    def setUp(self):
        self.functions = extract_functions(GO_SAMPLE, "go")

    def test_finds_both_functions(self):
        self.assertEqual([fn.name for fn in self.functions], ["Add", "average"])

    def test_spans_are_one_based_and_bounded(self):
        add = self.functions[0]
        self.assertEqual(add.start, 4)
        self.assertEqual(add.end, 6)
        self.assertEqual(add.length, 3)

    def test_exported_detection(self):
        self.assertTrue(self.functions[0].exported)
        self.assertFalse(self.functions[1].exported)

    def test_param_counting(self):
        self.assertEqual(self.functions[0].param_count, 2)  # a, b int -> two params
        self.assertEqual(self.functions[1].param_count, 1)


class TestPythonParsing(unittest.TestCase):
    def setUp(self):
        self.functions = extract_functions(PY_SAMPLE, "python")

    def test_finds_functions(self):
        self.assertEqual([fn.name for fn in self.functions], ["outer", "other"])

    def test_body_ends_before_next_def(self):
        outer = self.functions[0]
        self.assertEqual(outer.start, 1)
        self.assertEqual(outer.end, 6)

    def test_nesting_depth(self):
        self.assertEqual(max_nesting_depth(self.functions[0].body, "python"), 3)


class TestMetrics(unittest.TestCase):
    def test_cyclomatic_counts_decision_points(self):
        body = ["if a {", "for i := range xs {", "if b && c {", "}", "}", "}"]
        # 1 base + if + for + if + && = 5
        self.assertEqual(cyclomatic_complexity(body), 5)

    def test_cyclomatic_ignores_comments(self):
        self.assertEqual(cyclomatic_complexity(["// if for while"]), 1)

    def test_go_nesting_excludes_the_function_brace(self):
        body = ["func f() {", "\tif a {", "\t\tb()", "\t}", "}"]
        self.assertEqual(max_nesting_depth(body, "go"), 1)


class TestCorrectnessRules(unittest.TestCase):
    def test_off_by_one_loop_is_a_blocker(self):
        analysis = analyze_source("x.go", GO_SAMPLE)
        self.assertIn("off_by_one_loop", rules(analysis))
        finding = next(f for f in analysis.findings if f.rule == "off_by_one_loop")
        self.assertEqual(finding.severity, "blocker")
        self.assertEqual(finding.line, 10)

    def test_correct_loop_bound_is_not_flagged(self):
        source = "func f(xs []int) {\n\tfor i := 0; i <= len(xs)-1; i++ {\n\t}\n}\n"
        self.assertNotIn("off_by_one_loop", rules(analyze_source("x.go", source)))

    def test_divide_by_length_is_a_blocker(self):
        self.assertIn("divide_by_length", rules(analyze_source("x.go", GO_SAMPLE)))

    def test_divide_by_length_respects_an_empty_guard(self):
        source = (
            "func mean(xs []int) int {\n"
            "\tif len(xs) == 0 {\n\t\treturn 0\n\t}\n"
            "\treturn sum(xs) / len(xs)\n}\n"
        )
        self.assertNotIn("divide_by_length", rules(analyze_source("x.go", source)))


class TestReliabilityRules(unittest.TestCase):
    def test_ignored_error(self):
        source = "func f() {\n\t_ = doThing()\n}\n"
        self.assertIn("ignored_error", rules(analyze_source("x.go", source)))

    def test_panic_and_sleep(self):
        source = "func f() {\n\ttime.Sleep(5 * time.Second)\n\tpanic(\"no\")\n}\n"
        found = rules(analyze_source("x.go", source))
        self.assertIn("blocking_sleep", found)
        self.assertIn("panic_in_library", found)

    def test_missing_context_on_io_shaped_exported_func(self):
        source = "// GetThing fetches.\nfunc GetThing(id string) error {\n\treturn nil\n}\n"
        self.assertIn("missing_context", rules(analyze_source("x.go", source)))

    def test_context_first_param_satisfies_the_rule(self):
        source = (
            "// GetThing fetches.\n"
            "func GetThing(ctx context.Context, id string) error {\n\treturn nil\n}\n"
        )
        self.assertNotIn("missing_context", rules(analyze_source("x.go", source)))


class TestStructureRules(unittest.TestCase):
    def test_long_function(self):
        body = "\n".join(f"\tx{i} := {i}" for i in range(80))
        source = f"func big() {{\n{body}\n}}\n"
        self.assertIn("long_function", rules(analyze_source("x.go", source)))

    def test_duplicated_block(self):
        block = "\n".join(f"\tcallSomething{i}()" for i in range(5))
        source = f"func a() {{\n{block}\n}}\n\nfunc b() {{\n{block}\n}}\n"
        self.assertIn("duplicated_block", rules(analyze_source("x.go", source)))

    def test_thresholds_are_configurable(self):
        source = "func f() {\n\tx := 1\n\ty := 2\n}\n"
        strict = Thresholds(max_function_lines=2)
        self.assertIn("long_function", rules(analyze_source("x.go", source, strict)))
        self.assertNotIn("long_function", rules(analyze_source("x.go", source)))


class TestFindingCap(unittest.TestCase):
    def test_repeated_rule_is_summarised(self):
        # 1100.. avoids the allow-list of conventional numbers (0, 1, 100, 1000, ...).
        lines = "\n".join(f"\tv{i} := {1100 + i}" for i in range(12))
        analysis = analyze_source("x.go", f"func f() {{\n{lines}\n}}\n")
        magic = [f for f in analysis.findings if f.rule == "magic_number"]
        summary = [f for f in analysis.findings if f.rule == "magic_number_repeated"]
        self.assertEqual(len(magic), 5)
        self.assertEqual(len(summary), 1)
        self.assertIn("7 further", summary[0].message)


class TestMetricsSummary(unittest.TestCase):
    def test_metrics_shape(self):
        metrics = analyze_source("x.go", GO_SAMPLE).metrics()
        self.assertEqual(metrics["function_count"], 2)
        self.assertGreater(metrics["lines_of_code"], 5)
        self.assertGreaterEqual(metrics["longest_function_lines"], 3)


if __name__ == "__main__":
    unittest.main()
