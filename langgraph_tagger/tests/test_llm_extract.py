"""Tests for llm_extract node (mocked OpenAI)."""
from __future__ import annotations

import httpx
import pytest
from openai import APITimeoutError, InternalServerError, RateLimitError

from langgraph_tagger.nodes.llm_extract import llm_extract, OpenAITransientError
from langgraph_tagger.tests.conftest import make_llm_extraction


def _httpx_response(status: int) -> httpx.Response:
    """openai 2.x requires the response to have its request set."""
    return httpx.Response(status, request=httpx.Request("POST", "http://x"))


@pytest.mark.asyncio
async def test_happy_path_returns_parsed(mock_openai_client):
    extraction = make_llm_extraction()
    mock_openai_client.set_response(extraction)

    state = {
        "model": "gpt-5.4-mini",
        "pdf_text": "샘플 텍스트",
        "file_name": "삼성전자_1Q26.pdf",
        "caption": None,
        "sent_at": __import__("datetime").datetime(2026, 5, 1, 9, 0),
    }
    out = await llm_extract(state, client=mock_openai_client)

    assert out["llm_raw"] == extraction
    assert "llm_refusal" not in out


@pytest.mark.asyncio
async def test_unreadable_short_circuits(mock_openai_client):
    state = {"pdf_unreadable": True}
    out = await llm_extract(state, client=mock_openai_client)
    assert out["llm_raw"] is None
    # parse should not have been called
    mock_openai_client.chat.completions.parse.assert_not_called()


@pytest.mark.asyncio
async def test_refusal_recorded(mock_openai_client):
    mock_openai_client.set_refusal("policy violation: x")
    state = {
        "model": "gpt-5.4-mini",
        "pdf_text": "샘플",
        "file_name": "x.pdf",
        "caption": None,
        "sent_at": __import__("datetime").datetime(2026, 5, 1, 9, 0),
    }
    out = await llm_extract(state, client=mock_openai_client)
    assert out["llm_raw"] is None
    assert out["llm_refusal"] == "policy violation: x"


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_factory", [
    lambda: RateLimitError("429", response=_httpx_response(429), body=None),
    lambda: APITimeoutError(request=httpx.Request("POST", "http://x")),
    lambda: InternalServerError("500", response=_httpx_response(500), body=None),
])
async def test_transient_errors_raise_OpenAITransientError(mock_openai_client, exc_factory):
    mock_openai_client.set_exception(exc_factory())
    state = {
        "model": "gpt-5.4-mini",
        "pdf_text": "x",
        "file_name": "x.pdf",
        "caption": None,
        "sent_at": __import__("datetime").datetime(2026, 5, 1, 9, 0),
    }
    with pytest.raises(OpenAITransientError):
        await llm_extract(state, client=mock_openai_client)
