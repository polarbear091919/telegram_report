"""OpenAI async wrapper — extract_one + diff_one + transient 재시도 1회.

structured outputs (response_format=json_schema) 강제로 schema 준수 강제.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from openai import APIConnectionError, APITimeoutError, RateLimitError, APIError

from langgraph_tagger.analytics.llm_summary.prompts import (
    render_extraction_messages, render_diff_messages,
)
from langgraph_tagger.analytics.llm_summary.schemas import (
    ExtractionResult, DiffResult,
)

logger = logging.getLogger(__name__)


class TransientLLMError(RuntimeError):
    """429 / timeout / connection — 재시도 가능."""


_TRANSIENT_TYPES = (
    APIConnectionError, APITimeoutError, RateLimitError, TransientLLMError,
)


async def _call_with_retry(coro_factory, backoff_s: float):
    try:
        return await coro_factory()
    except _TRANSIENT_TYPES as e:
        logger.warning("LLM transient error, retrying in %ss: %s", backoff_s, e)
        await asyncio.sleep(backoff_s)
        try:
            return await coro_factory()
        except _TRANSIENT_TYPES as e2:
            logger.error("LLM transient retry exhausted: %s", e2)
            raise TransientLLMError(str(e2)) from e2


async def extract_one(
    *,
    client,                       # openai.AsyncOpenAI
    model: str,
    metadata: dict[str, Any],
    pages_text: str,
    timeout_s: int,
    backoff_s: float = 5.0,
) -> tuple[ExtractionResult, int, int]:
    """ExtractionResult + (input_tokens, output_tokens) 반환."""
    messages = render_extraction_messages(metadata, pages_text)

    async def _call():
        return await asyncio.wait_for(
            client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=ExtractionResult,
            ),
            timeout=timeout_s,
        )

    resp = await _call_with_retry(_call, backoff_s)
    parsed: ExtractionResult = resp.choices[0].message.parsed
    in_t = getattr(resp.usage, 'prompt_tokens', 0) or 0
    out_t = getattr(resp.usage, 'completion_tokens', 0) or 0
    return parsed, in_t, out_t


async def diff_one(
    *,
    client,
    model: str,
    prev_summary: dict[str, Any],
    curr_summary: dict[str, Any],
    prev_match_type: Literal['same_publisher', 'cross_publisher'],
    prev_report_id: int,
    prev_publisher: str,
    curr_publisher: str,
    timeout_s: int,
    backoff_s: float = 5.0,
) -> tuple[DiffResult, int, int]:
    messages = render_diff_messages(
        prev_summary, curr_summary, prev_match_type,
        prev_report_id, prev_publisher, curr_publisher,
    )

    async def _call():
        return await asyncio.wait_for(
            client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=DiffResult,
            ),
            timeout=timeout_s,
        )

    resp = await _call_with_retry(_call, backoff_s)
    parsed: DiffResult = resp.choices[0].message.parsed
    in_t = getattr(resp.usage, 'prompt_tokens', 0) or 0
    out_t = getattr(resp.usage, 'completion_tokens', 0) or 0
    return parsed, in_t, out_t
