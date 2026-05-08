"""write node: build UPDATE payload and persist via SupabaseSQL."""
from __future__ import annotations

from langgraph_tagger.state import RowState
from langgraph_tagger.supabase_io import UPDATE_SQL


def _build_payload(state: RowState, taxonomy_version: str) -> tuple:
    """Return UPDATE_SQL bind-arg tuple matching $1..$18 in supabase_io.UPDATE_SQL."""
    raw = state.get("llm_raw")
    is_oos = bool(state.get("is_oos"))

    # OOS: force report_type='기타', empty meta arrays, set out_of_scope_reason
    if is_oos:
        return (
            state["id"],                                     # $1
            None,                                             # $2 published_at (could fill from raw if present)
            "기타",                                           # $3 report_type
            None,                                             # $4 publisher
            None,                                             # $5 publisher_type
            [],                                               # $6 analysts
            (raw.title if raw else None),                     # $7 title (kept for search)
            [],                                               # $8 stock_codes
            [],                                               # $9 company_names
            [],                                               # $10 sectors_major
            [],                                               # $11 sectors_minor
            [],                                               # $12 products
            [],                                               # $13 topics
            state["oos_reason"],                              # $14 out_of_scope_reason
            state["tagging_status"],                          # $15
            state["tagging_confidence"],                      # $16
            state.get("tagging_notes"),                       # $17
            taxonomy_version,                                 # $18 taxonomy_version
        )

    # Unreadable / refusal: leave report_type NULL, all meta empty
    if raw is None:
        return (
            state["id"], None, None, None, None, [], None, [], [], [], [], [], [],
            None, state["tagging_status"], state["tagging_confidence"],
            state.get("tagging_notes"), taxonomy_version,
        )

    # In-scope: full meta
    return (
        state["id"],
        state["published_at_final"],
        raw.report_type,
        state.get("publisher_canon"),
        state.get("publisher_type"),
        list(raw.analysts),
        raw.title,
        list(state.get("stock_codes_valid", [])),
        list(state.get("company_names_final", [])),
        list(state.get("sectors_major_final", [])),
        list(state.get("sectors_minor_final", [])),
        list(state.get("products_final", [])),
        list(state.get("topics_canon", [])),
        None,                                                  # out_of_scope_reason NULL
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
