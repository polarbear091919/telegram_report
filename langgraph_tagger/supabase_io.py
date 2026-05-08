"""Supabase Postgres direct connection (asyncpg) for atomic claim / stale lock / UPDATE.

Why not supabase-py? supabase-py wraps PostgREST and doesn't natively support
``FOR UPDATE SKIP LOCKED`` semantics or arbitrary raw SQL without RPC functions.
Direct asyncpg keeps the SQL transparent and matches the spec §6.7 atomic claim
verbatim.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import asyncpg


# ── SQL constants (spec §9.1) ────────────────────────────────────────────────

STALE_LOCK_RECLAIM_SQL = """
UPDATE reports
   SET tagging_status='pending', tagging_locked_at=NULL, tagging_worker_id=NULL
 WHERE tagging_status='processing'
   AND tagging_locked_at < now() - ($1::int * interval '1 minute')
"""

ATOMIC_CLAIM_SQL = """
UPDATE reports
   SET tagging_status='processing',
       tagging_locked_at=now(),
       tagging_worker_id=$1
 WHERE id IN (
       SELECT id FROM reports
        WHERE tagging_status='pending'
        ORDER BY downloaded_at ASC
        LIMIT $2
        FOR UPDATE SKIP LOCKED
       )
RETURNING id, file_path, file_name, sent_at, caption, chat_username
"""

DRY_RUN_SELECT_SQL = """
SELECT id, file_path, file_name, sent_at, caption, chat_username
  FROM reports
 WHERE tagging_status='pending'
 ORDER BY downloaded_at ASC
 LIMIT $1
"""

ROW_IDS_FETCH_SQL = """
SELECT id, file_path, file_name, sent_at, caption, chat_username
  FROM reports
 WHERE id = ANY($1::bigint[])
"""

REVERT_TO_PENDING_SQL = """
UPDATE reports
   SET tagging_status='pending', tagging_locked_at=NULL, tagging_worker_id=NULL
 WHERE id=$1 AND tagging_status='processing'
"""

# Note: in-scope and OOS rows use the same UPDATE statement; the payload differs.
UPDATE_SQL = """
UPDATE reports
   SET published_at=$2,
       report_type=$3,
       publisher=$4,
       publisher_type=$5,
       analysts=$6,
       title=$7,
       stock_codes=$8,
       company_names=$9,
       sectors_major=$10,
       sectors_minor=$11,
       products=$12,
       topics=$13,
       out_of_scope_reason=$14,
       tagging_status=$15,
       tagging_confidence=$16,
       tagging_notes=$17,
       tagging_locked_at=NULL,
       tagging_worker_id=NULL,
       tagged_at=now(),
       tagger_version='langgraph-tagger@1.0',
       taxonomy_version=$18
 WHERE id=$1
"""

ESCALATION_PICK_SQL = """
SELECT id FROM reports
 WHERE tagging_status='review_needed'
   AND tagged_at >= $1
"""

INSPECT_SUMMARY_SQL = """
SELECT
  (SELECT count(*) FROM reports WHERE tagging_status='pending')          AS pending,
  (SELECT count(*) FROM reports WHERE tagging_status='processing')       AS processing,
  (SELECT count(*) FROM reports WHERE tagging_status='auto')             AS auto,
  (SELECT count(*) FROM reports WHERE tagging_status='review_needed')    AS review_needed,
  (SELECT count(*) FROM reports WHERE tagging_status='verified')         AS verified,
  (SELECT count(*) FROM reports WHERE out_of_scope_reason IS NOT NULL)   AS oos_total,
  (SELECT count(*) FROM reports WHERE tagged_at >= now() - interval '24 hours') AS last_24h
"""


# ── Adapter ──────────────────────────────────────────────────────────────────

class SupabaseSQL:
    """Thin asyncpg-backed adapter for the SQL constants above."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def from_env(cls) -> "SupabaseSQL":
        url = os.environ.get("SUPABASE_DB_URL")
        if not url:
            raise RuntimeError("SUPABASE_DB_URL is required")
        pool = await asyncpg.create_pool(url, min_size=1, max_size=10)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def fetch(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]

    async def execute(self, sql: str, args: Iterable[Any] = ()) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql, *args)
