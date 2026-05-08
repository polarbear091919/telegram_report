"""oos_gate: 3-way LangGraph routing function.

LangGraph 1.0 contract: routing functions for ``add_conditional_edges`` MUST
return a string label only and MUST NOT mutate state. State mutation for OOS
classification lives in the separate ``mark_oos_reason`` node.

Routes to one of:
  - status_unreadable  (pdf_unreadable or llm_refusal)
  - mark_oos_reason    (one of 4 OOS patterns; reason decided in next node)
  - canonicalize       (in-scope; downstream lookup/validate/enrich/decide)
"""
from __future__ import annotations

from typing import Literal

from langgraph_tagger.state import RowState
from langgraph_tagger.vocabulary.krx import KRXIndex


def oos_gate(state: RowState, *, krx: KRXIndex) -> Literal[
    "mark_oos_reason", "status_unreadable", "canonicalize"
]:
    if state.get("pdf_unreadable") or state.get("llm_refusal"):
        return "status_unreadable"

    raw = state.get("llm_raw")
    if raw is None:
        return "status_unreadable"

    sig = raw.oos_signals
    if sig.foreign_primary_coverage or sig.etf_or_fund or sig.digital_asset:
        return "mark_oos_reason"

    if sig.private_company_likely:
        # spec §6.5 rule 4 — KRX matched or IR자료 or IPO context all stay in-scope
        if any(krx.validate_code(c) for c in raw.stock_codes_raw):
            return "canonicalize"
        if raw.report_type == "IR자료":
            return "canonicalize"
        if raw.report_type == "IPO":
            return "canonicalize"
        return "mark_oos_reason"

    return "canonicalize"
