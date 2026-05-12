import pandas as pd
import pytest

from langgraph_tagger.analytics.aggregate import (
    sector_timeseries,
    sector_ranking,
    report_type_timeseries,
    stock_monthly,
    publisher_dist,
)


# === sector_timeseries ===

def test_sector_timeseries_groups_by_unit_and_level(inscope_df):
    result = sector_timeseries(inscope_df, level='sectors_major', items=['반도체'], unit='D')
    # 4 inscope rows have '반도체' in sectors_major (rows 0,1,2,3)
    assert result['count'].sum() == 4
    assert '반도체' in result.columns or '반도체' in result['sector'].values


def test_sector_timeseries_overlap_not_contains(inscope_df):
    """multi-select returns rows with ANY of the selected sectors — overlap."""
    result = sector_timeseries(inscope_df,
                                level='sectors_major',
                                items=['반도체', '2차전지'],
                                unit='D')
    # 5 inscope rows have either 반도체 or 2차전지
    assert result['count'].sum() == 5


def test_sector_timeseries_empty_items_uses_top_n(inscope_df):
    """When items is empty, returns top N sectors by volume."""
    result = sector_timeseries(inscope_df, level='sectors_major', items=[], unit='D', top_n=3)
    # All non-empty sectors_major rows (5 rows: 4 반도체 + 1 2차전지)
    assert result['count'].sum() == 5


def test_sector_timeseries_excludes_empty_sectors(inscope_df):
    """Row 4 (산업 type, empty sectors_major) must not appear."""
    result = sector_timeseries(inscope_df, level='sectors_major', items=['반도체'], unit='D')
    assert result['count'].sum() == 4  # not 5 — the 산업 row has empty sectors


# === sector_ranking ===

def test_sector_ranking_counts_unnested_stock_codes(inscope_df):
    """When 반도체 selected, count stock_codes occurrences across matching rows.
    Rows 0,1: ['005930']. Row 2: ['000660']. Row 3: ['005930','000660'].
    Total: 005930 appears 3 times, 000660 appears 2 times.
    """
    result = sector_ranking(inscope_df,
                             level='sectors_major',
                             items=['반도체'],
                             limit=10)
    by_code = dict(zip(result['code'], result['count']))
    assert by_code['005930'] == 3
    assert by_code['000660'] == 2


def test_sector_ranking_empty_items_uses_full_scope(inscope_df):
    """No filter: count over all rows with non-empty stock_codes."""
    result = sector_ranking(inscope_df, level='sectors_major', items=[], limit=10)
    by_code = dict(zip(result['code'], result['count']))
    assert by_code['005930'] == 3
    assert by_code['000660'] == 2
    assert by_code['373220'] == 1


# === report_type_timeseries ===

def test_report_type_timeseries_groups_by_type_and_unit(inscope_df):
    result = report_type_timeseries(inscope_df, unit='D')
    types = result['report_type'].unique().tolist()
    assert '단일종목' in types
    assert '섹터' in types
    assert '산업' in types
    # 단일종목 inscope rows: indices 0,1,2,5 → 4 rows
    type_counts = result.groupby('report_type')['count'].sum()
    assert type_counts['단일종목'] == 4
    assert type_counts['섹터'] == 1
    assert type_counts['산업'] == 1


def test_report_type_timeseries_oos_off_excludes_oos(with_oos_df):
    """Default (no OOS) — IR자료 OOS and foreign OOS not counted."""
    result = report_type_timeseries(with_oos_df, unit='D')
    types = result['report_type'].unique().tolist()
    assert 'IR자료' not in types
    # The foreign-tagged 단일종목 row (out_of_scope_reason='foreign') must also be excluded
    type_counts = result.groupby('report_type')['count'].sum()
    assert type_counts['단일종목'] == 4   # excludes the foreign OOS one


def test_report_type_timeseries_oos_on_includes_all(with_oos_df):
    """include_oos=True — IR자료 + foreign OOS rows counted.

    Regression: OOS rows have published_at=None and only sent_at set.
    The aggregator must derive effective_date from sent_at, otherwise
    these rows silently drop out of the count.
    """
    result = report_type_timeseries(with_oos_df, unit='D', include_oos=True)
    types = result['report_type'].unique().tolist()
    assert 'IR자료' in types
    type_counts = result.groupby('report_type')['count'].sum()
    assert type_counts['IR자료'] == 1
    assert type_counts['단일종목'] == 5   # includes the foreign OOS 단일종목 row


def test_report_type_timeseries_uses_sent_at_when_published_at_null():
    """Explicit regression: a row with only sent_at (no published_at) must
    appear in include_oos=True buckets, using sent_at KST date."""
    df = pd.DataFrame([
        {'published_at': None,
         'sent_at': '2026-05-07T22:00:00+00:00',   # 2026-05-08 KST
         'report_type': 'IR자료', 'publisher': 'X',
         'stock_codes': [], 'sectors_major': [], 'sectors_minor': [],
         'products': [], 'out_of_scope_reason': 'ir_self'},
    ])
    result = report_type_timeseries(df, unit='D', include_oos=True)
    assert len(result) == 1
    # The bucket date is the sent_at KST date (2026-05-08), not UTC (2026-05-07)
    assert result.iloc[0]['bucket'].strftime('%Y-%m-%d') == '2026-05-08'
    assert result.iloc[0]['report_type'] == 'IR자료'


# === stock_monthly ===

def test_stock_monthly_filters_by_code(inscope_df):
    result = stock_monthly(inscope_df, code='005930', unit='D')
    # Rows 0,1,3 have 005930 (in_df rows 0,1,3 — row 3 is the 섹터 multi-stock)
    assert result['count'].sum() == 3


def test_stock_monthly_unknown_code_returns_empty(inscope_df):
    result = stock_monthly(inscope_df, code='999999', unit='D')
    assert result['count'].sum() == 0


# === publisher_dist ===

def test_publisher_dist_counts_by_publisher(inscope_df):
    """For 005930 rows: 메리츠(1), 키움(1), NH(1)."""
    df_stock = inscope_df[inscope_df['stock_codes'].apply(lambda lst: '005930' in lst)]
    result = publisher_dist(df_stock, top_k=10)
    by_pub = dict(zip(result['publisher'], result['count']))
    assert by_pub['메리츠'] == 1
    assert by_pub['키움'] == 1
    assert by_pub['NH'] == 1


def test_publisher_dist_top_k_groups_into_other(inscope_df):
    """If top_k < unique publishers, the rest go to '기타'."""
    result = publisher_dist(inscope_df, top_k=2)
    pubs = result['publisher'].tolist()
    assert '기타' in pubs
    # All rows accounted for
    assert result['count'].sum() == len(inscope_df)
