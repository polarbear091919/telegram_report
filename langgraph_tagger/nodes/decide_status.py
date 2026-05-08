"""decide_status node: spec 2026-05-07 §6.6 status/confidence/notes decision tree.

Policy (spec §6.6):
  - unknown_stock_code  → review_needed/low
  - unknown_sector      → review_needed/low
  - unknown_product     → review_needed/low   (spec §6.6 — no silent drop)
  - unknown_publisher   → review_needed/low   (spec §6.6 — broker/IR-agency 분류 핵심)
  - type_indeterminate  → review_needed/low
  - first_page_unreadable / llm_refusal → review_needed/low

This is the **rule-tree heart** of langgraph_tagger. Implementing the rules
in code (rather than relying on the LLM to apply them) gives:
  1. Deterministic, testable output (this file's tests cover every branch).
  2. Zero LLM tokens for the decision step.
  3. Easy iteration on rules without re-prompting.
"""
from __future__ import annotations

from langgraph_tagger.state import RowState


def decide_status(state: RowState) -> dict:
    # 0. Hard gating: unreadable / refusal already handled by status_unreadable;
    # but if this node ever sees them (e.g., direct test), produce same output.
    if state.get("pdf_unreadable"):
        return {
            "tagging_status": "review_needed",
            "tagging_confidence": "low",
            "tagging_notes": "first_page_unreadable",
        }
    if state.get("llm_refusal"):
        return {
            "tagging_status": "review_needed",
            "tagging_confidence": "low",
            "tagging_notes": f"llm_refusal:{state['llm_refusal']}",
        }

    notes: list[str] = []
    raw = state.get("llm_raw")
    is_oos = bool(state.get("is_oos"))

    # 1. type_indeterminate: report_type='기타' + self_confidence='low' + not OOS
    if (raw is not None
            and raw.report_type == "기타"
            and raw.self_confidence == "low"
            and not is_oos):
        notes.append("type_indeterminate")

    # 2. Validation failures (only matter when not OOS)
    # Spec §6.6 정책: stock_codes/sectors/products/publisher 네 가지 모두
    # KRX 도메인 / vocabulary 외면 review_needed/low.
    if not is_oos:
        if state.get("stock_codes_unknown"):
            notes.append("unknown_stock_code:" + ",".join(state["stock_codes_unknown"]))
        if state.get("sectors_unknown"):
            notes.append("unknown_sector:" + ",".join(state["sectors_unknown"]))
        if state.get("products_unknown"):
            notes.append("unknown_product:" + ",".join(state["products_unknown"]))
        if state.get("publisher_canon") is None and raw is not None and raw.publisher_raw:
            notes.append(f"unknown_publisher:{raw.publisher_raw}")

    has_validation_failure = any(
        n.startswith(("unknown_stock_code:", "unknown_sector:",
                      "unknown_product:", "unknown_publisher:",
                      "type_indeterminate"))
        for n in notes
    )
    if has_validation_failure:
        return {
            "tagging_status": "review_needed",
            "tagging_confidence": "low",
            "tagging_notes": ";".join(notes),
        }

    # 3. auto: confidence determined by fallback signals
    # NOTE: publisher_canon=None 케이스는 위 has_validation_failure에서 처리됐으므로
    # 여기 도달하면 publisher_canon이 채워졌거나 publisher_raw가 비어있음.
    used_fallback = (
        state.get("used_sent_at_fallback")
        or bool(state.get("topic_unmapped"))
        or len(state.get("pages_used") or [1]) > 1
    )

    return {
        "tagging_status": "auto",
        "tagging_confidence": "medium" if used_fallback else "high",
        "tagging_notes": ";".join(notes) if notes else None,
    }
