"""Adapters for the existing coverage aggregations; no new data pipeline."""
import json

from langgraph_tagger.analytics import aggregate


def records(frame):
    return json.loads(frame.to_json(orient='records', date_format='iso'))


def market_payload(df, krx, level, items, unit, include_oos):
    inscope = df[df['out_of_scope_reason'].isna()]
    available = sorted({value for values in inscope[level] for value in (values if isinstance(values, list) else []) if value})
    rank = aggregate.sector_ranking(inscope, level, items)
    if not rank.empty:
        rank = rank.merge(krx[['code', 'name']], on='code', how='left').fillna('')
    dated = aggregate._ensure_effective_date(df)
    dates = dated['effective_date'].dropna()
    return {
        'total': len(df), 'inscope': len(inscope), 'oos': len(df) - len(inscope),
        'publishers': int(df['publisher'].nunique()),
        'latest': dates.max().date().isoformat() if len(dates) else None,
        'earliest': dates.min().date().isoformat() if len(dates) else None,
        'available_items': available,
        'coverage': records(aggregate.sector_timeseries(inscope, level, items, unit)),
        'ranking': records(rank),
        'types': records(aggregate.report_type_timeseries(df, unit, include_oos)),
    }


def stock_activity_payload(df, code, unit):
    return {'timeline': records(aggregate.stock_monthly(df, code, unit)),
            'publishers': records(aggregate.publisher_dist(df)), 'total': len(df)}
