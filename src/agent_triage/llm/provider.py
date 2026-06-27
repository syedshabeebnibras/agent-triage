"""Model-agnostic LLM provider layer.

Cognition's whole architecture is "route across providers (Anthropic, OpenAI, our
own SWE models) for best price/performance." We mirror that here: the triage
engine never imports a vendor SDK directly. It depends on the `LLMProvider`
protocol, and we can swap Claude, GPT, or a local model behind it.

This also makes the engine *testable offline*: `MockProvider` returns
deterministic, schema-valid responses so the full pipeline (and CI) runs without
network access or API spend. Real runs use `AnthropicProvider`.
"""

from __future__ import annotations

import json
import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal interface the triage engine needs from any model."""

    name: str

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> dict:
        """Return a parsed JSON object from the model.

        Implementations must guarantee a dict is returned (parsing/repair is the
        provider's responsibility), so the engine can stay simple.
        """
        ...


class ProviderError(RuntimeError):
    """Raised when a provider cannot return a usable response."""


def _extract_json(text: str) -> dict:
    """Best-effort JSON extraction from a model response.

    Handles the common cases: clean JSON, JSON in ```json fences, or JSON with
    leading/trailing prose. Raises ProviderError if nothing parses.
    """
    text = text.strip()
    # strip code fences if present
    if "```" in text:
        # take the content between the first pair of fences
        parts = text.split("```")
        for part in parts:
            candidate = part
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:]
            candidate = candidate.strip()
            if candidate.startswith("{"):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
    # try the whole thing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # last resort: grab the outermost {...}
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Could not parse JSON from response: {exc}") from exc
    raise ProviderError("No JSON object found in model response")


class AnthropicProvider:
    """Claude-backed provider. Used for real triage runs.

    Kept import-light: the anthropic SDK is imported lazily so the package (and
    CI) doesn't require it unless you actually call a real model.
    """

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        self.model = model
        self.name = f"anthropic:{model}"
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            if not self._api_key:
                raise ProviderError(
                    "ANTHROPIC_API_KEY not set; cannot use AnthropicProvider. "
                    "Use MockProvider for offline runs."
                )
            try:
                import anthropic  # noqa: PLC0415
            except ImportError as exc:
                raise ProviderError(
                    "anthropic SDK not installed. `pip install anthropic`."
                ) from exc
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> dict:
        client = self._ensure_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return _extract_json(text)


class MockProvider:
    """Deterministic offline provider for tests and demos without API spend.

    It inspects the user prompt for taxonomy signal keywords and returns a
    plausible, schema-valid classification. This is NOT a real classifier — it
    exists so the pipeline, API, dashboard, and CI are fully runnable offline.
    Real evaluation numbers must come from a real provider.
    """

    def __init__(self, forced_code: str | None = None):
        self.name = "mock"
        self.forced_code = forced_code

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> dict:
        lowered = user.lower()
        code = self.forced_code or self._guess(lowered)
        return {
            "primary_category": code,
            "confidence": 0.55,
            "root_cause": (
                "[MOCK] Deterministic offline classification based on keyword "
                f"signals. Selected {code}."
            ),
            "evidence_step_indices": self._guess_evidence(lowered),
            "secondary_category": None,
            "reasoning": "[MOCK] Offline heuristic; not a real model judgment.",
        }

    @staticmethod
    def _guess(text: str) -> str:
        table = [
            (("modulenotfound", "importerror", "pip install", "no module named"), "ENVIRONMENT"),
            (("rate limit", "429", "503", "connection reset", "traceback"), "INFRA_ERROR"),
            (("max iterations", "context window", "token limit", "timeout"), "RESOURCE_LIMIT"),
            (("patch does not apply", "edit failed", "malformed"), "TOOL_USE"),
            (("finish", "did not run tests", "premature"), "VERIFICATION"),
            (("could not find", "no such file", "grep"), "CONTEXT_RETRIEVAL"),
            (("assertion", "off-by-one", "wrong"), "REASONING"),
            (("ambiguous", "unclear", "underspecified"), "SCOPING"),
        ]
        for keys, code in table:
            if any(k in text for k in keys):
                return code
        return "OTHER"

    @staticmethod
    def _guess_evidence(text: str) -> list[int]:
        # mock: claim the first couple of steps as evidence
        return [0]


def default_provider() -> LLMProvider:
    """Pick a real provider if a key is present, else the offline mock."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicProvider()
    return MockProvider()
