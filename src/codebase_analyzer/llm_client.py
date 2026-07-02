"""LangChain-based LLM integration.

Two structured-output chains, both built on a single `ChatAnthropic`
instance via `with_structured_output`, so schema-conformant JSON is
guaranteed by the SDK/API rather than by prompt engineering alone:

  - `analyze_batch`     — per-class descriptions for one chunker.ClassBatch.
  - `generate_overview` — the single, project-wide summary, run once.

Every call's token usage is accumulated onto a shared `UsageTracker` so
`pipeline.py` can report and cost the whole run — cost is a first-class,
inspectable output of this tool, not a hidden side effect.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from codebase_analyzer.exceptions import LLMExtractionError
from codebase_analyzer.schemas import ClassBatchAnalysis, ProjectOverview

logger = logging.getLogger(__name__)

# Published per-million-token list pricing (USD), used only to produce an
# approximate cost estimate in the run summary. Actual billing may differ
# (promotional/negotiated rates, price changes) — see README limitations.
_PRICING_USD_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
}
_DEFAULT_PRICING = (1.00, 5.00)  # fall back to Haiku-tier pricing for an unrecognized model ID

_BATCH_SYSTEM_PROMPT = (
    "You are analyzing Java classes from a Spring Boot codebase. For each class "
    "provided, write a concise, technically accurate description of its purpose "
    "and, for every method listed, a one-sentence description of what it does. "
    "Base your analysis strictly on the signatures, annotations, Javadoc, and "
    "complexity flags given -- do not invent behavior you cannot infer from them. "
    "Reproduce each class_name and method signature exactly as given, so they can "
    "be matched back to the source. If a class has no notable design pattern, "
    "security-relevant logic, or complexity concern, return an empty notable_aspects "
    "list rather than inventing one."
)

_OVERVIEW_SYSTEM_PROMPT = (
    "You are summarizing a software project for a technical audience, given its "
    "README, its build dependencies, and a list of its classes' one-line purposes. "
    "Produce a clear, accurate high-level overview grounded strictly in the "
    "material given -- do not speculate about functionality not evidenced there."
)


@dataclass
class UsageTracker:
    """Accumulates token usage across every LLM call made during one run."""

    model: str
    calls_made: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def record(self, input_tokens: int, output_tokens: int) -> None:
        """Add one call's usage to the running totals."""
        self.calls_made += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        """Approximate USD cost of every call recorded so far."""
        input_price, output_price = _PRICING_USD_PER_MILLION_TOKENS.get(self.model, _DEFAULT_PRICING)
        return (self.input_tokens / 1_000_000) * input_price + (self.output_tokens / 1_000_000) * output_price


class LLMClient:
    """Wraps a LangChain `ChatAnthropic` instance with the two
    structured-output extraction operations this pipeline needs.
    """

    def __init__(self, *, api_key: str, model: str, usage_tracker: UsageTracker) -> None:
        # max_retries covers transient 429/5xx failures automatically (SDK
        # default backoff); anything that still fails is surfaced as
        # LLMExtractionError by `_invoke` below, not raised raw.
        # Note: ChatAnthropic's pydantic fields are `model`/`anthropic_api_key`,
        # but their declared aliases -- `model_name`/`api_key` -- are what its
        # constructor actually expects.
        self._chat = ChatAnthropic(
            model_name=model, api_key=SecretStr(api_key), timeout=120.0, max_retries=2, stop=None
        )
        self._batch_chain = self._chat.with_structured_output(ClassBatchAnalysis, include_raw=True)
        self._overview_chain = self._chat.with_structured_output(ProjectOverview, include_raw=True)
        self._usage = usage_tracker

    def analyze_batch(self, prompt_text: str) -> ClassBatchAnalysis:
        """Send one batch of condensed class text to the LLM and return its
        structured per-class analysis.

        Raises:
            LLMExtractionError: if the call fails after the SDK's own
                retries, or the response fails schema validation.
        """
        messages = [("system", _BATCH_SYSTEM_PROMPT), ("human", prompt_text)]
        result: ClassBatchAnalysis = self._invoke(self._batch_chain, messages)
        return result

    def generate_overview(self, prompt_text: str) -> ProjectOverview:
        """Produce the single, project-wide overview from README content,
        parsed build dependencies, and aggregated per-class one-line purposes.
        """
        messages = [("system", _OVERVIEW_SYSTEM_PROMPT), ("human", prompt_text)]
        result: ProjectOverview = self._invoke(self._overview_chain, messages)
        return result

    def _invoke(self, chain: Any, messages: list[tuple[str, str]]) -> Any:
        try:
            result = chain.invoke(messages)
        except Exception as exc:  # SDK-level failure: network, auth, retries exhausted
            raise LLMExtractionError(f"LLM call failed: {exc}") from exc

        raw_message = result.get("raw")
        usage = getattr(raw_message, "usage_metadata", None) if raw_message is not None else None
        if usage:
            self._usage.record(usage.get("input_tokens", 0), usage.get("output_tokens", 0))

        parsed = result.get("parsed")
        if parsed is None:
            raise LLMExtractionError(
                f"LLM response failed schema validation: {result.get('parsing_error')}"
            )
        return parsed
