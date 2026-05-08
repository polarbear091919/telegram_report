"""mark_oos_reason node: sets is_oos + oos_reason from LLM signals.

oos_gate (routing function) ensures we only enter this node when one of the
OOS signals is true and the §6.5 rule 4 exceptions don't apply.
"""
from __future__ import annotations

from langgraph_tagger.state import RowState


def mark_oos_reason(state: RowState) -> dict:
    sig = state["llm_raw"].oos_signals
    if sig.foreign_primary_coverage:
        return {"is_oos": True, "oos_reason": "foreign"}
    if sig.etf_or_fund:
        return {"is_oos": True, "oos_reason": "fund"}
    if sig.digital_asset:
        return {"is_oos": True, "oos_reason": "digital"}
    # Reached only when private_company_likely is true AND oos_gate's rule-4
    # exceptions (KRX matched / IR자료 / IPO) all rejected.
    return {"is_oos": True, "oos_reason": "private"}
