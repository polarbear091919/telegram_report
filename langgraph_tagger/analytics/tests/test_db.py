from unittest.mock import MagicMock

import pandas as pd

from langgraph_tagger.analytics.db import AnalyticsDB


def _make_supabase_with_pages(pages: list[list[dict]]) -> MagicMock:
    """Build a supabase-py client mock whose .range().execute() returns
    pages[i] for the i-th call. Subsequent calls return empty.

    Wires the shared range_mock to BOTH terminal chains so the helper
    serves the in-scope path (select.in_.is_.gte.range) and the
    OOS-on path (select.in_.range, which skips .is_/.gte).
    """
    sb = MagicMock()
    # Build the chainable mock
    table = sb.table.return_value
    select = table.select.return_value
    in_ret = select.in_.return_value
    chain = in_ret.is_.return_value.gte.return_value
    # The .range(...).execute() must yield pages in sequence
    range_mock = MagicMock()
    chain.range.return_value = range_mock
    # OOS-on path: select.in_().range(...) bypasses .is_/.gte and lands here.
    in_ret.range.return_value = range_mock

    page_iter = iter(pages + [[]])  # trailing empty for loop termination
    def _exec():
        return MagicMock(data=next(page_iter, []))
    range_mock.execute.side_effect = _exec
    return sb


def test_fetch_inscope_rows_paginates_until_short_page():
    sb = _make_supabase_with_pages([
        [{'id': i} for i in range(1000)],
        [{'id': 1000}],   # short page → stops
    ])
    db = AnalyticsDB(sb)
    df = db.fetch_inscope_rows(period_start_iso='2026-01-01')
    assert len(df) == 1001


def test_fetch_inscope_rows_applies_in_scope_filter():
    sb = _make_supabase_with_pages([[]])
    db = AnalyticsDB(sb)
    _ = db.fetch_inscope_rows(period_start_iso='2026-01-01')
    # Confirm .in_('tagging_status', ['auto', 'verified']) and is_('out_of_scope_reason', 'null')
    table_select = sb.table.return_value.select.return_value
    table_select.in_.assert_called_with('tagging_status', ['auto', 'verified'])
    table_select.in_.return_value.is_.assert_called_with('out_of_scope_reason', 'null')


def test_fetch_inscope_rows_applies_period_filter():
    sb = _make_supabase_with_pages([[]])
    db = AnalyticsDB(sb)
    _ = db.fetch_inscope_rows(period_start_iso='2026-01-15')
    chain = (sb.table.return_value.select.return_value
                       .in_.return_value
                       .is_.return_value)
    chain.gte.assert_called_with('published_at', '2026-01-15')


def test_fetch_inscope_or_oos_rows_off_applies_isnull_and_period():
    sb = _make_supabase_with_pages([[]])
    db = AnalyticsDB(sb)
    _ = db.fetch_inscope_or_oos_rows(period_start_iso='2026-01-01', include_oos=False)
    select = sb.table.return_value.select.return_value
    select.in_.assert_called_with('tagging_status', ['auto', 'verified'])
    select.in_.return_value.is_.assert_called_with('out_of_scope_reason', 'null')
    select.in_.return_value.is_.return_value.gte.assert_called_with(
        'published_at', '2026-01-01'
    )


def test_fetch_inscope_or_oos_rows_on_skips_isnull_and_period_server_side():
    """OOS-on: server-side filter is tagging_status only.
    Period filter is client-side via effective_date."""
    sb = MagicMock()
    select = sb.table.return_value.select.return_value
    chain = select.in_.return_value.range.return_value
    chain.execute.return_value = MagicMock(data=[])
    db = AnalyticsDB(sb)
    _ = db.fetch_inscope_or_oos_rows(period_start_iso='2026-01-01', include_oos=True)
    # is_('out_of_scope_reason', 'null') must NOT have been chained
    select.in_.return_value.is_.assert_not_called()
    # gte('published_at', ...) must NOT have been chained at the server side
    select.in_.return_value.gte.assert_not_called()


def test_fetch_inscope_or_oos_rows_on_applies_client_side_period_filter():
    """OOS-on: row with published_at=NULL and sent_at < period_start must
    be filtered out client-side via effective_date."""
    sb = _make_supabase_with_pages([[
        # Falls inside period (sent_at KST 2026-05-08)
        {'id': 1, 'published_at': None, 'sent_at': '2026-05-07T22:00:00+00:00',
         'report_type': 'IR자료', 'publisher': 'X',
         'stock_codes': ['005930'], 'company_names': ['삼성전자'],
         'sectors_major': [], 'sectors_minor': [], 'products': [],
         'tagging_status': 'verified', 'out_of_scope_reason': 'ir_self',
         'file_path': '1.pdf', 'file_name': '1.pdf', 'title': ''},
        # Falls outside period (sent_at KST 2026-04-30)
        {'id': 2, 'published_at': None, 'sent_at': '2026-04-29T22:00:00+00:00',
         'report_type': 'IR자료', 'publisher': 'Y',
         'stock_codes': [], 'company_names': [],
         'sectors_major': [], 'sectors_minor': [], 'products': [],
         'tagging_status': 'verified', 'out_of_scope_reason': 'ir_self',
         'file_path': '2.pdf', 'file_name': '2.pdf', 'title': ''},
    ]])
    db = AnalyticsDB(sb)
    df = db.fetch_inscope_or_oos_rows(period_start_iso='2026-05-01', include_oos=True)
    assert len(df) == 1
    assert df.iloc[0]['id'] == 1


def test_empty_result_returns_dataframe_with_expected_columns():
    """Regression: empty fetches must still expose EXPECTED_COLS so the
    downstream aggregators don't KeyError when indexing by column."""
    sb = _make_supabase_with_pages([[]])
    db = AnalyticsDB(sb)
    df = db.fetch_inscope_rows(period_start_iso='2026-01-01')
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
    for col in ('id', 'published_at', 'report_type', 'publisher',
                'stock_codes', 'sectors_major', 'sectors_minor', 'products',
                'sent_at', 'out_of_scope_reason'):
        assert col in df.columns


def test_fetch_returns_dataframe_with_expected_columns():
    sb = _make_supabase_with_pages([[
        {'id': 1, 'published_at': '2026-05-01', 'report_type': '단일종목',
         'publisher': 'NH', 'stock_codes': ['005930'], 'company_names': ['삼성전자'],
         'sectors_major': ['반도체'], 'sectors_minor': ['메모리반도체'],
         'products': ['DRAM'], 'tagging_status': 'auto',
         'out_of_scope_reason': None, 'file_path': '1.pdf', 'file_name': '1.pdf',
         'title': 't', 'sent_at': '2026-05-01T08:00:00+00:00'},
    ]])
    db = AnalyticsDB(sb)
    df = db.fetch_inscope_rows(period_start_iso='2026-01-01')
    assert isinstance(df, pd.DataFrame)
    for col in ('id', 'published_at', 'report_type', 'publisher', 'stock_codes',
                'sectors_major', 'sectors_minor', 'products'):
        assert col in df.columns
