"""The model layer: a provider-neutral core plus the offline mock provider.

The rest of the toolkit never imports a vendor SDK. It calls `complete()` with a system
prompt, a user turn and a JSON schema, and gets back a validated dict. Everything
vendor-specific is confined to a single adapter below, selected by `--provider`, so
swapping backends means adding one function rather than touching the pipeline.

Design notes
------------
* **Structured outputs.** Every request pins the response to the JSON schema for that
  mode, so the result is valid JSON by construction and the CLI never has to salvage
  JSON out of prose.
* **Prompt caching.** The system prompt is byte-stable per mode and carries a cache
  breakpoint; the diff and grounding facts go in the user turn, after the breakpoint.
  Reviewing ten files in one run therefore pays for the rubric once.
* **Refusals are not errors.** A safety classifier can decline a request and still
  return HTTP 200 with `stop_reason: "refusal"`. Code that reads `content[0]`
  unconditionally breaks on that, so `stop_reason` is checked first.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from .config import Settings

#: Preferred key, then the vendor-specific name the SDK reads on its own.
API_KEY_VARS = ("LLM_API_KEY", "ANTHROPIC_API_KEY")

#: Opt-in beta for server-side fallbacks when a request is declined by a classifier.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """Raised for anything that stops us returning a valid report."""


@dataclass
class LLMResult:
    data: dict
    provider: str
    model: str
    elapsed_s: float = 0.0
    usage: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"


def resolve_api_key() -> str | None:
    """First key found wins. Lets one variable drive any backend."""
    for name in API_KEY_VARS:
        value = os.environ.get(name)
        if value:
            return value
    return None


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def complete(
    *,
    mode: str,
    system: str,
    user: str,
    schema: dict,
    settings: Settings,
    mock_builder,
) -> LLMResult:
    """Produce a structured result for `mode`, from the model or from the mock provider."""
    started = time.monotonic()

    if settings.mock:
        return LLMResult(
            data=mock_builder(),
            provider="mock",
            model="offline-heuristics",
            elapsed_s=round(time.monotonic() - started, 3),
            notes=[
                "Offline mock mode: findings come from the deterministic static pass "
                "only. No model was called."
            ],
        )

    if not resolve_api_key():
        raise LLMError(
            f"No API key found (checked {', '.join(API_KEY_VARS)}).\n"
            "  * To run against a model: set LLM_API_KEY and re-run.\n"
            "  * To run offline:         add --mock to the same command."
        )

    adapter = _ADAPTERS.get(settings.provider)
    if adapter is None:
        raise LLMError(
            f"Unknown provider {settings.provider!r}. "
            f"Available: {', '.join(sorted(_ADAPTERS))}."
        )

    data, usage, notes = adapter(system=system, user=user, schema=schema, settings=settings)
    return LLMResult(
        data=data,
        provider=settings.provider,
        model=settings.model,
        elapsed_s=round(time.monotonic() - started, 3),
        usage=usage,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Adapter: messages-style API
# --------------------------------------------------------------------------- #


def _import_sdk():
    """Imported lazily so the toolkit has no hard runtime dependency."""
    try:
        import anthropic  # noqa: PLC0415 - optional dependency, only needed for live mode
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LLMError(
            "The API client library is not installed.\n"
            "  pip install -r requirements.txt\n"
            "Or run the same command with --mock to stay offline."
        ) from exc
    return anthropic


def _is_unsupported_parameter_error(exc: Exception) -> bool:
    """True when the SDK or API rejected an optional parameter we opted into."""
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = ("unexpected keyword", "fallback", "beta", "unknown field", "extra inputs")
    return isinstance(exc, TypeError) or any(marker in text for marker in markers)


def _messages_adapter(*, system: str, user: str, schema: dict, settings: Settings):
    sdk = _import_sdk()
    client = sdk.Anthropic(api_key=resolve_api_key())

    kwargs = {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        # A stable system prompt behind a cache breakpoint: the rubric is sent once per
        # run and read from cache on every file after the first.
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        "output_config": {
            "effort": settings.effort,
            "format": {"type": "json_schema", "schema": schema},
        },
        "messages": [{"role": "user", "content": user}],
    }

    notes: list[str] = []
    try:
        response = client.beta.messages.create(
            **kwargs, betas=[_FALLBACK_BETA], fallbacks="default"
        )
    except Exception as exc:  # noqa: BLE001 - re-raised below unless it is a param issue
        if not _is_unsupported_parameter_error(exc):
            raise LLMError(f"Model request failed: {exc}") from exc
        notes.append(
            "Server-side refusal fallbacks unavailable on this client version; "
            "sent a plain request instead."
        )
        try:
            response = client.messages.create(**kwargs)
        except Exception as inner:  # noqa: BLE001
            raise LLMError(f"Model request failed: {inner}") from inner

    return _parse_response(response, notes)


def _parse_response(response, notes: list[str]):
    stop_reason = getattr(response, "stop_reason", None)

    if stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise LLMError(
            "The model declined this request"
            + (f" (category: {category})" if category else "")
            + ". Review the input for content the safety classifiers flag, or retry "
            "with a smaller excerpt."
        )

    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )

    if stop_reason == "max_tokens":
        raise LLMError(
            "The response hit max_tokens before finishing. Re-run with a larger "
            "--max-tokens, a lower --effort, or fewer files per run."
        )

    if not text.strip():
        raise LLMError("The model returned an empty response.")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - schema makes this unlikely
        raise LLMError(f"Response was not valid JSON despite the schema: {exc}") from exc

    usage = getattr(response, "usage", None)
    usage_dict = {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
    }
    return data, usage_dict, notes


#: Provider registry. Add a backend by writing one function with this signature and
#: registering it here; nothing else in the toolkit needs to change.
_ADAPTERS = {
    "messages-api": _messages_adapter,
}
