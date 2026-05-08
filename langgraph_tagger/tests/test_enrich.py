from datetime import date, datetime, timezone

import pytest

from langgraph_tagger.nodes.enrich import enrich, KST
from langgraph_tagger.tests.conftest import make_llm_extraction


@pytest.fixture
def kst_dt():
    """A UTC datetime that is 2026-05-08 in KST (utc 15:00 → 00:00 next day KST)."""
    return datetime(2026, 5, 7, 15, 0, tzinfo=timezone.utc)


def test_single_stock_auto_enrichment(krx, kst_dt):
    """단일종목 + KRX 매칭 → company_names/sectors/products auto-merge."""
    state = {
        "llm_raw": make_llm_extraction(
            report_type="단일종목",
            stock_codes_raw=["005930"],
            company_names=[],         # LLM didn't extract — code fills from KRX
            sectors_major=[],
            sectors_minor=[],
            products=[],
            published_at=None,
        ),
        "stock_codes_valid": ["005930"],
        "sectors_major_valid": [],
        "sectors_minor_valid": [],
        "products_valid": [],
        "products_unknown": [],
        "sent_at": kst_dt,
    }
    out = enrich(state, krx=krx)
    # company_names auto-filled from KRX
    assert "삼성전자" in out["company_names_final"]
    # sectors auto-filled (depth: products → minor → major)
    assert "반도체" in out["sectors_major_final"]
    assert "메모리반도체" in out["sectors_minor_final"]
    # published_at fell back to sent_at in KST
    assert out["published_at_final"] == date(2026, 5, 8)
    assert out["used_sent_at_fallback"] is True


def test_industry_no_auto_enrichment(krx, kst_dt):
    state = {
        "llm_raw": make_llm_extraction(
            report_type="산업",
            stock_codes_raw=[],
            company_names=[],
            sectors_major=["반도체"],
            sectors_minor=[],
            products=[],
            published_at="2026-05-01",
        ),
        "stock_codes_valid": [],
        "sectors_major_valid": ["반도체"],
        "sectors_minor_valid": [],
        "products_valid": [],
        "products_unknown": [],
        "sent_at": kst_dt,
    }
    out = enrich(state, krx=krx)
    assert out["company_names_final"] == []
    assert out["sectors_major_final"] == ["반도체"]
    assert out["used_sent_at_fallback"] is False
    assert out["published_at_final"] == date(2026, 5, 1)


def test_enrich_uses_products_valid_only(krx, kst_dt):
    """enrich gets products from validate's products_valid (already filtered).
    Unknown products are NOT silently dropped — they live in products_unknown
    and decide_status maps them to review_needed/low (spec §6.6).
    """
    state = {
        "llm_raw": make_llm_extraction(
            report_type="단일종목",
            stock_codes_raw=[],
            company_names=["KT&G"],
            sectors_major=[], sectors_minor=[],
            products=["DRAM", "완전이상한제품"],
            published_at="2026-05-01",
        ),
        "stock_codes_valid": [],
        "sectors_major_valid": [],
        "sectors_minor_valid": [],
        "products_valid": ["DRAM"],          # validate already split
        "products_unknown": ["완전이상한제품"],
        "sent_at": kst_dt,
    }
    out = enrich(state, krx=krx)
    # Only validated products survive into products_final; enrichment may add
    # KRX-matched tokens via single-stock rule (none here since stock_codes_valid is empty).
    assert "DRAM" in out["products_final"]
    assert "완전이상한제품" not in out["products_final"]


def test_minor_to_major_rollup(krx, kst_dt):
    """sectors_minor='메모리반도체' → sectors_major='반도체' auto-merge."""
    state = {
        "llm_raw": make_llm_extraction(
            report_type="섹터",
            stock_codes_raw=[],
            company_names=[],
            sectors_major=[],
            sectors_minor=["메모리반도체"],
            products=[],
            published_at="2026-05-01",
        ),
        "stock_codes_valid": [],
        "sectors_major_valid": [],
        "sectors_minor_valid": ["메모리반도체"],
        "products_valid": [],
        "products_unknown": [],
        "sent_at": kst_dt,
    }
    out = enrich(state, krx=krx)
    assert "반도체" in out["sectors_major_final"]
    assert "메모리반도체" in out["sectors_minor_final"]
