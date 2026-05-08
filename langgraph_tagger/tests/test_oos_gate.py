"""Tests for oos_gate (3-way routing function — does NOT mutate state)."""
import pytest

from langgraph_tagger.llm_schemas import LLMExtraction, OOSSignals
from langgraph_tagger.nodes.oos_gate import oos_gate
from langgraph_tagger.tests.conftest import make_llm_extraction


def _ext(**oos_kwargs) -> LLMExtraction:
    sig = OOSSignals(
        foreign_primary_coverage=oos_kwargs.get("foreign", False),
        etf_or_fund=oos_kwargs.get("etf", False),
        digital_asset=oos_kwargs.get("digital", False),
        private_company_likely=oos_kwargs.get("private", False),
    )
    return make_llm_extraction(
        oos_signals=sig,
        report_type=oos_kwargs.get("report_type", "단일종목"),
        stock_codes_raw=oos_kwargs.get("stock_codes_raw", []),
    )


def test_pdf_unreadable_routes_to_status_unreadable(krx):
    state = {"pdf_unreadable": True, "llm_raw": None}
    assert oos_gate(state, krx=krx) == "status_unreadable"
    # state must NOT be mutated
    assert "oos_reason" not in state


def test_llm_refusal_routes_to_status_unreadable(krx):
    state = {"pdf_unreadable": False, "llm_raw": None, "llm_refusal": "policy"}
    assert oos_gate(state, krx=krx) == "status_unreadable"
    assert "oos_reason" not in state


def test_foreign_routes_to_mark_oos(krx):
    state = {"llm_raw": _ext(foreign=True)}
    assert oos_gate(state, krx=krx) == "mark_oos_reason"
    # routing-only — does NOT set oos_reason here
    assert "oos_reason" not in state


def test_fund_routes_to_mark_oos(krx):
    state = {"llm_raw": _ext(etf=True)}
    assert oos_gate(state, krx=krx) == "mark_oos_reason"


def test_digital_routes_to_mark_oos(krx):
    state = {"llm_raw": _ext(digital=True)}
    assert oos_gate(state, krx=krx) == "mark_oos_reason"


def test_private_with_no_krx_match_routes_to_mark_oos(krx):
    state = {"llm_raw": _ext(private=True, stock_codes_raw=["999999"])}
    assert oos_gate(state, krx=krx) == "mark_oos_reason"


def test_private_with_krx_match_stays_in_scope(krx):
    # spec §6.5 rule 4: KRX-matched code → in-scope even if private signal is set
    state = {"llm_raw": _ext(private=True, stock_codes_raw=["005930"])}
    assert oos_gate(state, krx=krx) == "canonicalize"


def test_private_with_ir_jaryo_stays_in_scope(krx):
    # spec §6.5 rule 4: publisher_type=company (자체 IR) is in-scope IR자료
    state = {"llm_raw": _ext(private=True, report_type="IR자료")}
    assert oos_gate(state, krx=krx) == "canonicalize"


def test_private_with_ipo_unmatched_stays_in_scope(krx):
    # spec §6.5 rule 4 second case: KRX-unmatched but public-offer/IPO context → in-scope IPO
    state = {"llm_raw": _ext(private=True, report_type="IPO")}
    assert oos_gate(state, krx=krx) == "canonicalize"


def test_in_scope_default_routes_to_canonicalize(krx):
    state = {"llm_raw": _ext()}
    assert oos_gate(state, krx=krx) == "canonicalize"


def test_routing_function_does_not_mutate_state_in_any_branch(krx):
    """Defense-in-depth: snapshot before/after to confirm no mutation."""
    import copy
    state = {"llm_raw": _ext(foreign=True)}
    snapshot = copy.deepcopy(state)
    oos_gate(state, krx=krx)
    assert state == snapshot
