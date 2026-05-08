"""Shared test fixtures for langgraph_tagger."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from langgraph_tagger.llm_schemas import LLMExtraction, OOSSignals
from langgraph_tagger.vocabulary.krx import KRXIndex


@pytest.fixture(scope="session")
def krx() -> KRXIndex:
    """Real KRX index loaded once per session."""
    return KRXIndex.load(Path("docs/stock_data/KRX_stocks_data.csv"))


@pytest.fixture
def mock_openai_client():
    """AsyncMock that returns a configurable LLMExtraction.

    Usage:
        mock_openai_client.set_response(LLMExtraction(...))
        # or
        mock_openai_client.set_refusal("policy violation")
        # or
        from openai import RateLimitError
        mock_openai_client.set_exception(RateLimitError("rate limited"))
    """
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    parse = AsyncMock()
    client.chat.completions.parse = parse

    def _set_response(parsed: LLMExtraction):
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.parsed = parsed
        completion.choices[0].message.refusal = None
        parse.return_value = completion

    def _set_refusal(reason: str):
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.parsed = None
        completion.choices[0].message.refusal = reason
        parse.return_value = completion

    def _set_exception(exc: Exception):
        parse.side_effect = exc

    client.set_response = _set_response
    client.set_refusal = _set_refusal
    client.set_exception = _set_exception
    return client


def make_llm_extraction(**overrides) -> LLMExtraction:
    """Factory for tests — sane defaults overridable per test."""
    defaults = dict(
        report_type="단일종목",
        title="삼성전자 1Q26 Preview",
        published_at="2026-05-01",
        stock_codes_raw=["005930"],
        company_names=["삼성전자"],
        sectors_major=["반도체"],
        sectors_minor=["메모리반도체"],
        products=["DRAM", "NAND"],
        publisher_raw="키움증권",
        analysts=["홍길동"],
        topics=["AI수혜"],
        oos_signals=OOSSignals(
            foreign_primary_coverage=False, etf_or_fund=False,
            digital_asset=False, private_company_likely=False,
        ),
        self_confidence="high",
        notes=None,
    )
    defaults.update(overrides)
    return LLMExtraction(**defaults)
