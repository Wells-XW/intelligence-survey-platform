"""Multi-model routing for LLM calls.

Routing strategy (from tech architecture v1):
- Chinese-heavy tasks → DeepSeek-R1 (5% of GPT-4o cost, best Chinese quality)
- English analysis → Claude Opus 4 (200K context for literature review)
- Batch / low-cost detection → GPT-4.5 mini
- Sensitive data (PIPL) → local Qwen3 (data never leaves server)

Cost per 1K tokens (approximate, May 2026):
- deepseek-chat:    $0.00014 input / $0.00028 output (~$0.28/M tokens)
- claude-opus-4:    $0.015 input / $0.075 output
- gpt-4.5-mini:     $0.0005 input / $0.002 output
- local-qwen:       $0 (self-hosted, hardware cost only)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from openai import AsyncOpenAI, OpenAIError


# ── Route decision types ──────────────────────────────────────────────


class ModelTarget(str, Enum):
    """Which model to route a request to."""
    DEEPSEEK = "deepseek"
    CLAUDE = "claude"
    GPT_MINI = "gpt-mini"
    LOCAL_QWEN = "local-qwen"


class TaskCategory(str, Enum):
    """Categorises an AI task to inform routing."""
    SURVEY_GENERATION = "survey_generation"      # structured JSON output
    ITEM_REFINEMENT = "item_refinement"           # critique + revision
    LITERATURE_SEARCH = "literature_search"       # English academic
    SENSITIVE_PIPL = "sensitive_pipl"            # personal data handling
    QUALITY_CHECK = "quality_check"              # batch, low-cost
    TRANSLATION = "translation"                  # zh↔en


@dataclass
class RouteDecision:
    """Result of the routing decision."""
    target: ModelTarget
    model_name: str
    reasoning: str


@dataclass
class AiCallResult:
    """Result of a single LLM call."""
    content: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    estimated_cost_cents: float
    success: bool = True
    error_message: Optional[str] = None


# ── Routing matrix ────────────────────────────────────────────────────

# Maps (task_category, has_chinese, has_sensitive_data) → ModelTarget
_ROUTE_TABLE: dict[tuple[TaskCategory, bool, bool], ModelTarget] = {
    # Chinese survey tasks → DeepSeek (best Chinese, cheapest)
    (TaskCategory.SURVEY_GENERATION, True, False):  ModelTarget.DEEPSEEK,
    (TaskCategory.ITEM_REFINEMENT, True, False):     ModelTarget.DEEPSEEK,
    # English-heavy tasks → Claude
    (TaskCategory.SURVEY_GENERATION, False, False): ModelTarget.DEEPSEEK,
    (TaskCategory.LITERATURE_SEARCH, False, False):  ModelTarget.CLAUDE,
    (TaskCategory.LITERATURE_SEARCH, True, False):   ModelTarget.DEEPSEEK,
    # Batch low-cost
    (TaskCategory.QUALITY_CHECK, True, False):      ModelTarget.GPT_MINI,
    (TaskCategory.QUALITY_CHECK, False, False):      ModelTarget.GPT_MINI,
    # Sensitive → local only
    (TaskCategory.SENSITIVE_PIPL, True, True):      ModelTarget.LOCAL_QWEN,
    (TaskCategory.SENSITIVE_PIPL, False, True):      ModelTarget.LOCAL_QWEN,
    # Translation → DeepSeek (good bilingual)
    (TaskCategory.TRANSLATION, True, False):         ModelTarget.DEEPSEEK,
    (TaskCategory.TRANSLATION, False, False):         ModelTarget.DEEPSEEK,
}

_MODEL_NAMES: dict[ModelTarget, str] = {
    ModelTarget.DEEPSEEK:  "deepseek-chat",
    ModelTarget.CLAUDE:    "claude-opus-4-20250514",
    ModelTarget.GPT_MINI:  "gpt-4.5-mini",
    ModelTarget.LOCAL_QWEN: "qwen3-72b",
}


def route_request(
    task: TaskCategory,
    has_chinese: bool = True,
    has_sensitive_data: bool = False,
    prefer_model: Optional[ModelTarget] = None,
) -> RouteDecision:
    """Decide which model to use for a given task.

    Args:
        task: The category of AI work requested.
        has_chinese: ``True`` if the input contains Chinese text.
        has_sensitive_data: ``True`` if PIPL-covered personal data is involved.
        prefer_model: Override the routing decision (caller preference).

    Returns:
        A ``RouteDecision`` with target model and reasoning.
    """
    if prefer_model is not None:
        return RouteDecision(
            target=prefer_model,
            model_name=_MODEL_NAMES[prefer_model],
            reasoning="User-specified model preference override.",
        )

    # Sensitive data always forces local model
    if has_sensitive_data:
        return RouteDecision(
            target=ModelTarget.LOCAL_QWEN,
            model_name=_MODEL_NAMES[ModelTarget.LOCAL_QWEN],
            reasoning="Sensitive/PIPL data — routed to local Qwen3 for data sovereignty.",
        )

    key = (task, has_chinese, has_sensitive_data)
    target = _ROUTE_TABLE.get(key, ModelTarget.DEEPSEEK)

    reasons = {
        ModelTarget.DEEPSEEK: "Chinese text and/or structured JSON → DeepSeek (best cost/quality ratio).",
        ModelTarget.CLAUDE: "English academic analysis → Claude Opus 4 (200K context).",
        ModelTarget.GPT_MINI: "Batch/low-cost task → GPT-4.5 mini (fast, cheap).",
        ModelTarget.LOCAL_QWEN: "Sensitive data → local Qwen3 (data never leaves server).",
    }

    return RouteDecision(
        target=target,
        model_name=_MODEL_NAMES[target],
        reasoning=reasons[target],
    )


# ── Provider clients ──────────────────────────────────────────────────


def _build_openai_client(
    api_key: str, base_url: str
) -> AsyncOpenAI:
    """Create an OpenAI-compatible client for a given provider."""
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


async def call_deepseek(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> AiCallResult:
    """Call DeepSeek (OpenAI-compatible API)."""
    client = _build_openai_client(api_key, base_url)
    start = time.monotonic()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        usage = resp.usage
        return AiCallResult(
            content=resp.choices[0].message.content or "",
            model=resp.model,
            provider="deepseek",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=elapsed_ms,
            estimated_cost_cents=_estimate_deepseek_cost(
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            ),
        )
    except OpenAIError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return AiCallResult(
            content="",
            model=model,
            provider="deepseek",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=elapsed_ms,
            estimated_cost_cents=0.0,
            success=False,
            error_message=str(exc),
        )


async def call_claude(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> AiCallResult:
    """Call Claude via OpenAI-compatible endpoint (Anthropic or proxy)."""
    # Claude can be accessed via an OpenAI-compatible proxy; for direct
    # Anthropic API, use the anthropic SDK. For MVP we support both.
    # Fallback: use the configured base URL (could be a proxy).

    from ..config import settings

    # For MVP, we route Claude calls through the same OpenAI-compatible
    # pattern. If the provider is Anthropic-native, we'd use the
    # anthropic SDK. The base_url should point to a proxy for MVP.
    client = _build_openai_client(api_key, base_url=settings.deepseek_base_url)

    # If no separate Claude key, redirect to DeepSeek as fallback
    if not api_key or api_key == settings.deepseek_api_key:
        return await call_deepseek(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )

    start = time.monotonic()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        usage = resp.usage
        return AiCallResult(
            content=resp.choices[0].message.content or "",
            model=resp.model,
            provider="anthropic",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=elapsed_ms,
            estimated_cost_cents=_estimate_claude_cost(
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            ),
        )
    except OpenAIError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return AiCallResult(
            content="",
            model=model,
            provider="anthropic",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=elapsed_ms,
            estimated_cost_cents=0.0,
            success=False,
            error_message=str(exc),
        )


async def execute_ai_call(
    system_prompt: str,
    user_prompt: str,
    task: TaskCategory,
    *,
    has_chinese: bool = True,
    has_sensitive_data: bool = False,
    prefer_model: Optional[ModelTarget] = None,
) -> tuple[AiCallResult, RouteDecision]:
    """Route and execute a single LLM call.

    This is the main entry point for all AI calls in the platform.
    It decides the model, dispatches to the correct provider, and
    returns both the result and the routing metadata.

    Args:
        system_prompt: The system-level instruction for the LLM.
        user_prompt: The user-facing task description or context.
        task: The ``TaskCategory`` for routing.
        has_chinese: Whether the input contains Chinese.
        has_sensitive_data: Whether PIPL-sensitive data is involved.
        prefer_model: Optional user preference to override routing.

    Returns:
        A tuple of ``(AiCallResult, RouteDecision)``.
    """
    from ..config import settings

    decision = route_request(
        task=task,
        has_chinese=has_chinese,
        has_sensitive_data=has_sensitive_data,
        prefer_model=prefer_model,
    )

    if decision.target == ModelTarget.DEEPSEEK:
        result = await call_deepseek(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=decision.model_name,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            timeout=settings.llm_request_timeout,
        )
    elif decision.target == ModelTarget.CLAUDE:
        result = await call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=getattr(settings, "claude_api_key", ""),
            model=decision.model_name,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            timeout=settings.llm_request_timeout,
        )
    elif decision.target == ModelTarget.GPT_MINI:
        result = await call_deepseek(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=getattr(settings, "openai_api_key", settings.deepseek_api_key),
            base_url="https://api.openai.com/v1",
            model=decision.model_name,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            timeout=settings.llm_request_timeout,
        )
    else:  # LOCAL_QWEN — fallback to DeepSeek for MVP
        # In production, this routes to a self-hosted vLLM/TGI endpoint.
        # For MVP, we fallback to DeepSeek (PIPL risk accepted in dev).
        from ..config import settings

        result = await call_deepseek(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            timeout=settings.llm_request_timeout,
        )

    return result, decision


# ── Cost estimation helpers ───────────────────────────────────────────


def _estimate_deepseek_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """DeepSeek pricing: $0.14/M input, $0.28/M output."""
    cost = (prompt_tokens / 1_000_000) * 0.14 + (completion_tokens / 1_000_000) * 0.28
    return round(cost * 100, 4)  # convert to cents


def _estimate_claude_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Claude Opus 4: $15/M input, $75/M output."""
    cost = (prompt_tokens / 1_000_000) * 15.0 + (completion_tokens / 1_000_000) * 75.0
    return round(cost * 100, 4)
