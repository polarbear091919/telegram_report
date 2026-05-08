"""llm_extract node: single OpenAI structured-output call."""
from __future__ import annotations

from openai import APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError
from pydantic import ValidationError

from langgraph_tagger.llm_schemas import LLMExtraction
from langgraph_tagger.prompts import SYSTEM_PROMPT, user_message
from langgraph_tagger.state import RowState


class OpenAITransientError(Exception):
    """Wraps 429/5xx/timeout from OpenAI; orchestrator reverts row to pending."""


async def llm_extract(state: RowState, *, client: AsyncOpenAI) -> dict:
    if state.get("pdf_unreadable"):
        # Short-circuit: don't burn an LLM call on unreadable input
        return {"llm_raw": None}

    sent_at = state["sent_at"]
    sent_iso = sent_at.isoformat() if sent_at else ""

    try:
        completion = await client.chat.completions.parse(
            model=state["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message(
                    file_name=state["file_name"],
                    caption=state.get("caption"),
                    sent_at_iso=sent_iso,
                    pdf_text=state["pdf_text"],
                )},
            ],
            response_format=LLMExtraction,
            temperature=0,
        )
    except (RateLimitError, APITimeoutError, InternalServerError, ValidationError) as e:
        raise OpenAITransientError(str(e)) from e

    msg = completion.choices[0].message
    if msg.refusal:
        return {"llm_raw": None, "llm_refusal": msg.refusal}
    return {"llm_raw": msg.parsed}
