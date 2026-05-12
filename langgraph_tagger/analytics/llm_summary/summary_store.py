"""DB CRUD for report_summaries.

REST (supabase-py): fetch / upsert / update_diff (simple ops).
asyncpg (raw SQL): find_prev_for_diff cascade (Task 9에서 추가).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


# ── REST (supabase-py) ─────────────────────────────────────────────────────

def fetch_summaries(
    sb,                                  # supabase-py client
    report_ids: list[int],
    active_version: str,
) -> dict[int, dict[str, Any]]:
    """active version에 해당하는 summary들만 cache lookup. 다른 버전은 cache miss로 취급."""
    if not report_ids:
        return {}
    resp = (
        sb.table('report_summaries')
          .select('*')
          .in_('report_id', report_ids)
          .eq('summary_version', active_version)
          .execute()
    )
    return {row['report_id']: row for row in (resp.data or [])}


def upsert_summary(sb, payload: dict[str, Any]) -> None:
    """INSERT or full-replace UPDATE. diff 필드는 항상 NULL로 reset됨.

    Caller가 payload 빌드 시 prev_report_id/prev_match_type/diff_narrative를
    명시적으로 None으로 채워야 함 (이 함수가 강제하진 않지만 spec §10 약속).
    """
    assert payload.get('prev_report_id') is None, "upsert payload must NULL prev_report_id (diff reset)"
    assert payload.get('prev_match_type') is None, "upsert payload must NULL prev_match_type (diff reset)"
    assert payload.get('diff_narrative') is None, "upsert payload must NULL diff_narrative (diff reset)"
    sb.table('report_summaries').upsert(payload, on_conflict='report_id').execute()


def update_diff(
    sb,
    report_id: int,
    prev_report_id: Optional[int],
    match_type: Literal['same_publisher', 'cross_publisher', 'none'],
    narrative: Optional[str],
) -> None:
    """Pass2 결과 — diff 필드만 부분 update."""
    sb.table('report_summaries').update({
        'prev_report_id': prev_report_id,
        'prev_match_type': match_type,
        'diff_narrative': narrative,
    }).eq('report_id', report_id).execute()


# ── asyncpg (cascade) ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class PrevRow:
    prev_report_id: int
    prev_publisher: Optional[str]
    prev_published_at: Any              # date or string from asyncpg
    match_type: Literal['same_publisher', 'cross_publisher']
    summary: dict[str, Any]             # prev summary body (target_price_new 등)


_FIND_PREV_SQL = """
WITH eligible AS (
  SELECT
    r.id              AS prev_report_id,
    r.publisher       AS prev_publisher,
    r.published_at    AS prev_published_at,
    (r.publisher IS NOT DISTINCT FROM $2) AS is_same_pub,
    s.target_price_new,
    s.target_price_old,
    s.target_price_dir,
    s.recommendation,
    s.recommendation_dir,
    s.one_line_summary,
    s.positive_points,
    s.risk_points,
    s.target_price_raw,
    s.recommendation_raw
  FROM reports r
  INNER JOIN report_summaries s
    ON s.report_id = r.id
   AND s.summary_version = $4
  WHERE r.tagging_status IN ('auto','verified')
    AND r.report_type = '단일종목'
    AND r.out_of_scope_reason IS NULL
    AND r.stock_codes @> ARRAY[$1]::text[]
    AND r.published_at < $3::date
)
SELECT
  *,
  CASE WHEN is_same_pub THEN 'same_publisher' ELSE 'cross_publisher' END AS match_type
FROM eligible
ORDER BY is_same_pub DESC, prev_published_at DESC
LIMIT 1;
"""


async def find_prev_for_diff(
    pool,                              # asyncpg.Pool
    stock_code: str,
    publisher: Optional[str],
    current_published_at: str,         # ISO date string
    active_version: str,
) -> Optional[PrevRow]:
    """같은 종목 이전 단일종목 in-scope 리포트 중 active 버전 summary를 가진
    prev. 같은 발행처 우선, 없으면 발행처 무관 가장 최근. 둘 다 없으면 None."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _FIND_PREV_SQL,
            stock_code, publisher, current_published_at, active_version,
        )
    if row is None:
        return None
    summary_keys = (
        'target_price_new', 'target_price_old', 'target_price_dir',
        'recommendation', 'recommendation_dir', 'one_line_summary',
        'positive_points', 'risk_points',
        'target_price_raw', 'recommendation_raw',
    )
    return PrevRow(
        prev_report_id=row['prev_report_id'],
        prev_publisher=row['prev_publisher'],
        prev_published_at=row['prev_published_at'],
        match_type=row['match_type'],
        summary={k: row[k] for k in summary_keys},
    )
