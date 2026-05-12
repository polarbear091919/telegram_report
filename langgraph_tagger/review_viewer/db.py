"""supabase-py REST wrapper for review viewer queries.

Sync (Streamlit-friendly), unlike the async asyncpg adapter in
langgraph_tagger/supabase_io.py used by the tagger pipeline.
"""
from __future__ import annotations

from typing import Any, Iterable

from langgraph_tagger.review_viewer.actions import (
    SNAPSHOT_COLUMNS,
    build_pending_reset_payload,
)


class ReviewDB:
    """Thin facade over a supabase-py client.

    The client argument is intentionally typed `Any` so tests can pass
    MagicMock without dragging supabase-py imports into the test path.
    """

    def __init__(self, client: Any) -> None:
        self._sb = client

    def count_review_queue(self) -> int:
        result = (
            self._sb.table('reports')
            .select('id', count='exact')
            .eq('tagging_status', 'review_needed')
            .execute()
        )
        return int(result.count or 0)

    def fetch_next_review(self, skipped_ids: Iterable[int]) -> dict[str, Any] | None:
        skipped_list = list(skipped_ids)
        q = (
            self._sb.table('reports')
            .select('*')
            .eq('tagging_status', 'review_needed')
        )
        if skipped_list:
            q = q.not_.in_('id', skipped_list)
        q = q.order('tagged_at', desc=False).limit(1)
        result = q.execute()
        data = result.data or []
        return data[0] if data else None

    def mark_verified(self, row_id: int, payload: dict[str, Any]) -> None:
        self._sb.table('reports').update(payload).eq('id', row_id).execute()

    def mark_oos(self, row_id: int, payload: dict[str, Any]) -> None:
        self._sb.table('reports').update(payload).eq('id', row_id).execute()

    def mark_pending(self, row_id: int) -> None:
        payload = build_pending_reset_payload()
        self._sb.table('reports').update(payload).eq('id', row_id).execute()

    def restore_snapshot(self, row_id: int, snapshot: dict[str, Any]) -> None:
        """Apply only allowlisted columns from snapshot, ignoring any leakage."""
        filtered = {col: snapshot[col] for col in SNAPSHOT_COLUMNS if col in snapshot}
        self._sb.table('reports').update(filtered).eq('id', row_id).execute()
