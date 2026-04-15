"""Usage tracking and cost estimation."""

from __future__ import annotations

from dataclasses import dataclass

from fool_code.types import Session, TokenUsage

DEFAULT_INPUT_COST_PER_MILLION = 15.0
DEFAULT_OUTPUT_COST_PER_MILLION = 75.0
DEFAULT_CACHE_CREATION_COST_PER_MILLION = 18.75
DEFAULT_CACHE_READ_COST_PER_MILLION = 1.5


@dataclass
class ModelPricing:
    input_cost_per_million: float
    output_cost_per_million: float
    cache_creation_cost_per_million: float
    cache_read_cost_per_million: float

    @staticmethod
    def default_sonnet_tier() -> ModelPricing:
        return ModelPricing(
            input_cost_per_million=DEFAULT_INPUT_COST_PER_MILLION,
            output_cost_per_million=DEFAULT_OUTPUT_COST_PER_MILLION,
            cache_creation_cost_per_million=DEFAULT_CACHE_CREATION_COST_PER_MILLION,
            cache_read_cost_per_million=DEFAULT_CACHE_READ_COST_PER_MILLION,
        )


@dataclass
class UsageCostEstimate:
    input_cost_usd: float
    output_cost_usd: float
    cache_creation_cost_usd: float
    cache_read_cost_usd: float

    @property
    def total_cost_usd(self) -> float:
        return (
            self.input_cost_usd
            + self.output_cost_usd
            + self.cache_creation_cost_usd
            + self.cache_read_cost_usd
        )


def pricing_for_model(model: str) -> ModelPricing | None:
    normalized = model.lower()
    if "haiku" in normalized:
        return ModelPricing(1.0, 5.0, 1.25, 0.1)
    if "opus" in normalized:
        return ModelPricing(15.0, 75.0, 18.75, 1.5)
    if "sonnet" in normalized:
        return ModelPricing.default_sonnet_tier()
    return None


def estimate_cost(usage: TokenUsage, pricing: ModelPricing | None = None) -> UsageCostEstimate:
    p = pricing or ModelPricing.default_sonnet_tier()
    return UsageCostEstimate(
        input_cost_usd=_cost(usage.input_tokens, p.input_cost_per_million),
        output_cost_usd=_cost(usage.output_tokens, p.output_cost_per_million),
        cache_creation_cost_usd=_cost(
            usage.cache_creation_input_tokens, p.cache_creation_cost_per_million
        ),
        cache_read_cost_usd=_cost(
            usage.cache_read_input_tokens, p.cache_read_cost_per_million
        ),
    )


def format_usd(amount: float) -> str:
    return f"${amount:.4f}"


def _cost(tokens: int, usd_per_million: float) -> float:
    return tokens / 1_000_000.0 * usd_per_million


class UsageTracker:
    def __init__(self) -> None:
        self._latest_turn = TokenUsage()
        self._cumulative = TokenUsage()
        self._turns = 0

    @staticmethod
    def from_session(session: Session) -> UsageTracker:
        tracker = UsageTracker()
        for msg in session.messages:
            if msg.usage is not None:
                tracker.record(msg.usage)
        return tracker

    def record(self, usage: TokenUsage) -> None:
        self._latest_turn = usage
        self._cumulative.input_tokens += usage.input_tokens
        self._cumulative.output_tokens += usage.output_tokens
        self._cumulative.cache_creation_input_tokens += usage.cache_creation_input_tokens
        self._cumulative.cache_read_input_tokens += usage.cache_read_input_tokens
        self._turns += 1

    @property
    def current_turn_usage(self) -> TokenUsage:
        return self._latest_turn

    @property
    def cumulative_usage(self) -> TokenUsage:
        return self._cumulative

    @property
    def turns(self) -> int:
        return self._turns

    def summary_lines(self, label: str, model: str | None = None) -> list[str]:
        pricing = pricing_for_model(model) if model else None
        cost = estimate_cost(self._cumulative, pricing)
        total = self._cumulative.total_tokens()
        model_suffix = f" model={model}" if model else ""
        pricing_suffix = ""
        if model and pricing is None:
            pricing_suffix = " pricing=estimated-default"
        return [
            (
                f"{label}: total_tokens={total}"
                f" input={self._cumulative.input_tokens}"
                f" output={self._cumulative.output_tokens}"
                f" cache_write={self._cumulative.cache_creation_input_tokens}"
                f" cache_read={self._cumulative.cache_read_input_tokens}"
                f" estimated_cost={format_usd(cost.total_cost_usd)}"
                f"{model_suffix}{pricing_suffix}"
            ),
            (
                f"  cost breakdown:"
                f" input={format_usd(cost.input_cost_usd)}"
                f" output={format_usd(cost.output_cost_usd)}"
                f" cache_write={format_usd(cost.cache_creation_cost_usd)}"
                f" cache_read={format_usd(cost.cache_read_cost_usd)}"
            ),
        ]
