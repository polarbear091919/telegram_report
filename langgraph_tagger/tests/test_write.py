from datetime import date, datetime, timezone

import pytest

from langgraph_tagger.nodes.write import write
from langgraph_tagger.supabase_io import UPDATE_SQL
from langgraph_tagger.tests.conftest import make_llm_extraction


def _in_scope_state():
    return {
        "id": 100,
        "model": "gpt-5.4-mini",
        "is_oos": False,
        "llm_raw": make_llm_extraction(),
        "publisher_canon": "키움증권",
        "publisher_type": "broker",
        "topics_canon": ["AI수혜"],
        "stock_codes_valid": ["005930"],
        "company_names_final": ["삼성전자"],
        "sectors_major_final": ["반도체"],
        "sectors_minor_final": ["메모리반도체"],
        "products_final": ["DRAM"],
        "published_at_final": date(2026, 5, 1),
        "tagging_status": "auto",
        "tagging_confidence": "high",
        "tagging_notes": None,
    }


@pytest.mark.asyncio
async def test_in_scope_write_calls_update(mock_supabase):
    state = _in_scope_state()
    await write(state, sb=mock_supabase, dry_run=False, taxonomy_version="KRX@2026-05-08")
    assert len(mock_supabase.executed) == 1
    sql, args = mock_supabase.executed[0]
    assert sql == UPDATE_SQL
    # id is first arg
    assert args[0] == 100
    # report_type from llm_raw (not 기타)
    assert args[2] == "단일종목"
    # publisher canonical
    assert args[3] == "키움증권"


@pytest.mark.asyncio
async def test_dry_run_does_not_write(mock_supabase):
    state = _in_scope_state()
    await write(state, sb=mock_supabase, dry_run=True, taxonomy_version="KRX@2026-05-08")
    assert mock_supabase.executed == []


@pytest.mark.asyncio
async def test_oos_write_overrides_to_etc_and_empties_meta(mock_supabase):
    state = _in_scope_state()
    state.update({
        "is_oos": True,
        "oos_reason": "foreign",
        "tagging_confidence": "high",
    })
    await write(state, sb=mock_supabase, dry_run=False, taxonomy_version="KRX@2026-05-08")
    sql, args = mock_supabase.executed[0]
    assert args[2] == "기타"           # report_type forced
    assert args[13] == "foreign"        # out_of_scope_reason
    assert args[7] == []                # stock_codes empty
    assert args[8] == []                # company_names empty


@pytest.mark.asyncio
async def test_unreadable_write_has_null_report_type(mock_supabase):
    state = _in_scope_state()
    state.update({
        "is_oos": False,
        "tagging_status": "review_needed",
        "tagging_confidence": "low",
        "tagging_notes": "first_page_unreadable",
        "llm_raw": None,   # llm never returned anything usable
    })
    await write(state, sb=mock_supabase, dry_run=False, taxonomy_version="KRX@2026-05-08")
    sql, args = mock_supabase.executed[0]
    assert args[2] is None              # report_type NULL
    assert args[14] == "review_needed"
