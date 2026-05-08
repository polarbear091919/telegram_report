"""Exhaustive decide_status branches (spec §6.6) — no LLM, pure logic."""
import pytest

from langgraph_tagger.nodes.decide_status import decide_status
from langgraph_tagger.tests.conftest import make_llm_extraction


def _base_state(**kwargs):
    """All-success defaults; tests override specific keys to exercise branches."""
    s = {
        "pdf_unreadable": False,
        "llm_refusal": None,
        "llm_raw": make_llm_extraction(self_confidence="high"),
        "is_oos": False,
        "stock_codes_unknown": [],
        "sectors_unknown": [],
        "products_unknown": [],
        "topic_unmapped": [],
        "publisher_canon": "키움증권",
        "used_sent_at_fallback": False,
        "pages_used": [1],
    }
    s.update(kwargs)
    return s


# ── failure: gating ─────────────────────────────────────────────

def test_pdf_unreadable_yields_first_page_unreadable():
    out = decide_status(_base_state(pdf_unreadable=True))
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert out["tagging_notes"] == "first_page_unreadable"


def test_llm_refusal_yields_review_needed():
    out = decide_status(_base_state(llm_refusal="policy"))
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert out["tagging_notes"] == "llm_refusal:policy"


# ── failure: validation ─────────────────────────────────────────

def test_unknown_stock_code_yields_review_needed():
    out = decide_status(_base_state(stock_codes_unknown=["999999"]))
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert "unknown_stock_code:999999" in out["tagging_notes"]


def test_unknown_sector_yields_review_needed():
    out = decide_status(_base_state(sectors_unknown=["완전이상한산업"]))
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert "unknown_sector:완전이상한산업" in out["tagging_notes"]


def test_type_indeterminate_yields_review_needed():
    out = decide_status(_base_state(
        llm_raw=make_llm_extraction(report_type="기타", self_confidence="low"),
    ))
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert "type_indeterminate" in out["tagging_notes"]


# ── auto/high ───────────────────────────────────────────────────

def test_all_clean_yields_auto_high():
    out = decide_status(_base_state())
    assert out["tagging_status"] == "auto"
    assert out["tagging_confidence"] == "high"
    assert out["tagging_notes"] is None


# ── auto/medium (single fallback signals) ──────────────────────

def test_sent_at_fallback_yields_auto_medium():
    out = decide_status(_base_state(used_sent_at_fallback=True))
    assert out["tagging_status"] == "auto"
    assert out["tagging_confidence"] == "medium"


def test_topic_unmapped_yields_auto_medium():
    out = decide_status(_base_state(topic_unmapped=["새토픽"]))
    assert out["tagging_status"] == "auto"
    assert out["tagging_confidence"] == "medium"


def test_page_fallback_yields_auto_medium():
    out = decide_status(_base_state(pages_used=[1, 2]))
    assert out["tagging_status"] == "auto"
    assert out["tagging_confidence"] == "medium"


# ── failure: spec §6.6 elevated unknown_publisher / unknown_product ─

def test_unknown_publisher_yields_review_needed():
    """Spec 2026-05-07 §6.6: unknown_publisher → review_needed/low."""
    out = decide_status(_base_state(
        publisher_canon=None,
        llm_raw=make_llm_extraction(publisher_raw="UnknownBoutique"),
    ))
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert "unknown_publisher:UnknownBoutique" in out["tagging_notes"]


def test_unknown_product_yields_review_needed():
    """Spec 2026-05-07 §6.6: unknown_product → review_needed/low."""
    out = decide_status(_base_state(
        products_unknown=["완전이상한제품"],
    ))
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert "unknown_product:완전이상한제품" in out["tagging_notes"]


# ── combinations: validation failure dominates fallback signals ──

def test_unknown_stock_code_and_sent_at_fallback_still_review_needed():
    out = decide_status(_base_state(
        stock_codes_unknown=["999999"], used_sent_at_fallback=True))
    assert out["tagging_status"] == "review_needed"


def test_oos_row_skips_validation_failure_check():
    """OOS rows: stock_codes_unknown / unknown_publisher are not collected as failures."""
    # mark_oos_reason already set is_oos=True. decide_status MUST NOT collect
    # unknown_* notes for OOS rows (their meta is empty by design).
    out = decide_status(_base_state(
        is_oos=True,
        publisher_canon=None,
        llm_raw=make_llm_extraction(publisher_raw="ExternalSource"),
        products_unknown=["외국제품"],
        stock_codes_unknown=["AAPL"],
    ))
    # Note: status_oos sets tagging_status/confidence; this test only verifies
    # that decide_status doesn't override them with review_needed for OOS rows.
    # In the full graph, decide_status is bypassed for OOS path, but if called
    # directly here the result must not be review_needed/low.
    assert out["tagging_status"] != "review_needed"


def test_combined_unknown_publisher_and_product():
    out = decide_status(_base_state(
        publisher_canon=None,
        llm_raw=make_llm_extraction(publisher_raw="X"),
        products_unknown=["Y"],
    ))
    assert out["tagging_status"] == "review_needed"
    assert "unknown_publisher:X" in out["tagging_notes"]
    assert "unknown_product:Y" in out["tagging_notes"]
