"""CLI-layer tests.

The pipeline tests construct `Settings` directly, which means they cannot catch a bug
in how the parser builds `Settings`. That gap let a real one through once: argparse's
`set_defaults()` mutates `action.default` in place, and because every subparser shares
one `--mock` Action via `parents=[common]`, setting `mock=True` on the `scan` subparser
silently turned mock mode on for `review`, `pair` and `snippet` as well. Live runs
returned offline reports and said nothing. Hence `TestMockIsOptIn`.
"""

import os
import unittest

from careem_ai_reviewer.cli import build_parser
from careem_ai_reviewer.config import DEFAULT_EFFORT, DEFAULT_MODEL, DEFAULT_PROVIDER
from careem_ai_reviewer.llm import API_KEY_VARS, LLMError, complete

SUBCOMMANDS_TAKING_MOCK = ("review", "pair", "snippet", "scan", "serve", "demo")


class TestMockIsOptIn(unittest.TestCase):
    """Offline mode must never switch itself on. A silent downgrade is a wrong answer."""

    def test_mock_defaults_to_false_for_every_subcommand(self):
        parser = build_parser()
        for command in SUBCOMMANDS_TAKING_MOCK:
            with self.subTest(command=command):
                args = parser.parse_args([command])
                self.assertFalse(
                    args.mock,
                    f"`{command}` defaults to mock mode; live runs would silently "
                    "return offline reports",
                )

    def test_mock_flag_is_honoured_when_passed(self):
        parser = build_parser()
        for command in SUBCOMMANDS_TAKING_MOCK:
            with self.subTest(command=command):
                self.assertTrue(parser.parse_args([command, "--mock"]).mock)

    def test_one_subcommands_defaults_do_not_leak_into_another(self):
        """Regression guard for the shared-Action mutation described in the docstring."""
        parser = build_parser()
        parser.parse_args(["scan"])  # the subcommand that used to poison the default
        self.assertFalse(parser.parse_args(["review"]).mock)
        self.assertFalse(build_parser().parse_args(["review"]).mock)


class TestParserDefaults(unittest.TestCase):
    def test_shared_options_are_present_everywhere(self):
        parser = build_parser()
        for command in SUBCOMMANDS_TAKING_MOCK:
            with self.subTest(command=command):
                args = parser.parse_args([command])
                self.assertEqual(args.model, DEFAULT_MODEL)
                self.assertEqual(args.provider, DEFAULT_PROVIDER)
                self.assertEqual(args.effort, DEFAULT_EFFORT)

    def test_overrides_parse(self):
        args = build_parser().parse_args(
            ["review", "src", "--model", "x-1", "--provider", "custom",
             "--effort", "max", "--max-tokens", "999"]
        )
        self.assertEqual(args.model, "x-1")
        self.assertEqual(args.provider, "custom")
        self.assertEqual(args.effort, "max")
        self.assertEqual(args.max_tokens, 999)
        self.assertEqual(args.paths, ["src"])

    def test_invalid_effort_is_rejected(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["review", "--effort", "turbo"])

    def test_gate_is_opt_in(self):
        self.assertFalse(build_parser().parse_args(["review"]).gate)
        self.assertTrue(build_parser().parse_args(["review", "--gate"]).gate)


class TestLiveModeRefusesToDowngrade(unittest.TestCase):
    def setUp(self):
        self._saved = {name: os.environ.pop(name, None) for name in API_KEY_VARS}

    def tearDown(self):
        for name, value in self._saved.items():
            if value is not None:
                os.environ[name] = value

    def test_no_key_and_no_mock_raises_rather_than_falling_back(self):
        from careem_ai_reviewer.config import Settings

        with self.assertRaises(LLMError) as ctx:
            complete(
                mode="review",
                system="s",
                user="u",
                schema={"type": "object", "properties": {}, "required": [],
                        "additionalProperties": False},
                settings=Settings(mock=False),
                mock_builder=lambda: {"should": "never be called"},
            )
        message = str(ctx.exception)
        self.assertIn("No API key found", message)
        self.assertIn("--mock", message)

    def test_unknown_provider_is_rejected(self):
        from careem_ai_reviewer.config import Settings

        os.environ["LLM_API_KEY"] = "test-key-not-used"
        try:
            with self.assertRaises(LLMError) as ctx:
                complete(
                    mode="review",
                    system="s",
                    user="u",
                    schema={"type": "object", "properties": {}, "required": [],
                            "additionalProperties": False},
                    settings=Settings(mock=False, provider="does-not-exist"),
                    mock_builder=lambda: {},
                )
            self.assertIn("Unknown provider", str(ctx.exception))
        finally:
            os.environ.pop("LLM_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
