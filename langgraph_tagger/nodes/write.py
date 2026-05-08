"""write node (v2): build UPDATE payload and persist via SupabaseSQL.

v2 변경 (rev-7):
- topics 제거, stock_codes_raw/company_names_raw 추가 → 19-arg payload
- OOS row도 LLM의 report_type/publisher/title/analysts 보존 ('기타' 강제 안 함)
"""
from __future__ import annotations

from langgraph_tagger.state import RowState
from langgraph_tagger.supabase_io import UPDATE_SQL


def _build_payload(state: RowState, taxonomy_version: str) -> tuple:
    """Return UPDATE_SQL bind-arg tuple matching $1..$19 in supabase_io.UPDATE_SQL."""
    raw = state.get("llm_raw")
    is_oos = bool(state.get("is_oos"))

    # OOS 케이스 — 분류 본체(stock_codes/company_names/sectors/products)는 비우되
    # report_type/publisher/title/analysts/raw audit는 LLM 출력 그대로 보존.
    if is_oos:
        return (
            state["id"],                                     # $1
            None,                                             # $2 published_at (OOS는 null)
            (raw.report_type if raw else None),               # $3 report_type — LLM 분류 그대로
            (raw.publisher_canon if raw else None),           # $4 publisher
            (raw.publisher_type if raw else None),            # $5 publisher_type
            list(raw.analysts) if raw else [],                # $6 analysts
            (raw.title if raw else None),                     # $7 title
            [],                                               # $8 stock_codes
            [],                                               # $9 company_names
            list(raw.stock_codes_raw) if raw else [],         # $10 stock_codes_raw (audit)
            list(raw.company_names_raw) if raw else [],       # $11 company_names_raw (audit)
            [],                                               # $12 sectors_major
            [],                                               # $13 sectors_minor
            [],                                               # $14 products
            state["oos_reason"],                              # $15 out_of_scope_reason
            state["tagging_status"],                          # $16
            state["tagging_confidence"],                      # $17
            state.get("tagging_notes"),                       # $18
            taxonomy_version,                                 # $19
        )

    # 가독 실패 (raw 없음)
    if raw is None:
        return (
            state["id"], None, None, None, None, [], None,
            [], [], [], [], [], [], [],
            None, state["tagging_status"], state["tagging_confidence"],
            state.get("tagging_notes"), taxonomy_version,
        )

    # in-scope
    return (
        state["id"],
        state["published_at_final"],
        raw.report_type,
        raw.publisher_canon,
        raw.publisher_type,
        list(raw.analysts),
        raw.title,
        list(state.get("stock_codes_final", [])),
        list(state.get("company_names_final", [])),
        list(raw.stock_codes_raw),                  # audit 항상 보존
        list(raw.company_names_raw),                # audit 항상 보존
        list(state.get("sectors_major_final", [])),
        list(state.get("sectors_minor_final", [])),
        list(state.get("products_final", [])),
        None,                                        # out_of_scope_reason NULL
        state["tagging_status"],
        state["tagging_confidence"],
        state.get("tagging_notes"),
        taxonomy_version,
    )


async def write(state: RowState, *, sb, dry_run: bool, taxonomy_version: str) -> dict:
    if dry_run:
        return {}
    args = _build_payload(state, taxonomy_version)
    await sb.execute(UPDATE_SQL, args)
    return {}
