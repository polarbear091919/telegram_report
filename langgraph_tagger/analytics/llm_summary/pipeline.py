"""Phase 2 orchestration — 2-pass (extract → diff) + pool lifecycle.

Spec §8. 메인 함수 `analyze_stock`은 Task 11/12에서 추가.
"""
from __future__ import annotations

from langgraph_tagger.analytics.llm_summary.schemas import ExtractionResult


def normalize_target_price_dir(r: ExtractionResult) -> ExtractionResult:
    """deterministic 산수로 target_price_dir 덮어씀 (LLM 판단보다 산수 우선).

    Spec §6.3 — old/new 둘 다 int면 부호 비교, 한쪽만이면 LLM 판단 유지,
    둘 다 None이면 'N/A' 강제.
    """
    new, old = r.target_price_new, r.target_price_old
    if new is not None and old is not None:
        if new > old:    forced = '상향'
        elif new < old:  forced = '하향'
        else:            forced = '불변'
    elif new is None and old is None:
        forced = 'N/A'
    else:
        # 한쪽만 있음 → LLM 판단 유지 (신규/N/A 등)
        return r
    if r.target_price_dir == forced:
        return r
    return r.model_copy(update={'target_price_dir': forced})
