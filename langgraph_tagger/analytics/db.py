"""supabase-py REST wrapper with paginated fetch.

Fetcher pattern:
  - in-scope only: server-side published_at filter is safe (writer
    always sets published_at for in-scope rows).
  - OOS included: writer sets published_at=NULL for OOS rows, so the
    server-side published_at filter would silently drop them. Instead,
    skip the server-side period filter and let aggregate.py filter by
    effective_date (published_at or sent_at KST) client-side.

All group-by / unnest / bucket happens client-side in aggregate.py.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

PAGE = 1000

EXPECTED_COLS: tuple[str, ...] = (
    'id', 'published_at', 'sent_at', 'report_type', 'publisher',
    'stock_codes', 'company_names', 'sectors_major', 'sectors_minor',
    'products', 'tagging_status', 'out_of_scope_reason', 'file_path',
    'file_name', 'title',
)

SELECT_COLS = ', '.join(EXPECTED_COLS)


def _paged_fetch(chain) -> list[dict]:
    """Loop .range(offset, offset+PAGE-1).execute() until a short page."""
    rows: list[dict] = []
    offset = 0
    while True:
        result = chain.range(offset, offset + PAGE - 1).execute()
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return rows


def _to_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame that always has the expected columns, even for
    empty results — downstream aggregators index columns by name."""
    df = pd.DataFrame(rows, columns=list(EXPECTED_COLS))
    return df


class AnalyticsDB:
    """Read-only DB wrapper for analytics dashboard."""

    def __init__(self, client: Any) -> None:
        self._sb = client

    def fetch_inscope_rows(self, period_start_iso: str) -> pd.DataFrame:
        """In-scope rows only. tagging_status IN ('auto','verified') AND
        out_of_scope_reason IS NULL AND published_at >= period_start.
        """
        chain = (
            self._sb.table('reports')
            .select(SELECT_COLS)
            .in_('tagging_status', ['auto', 'verified'])
            .is_('out_of_scope_reason', 'null')
            .gte('published_at', period_start_iso)
        )
        rows = _paged_fetch(chain)
        return _to_frame(rows)

    def fetch_inscope_or_oos_rows(self,
                                    period_start_iso: str,
                                    include_oos: bool) -> pd.DataFrame:
        """For Report type volume sub-tab.

        - include_oos=False: in-scope only, server-side published_at filter.
        - include_oos=True: OOS rows have published_at=NULL. Skip the
          server-side period filter and let the caller (aggregate.py) drop
          rows whose effective_date < period_start via _ensure_effective_date.
        """
        chain = (
            self._sb.table('reports')
            .select(SELECT_COLS)
            .in_('tagging_status', ['auto', 'verified'])
        )
        if not include_oos:
            chain = (chain
                     .is_('out_of_scope_reason', 'null')
                     .gte('published_at', period_start_iso))
        rows = _paged_fetch(chain)
        df = _to_frame(rows)
        if include_oos:
            # Client-side period filter using effective_date semantics:
            # published_at OR (sent_at as KST date).
            pub = pd.to_datetime(df['published_at'], errors='coerce')
            sent = pd.to_datetime(df['sent_at'], errors='coerce', utc=True)
            sent_kst = (sent.dt.tz_convert('Asia/Seoul')
                            .dt.tz_localize(None)
                            .dt.normalize())
            eff = pub.fillna(sent_kst)
            cutoff = pd.Timestamp(period_start_iso)
            df = df[eff >= cutoff].reset_index(drop=True)
        return df

    def fetch_stock_rows(self, code: str, period_start_iso: str) -> pd.DataFrame:
        """All in-scope rows where stock_codes contains the given code.

        Uses Postgres array contains: .cs('stock_codes', '{<code>}').
        """
        chain = (
            self._sb.table('reports')
            .select(SELECT_COLS)
            .in_('tagging_status', ['auto', 'verified'])
            .is_('out_of_scope_reason', 'null')
            .cs('stock_codes', f'{{{code}}}')
            .gte('published_at', period_start_iso)
        )
        rows = _paged_fetch(chain)
        return _to_frame(rows)
