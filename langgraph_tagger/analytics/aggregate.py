"""Pandas client-side aggregation for the analytics dashboard.

All functions take a DataFrame (raw rows from supabase) and return a
DataFrame ready to feed a chart. No DB calls, no Streamlit calls — pure.

effective_date: every time-bucketed aggregator uses an effective_date
column = published_at OR (sent_at converted to KST date). Required
because OOS rows have published_at=NULL (writer sets it NULL for OOS),
so without the fallback Report type volume's OOS toggle would silently
drop those rows.
"""
from __future__ import annotations

import pandas as pd


def _ensure_effective_date(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with an 'effective_date' column derived as:
       published_at  if not null,
       else sent_at converted to KST (UTC+9) and floored to the date.
    """
    out = df.copy()
    pub = pd.to_datetime(out['published_at'], errors='coerce')
    sent = pd.to_datetime(out['sent_at'], errors='coerce', utc=True)
    sent_kst = (sent.dt.tz_convert('Asia/Seoul')
                    .dt.tz_localize(None)
                    .dt.normalize())
    out['effective_date'] = pub.fillna(sent_kst)
    return out


def _floor_to_unit(s: pd.Series, unit: str) -> pd.Series:
    """Floor a datetime series to the unit: D (day), W (week), M (month).

    Uses period alias (not frequency alias). 'MS' is a frequency alias
    (Month Start offset) and is NOT a valid argument to Series.dt.to_period;
    use 'M' and let .dt.start_time give the first day of that month.
    """
    mapping = {'D': 'D', 'W': 'W', 'M': 'M'}
    freq = mapping.get(unit, 'D')
    return s.dt.to_period(freq).dt.start_time


def sector_timeseries(df: pd.DataFrame,
                       level: str,
                       items: list[str],
                       unit: str,
                       top_n: int = 10) -> pd.DataFrame:
    """For each (bucket, sector), return count.

    - level: one of 'sectors_major', 'sectors_minor', 'products'
    - items: selected sector names (overlap match). Empty → top N by volume.
    - unit: 'D', 'W', 'M'
    Output columns: ['bucket', 'sector', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['bucket', 'sector', 'count'])
    d = _ensure_effective_date(df)
    d = d[d[level].apply(lambda lst: isinstance(lst, list) and len(lst) > 0)]
    if d.empty:
        return pd.DataFrame(columns=['bucket', 'sector', 'count'])
    if items:
        d = d[d[level].apply(lambda lst: any(s in items for s in lst))]
    exploded = d.assign(sector=d[level]).explode('sector')
    if items:
        exploded = exploded[exploded['sector'].isin(items)]
    else:
        top = (exploded.groupby('sector').size()
                       .nlargest(top_n).index.tolist())
        exploded = exploded[exploded['sector'].isin(top)]
    exploded['bucket'] = _floor_to_unit(exploded['effective_date'], unit)
    return (exploded.groupby(['bucket', 'sector']).size()
                    .reset_index(name='count'))


def sector_ranking(df: pd.DataFrame,
                    level: str,
                    items: list[str],
                    limit: int = 20) -> pd.DataFrame:
    """For rows matching the sector filter, unnest stock_codes and count desc.

    Output columns: ['code', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['code', 'count'])
    d = df[df['stock_codes'].apply(lambda lst: isinstance(lst, list) and len(lst) > 0)]
    if items:
        d = d[d[level].apply(lambda lst: any(s in items for s in (lst or [])))]
    if d.empty:
        return pd.DataFrame(columns=['code', 'count'])
    codes = d['stock_codes'].explode()
    return (codes.value_counts()
                  .head(limit)
                  .rename_axis('code')
                  .reset_index(name='count'))


def report_type_timeseries(df: pd.DataFrame,
                            unit: str,
                            include_oos: bool = False) -> pd.DataFrame:
    """For each (bucket, report_type), return count.

    If include_oos is False, exclude rows with out_of_scope_reason set.
    Output columns: ['bucket', 'report_type', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['bucket', 'report_type', 'count'])
    d = _ensure_effective_date(df)
    if not include_oos:
        d = d[d['out_of_scope_reason'].isna()]
    if d.empty:
        return pd.DataFrame(columns=['bucket', 'report_type', 'count'])
    d['bucket'] = _floor_to_unit(d['effective_date'], unit)
    return (d.groupby(['bucket', 'report_type']).size()
             .reset_index(name='count'))


def stock_monthly(df: pd.DataFrame, code: str, unit: str) -> pd.DataFrame:
    """For a single stock, time-bucketed count.

    Output columns: ['bucket', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['bucket', 'count'])
    d = df[df['stock_codes'].apply(lambda lst: isinstance(lst, list) and code in lst)]
    if d.empty:
        return pd.DataFrame(columns=['bucket', 'count'])
    d = _ensure_effective_date(d)
    d['bucket'] = _floor_to_unit(d['effective_date'], unit)
    return d.groupby('bucket').size().reset_index(name='count')


def publisher_dist(df: pd.DataFrame, top_k: int = 5) -> pd.DataFrame:
    """Top K publishers by row count; rest grouped into '기타'.

    Output columns: ['publisher', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['publisher', 'count'])
    counts = df['publisher'].value_counts()
    if len(counts) <= top_k:
        return counts.rename_axis('publisher').reset_index(name='count')
    top = counts.head(top_k).rename_axis('publisher').reset_index(name='count')
    others = pd.DataFrame([{
        'publisher': '기타',
        'count': int(counts.iloc[top_k:].sum()),
    }])
    return pd.concat([top, others], ignore_index=True)
