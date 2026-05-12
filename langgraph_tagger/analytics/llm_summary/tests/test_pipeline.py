from langgraph_tagger.analytics.llm_summary.pipeline import (
    normalize_target_price_dir,
)
from langgraph_tagger.analytics.llm_summary.schemas import ExtractionResult


def _make(new=None, old=None, dir_='N/A'):
    return ExtractionResult(
        target_price_new=new, target_price_old=old,
        target_price_dir=dir_, recommendation='매수',
        recommendation_dir='유지', one_line_summary='X',
        positive_points=[], risk_points=[],
        target_price_raw='8만원' if new else None,
        recommendation_raw='Buy',
        source_pages=[1] if new else [],
        extraction_confidence='high',
    )


def test_normalize_both_int_higher_overrides_to_상향():
    r = _make(new=85000, old=70000, dir_='불변')  # LLM이 틀려도
    out = normalize_target_price_dir(r)
    assert out.target_price_dir == '상향'


def test_normalize_both_int_lower_overrides_to_하향():
    r = _make(new=60000, old=70000, dir_='상향')  # LLM이 틀려도
    out = normalize_target_price_dir(r)
    assert out.target_price_dir == '하향'


def test_normalize_both_int_equal_overrides_to_불변():
    r = _make(new=70000, old=70000, dir_='상향')
    out = normalize_target_price_dir(r)
    assert out.target_price_dir == '불변'


def test_normalize_only_new_keeps_llm_judgment():
    r = _make(new=85000, old=None, dir_='신규')
    out = normalize_target_price_dir(r)
    assert out.target_price_dir == '신규'  # LLM 판단 유지


def test_normalize_neither_forces_NA():
    r = _make(new=None, old=None, dir_='상향')  # LLM 잘못 추출
    out = normalize_target_price_dir(r)
    assert out.target_price_dir == 'N/A'


from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from langgraph_tagger.analytics.llm_summary import pipeline
from langgraph_tagger.analytics.llm_summary.config import LLMSummaryConfig
from langgraph_tagger.analytics.llm_summary.schemas import ExtractionResult


@pytest.fixture
def cfg():
    """Test config with mock OpenAI key — passed explicitly to analyze_stock."""
    return LLMSummaryConfig(
        openai_model='gpt-5.4-mini', max_concurrent=2,
        per_report_timeout_s=10, max_input_tokens=10000,
        summary_version='llm-summary@1.0',
        supabase_db_url='postgres://test',
        openai_api_key='sk-test-mock',
    )


@pytest.fixture
def fake_pool(monkeypatch):
    """Replace pipeline.open_pool with a no-op asynccontextmanager."""
    @asynccontextmanager
    async def _ctx(*a, **k):
        yield MagicMock()
    monkeypatch.setattr(pipeline, 'open_pool', _ctx)


class FakeAnalyticsDB:
    def __init__(self, df: pd.DataFrame, sb=None):
        self._df = df
        self._sb = sb
    def fetch_stock_rows(self, code, period_start_iso):
        return self._df.copy()


def _make_row(id_, report_type='단일종목', file_path='reports/x.pdf'):
    return {
        'id': id_, 'report_type': report_type,
        'publisher': '삼성증권', 'published_at': '2026-05-05',
        'stock_codes': ['005930'], 'file_path': file_path,
        'tagging_status': 'auto', 'out_of_scope_reason': None,
        'title': 'Test', 'sent_at': '2026-05-05T00:00:00+00:00',
    }


@pytest.fixture
def mock_llm_extract(monkeypatch):
    """extract_one mock returning a valid result."""
    async def _fake(*args, **kwargs):
        return (ExtractionResult(
            target_price_new=85000, target_price_old=70000,
            target_price_dir='상향', recommendation='매수',
            recommendation_dir='유지', one_line_summary='X',
            positive_points=['p'], risk_points=['r'],
            target_price_raw='8.5만원', recommendation_raw='Buy',
            source_pages=[1], extraction_confidence='high',
        ), 1000, 200)
    monkeypatch.setattr(pipeline, 'extract_one_safe', _fake)


@pytest.mark.asyncio
async def test_pass1_cache_hit_skips_llm(mock_llm_extract, fake_pool, cfg, tmp_path):
    """cache hit + diff already done이면 LLM 호출 0."""
    df = pd.DataFrame([_make_row(1)])
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
        {'report_id': 1, 'summary_version': 'llm-summary@1.0',
         'prev_match_type': 'same_publisher',
         'publisher': '삼성증권', 'stock_codes': ['005930'],
         'published_at': '2026-05-05'},
    ]
    adb = FakeAnalyticsDB(df, sb)

    cards = await pipeline.analyze_stock(
        analytics_db=adb, storage_base_dir=tmp_path,
        stock_code='005930', period_start_iso='2026-01-01',
        progress_cb=lambda *a, **k: None, cfg=cfg,
    )
    assert len(cards) == 1


@pytest.mark.asyncio
async def test_pass1_filters_non_단일종목(mock_llm_extract, fake_pool, cfg,
                                          monkeypatch, tmp_path):
    df = pd.DataFrame([_make_row(1, report_type='산업'),
                       _make_row(2, report_type='단일종목')])
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.eq.return_value.execute.return_value.data = []
    adb = FakeAnalyticsDB(df, sb)

    monkeypatch.setattr(pipeline, 'find_prev_for_diff_safe',
                        AsyncMock(return_value=None))
    upsert_calls = []
    monkeypatch.setattr(pipeline, '_call_summary_store_upsert',
                        lambda sb, payload: upsert_calls.append(payload))
    monkeypatch.setattr(pipeline, '_call_summary_store_update_diff',
                        lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'extract_pdf_pages',
                        lambda *a, **k: ('text', 1, 1, False))

    cards = await pipeline.analyze_stock(
        analytics_db=adb, storage_base_dir=tmp_path,
        stock_code='005930', period_start_iso='2026-01-01',
        progress_cb=lambda *a, **k: None, cfg=cfg,
    )
    # 단일종목만 LLM extract됨 — upsert는 id=2에 대해서만
    upserted_ids = [p['report_id'] for p in upsert_calls]
    assert upserted_ids == [2]
