"""Macro page — two sub-tabs: Sector coverage + Report type volume."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from langgraph_tagger.analytics import aggregate, charts


PERIODS = {
    '최근 30일': 30,
    '최근 90일': 90,
    '최근 180일': 180,
    '최근 1년': 365,
    '전체': 36500,
}
UNITS = {'일별': 'D', '주별': 'W', '월별': 'M'}


def _period_start_iso(label: str) -> str:
    days = PERIODS[label]
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.date().isoformat()


def render(db, krx_df, session) -> None:
    """Render macro page with two sub-tabs."""
    tab_coverage, tab_report_type = st.tabs(['Sector coverage', 'Report type volume'])

    with tab_coverage:
        _render_sector_coverage(db, krx_df, session)

    with tab_report_type:
        _render_report_type_volume(db, session)


def _render_sector_coverage(db, krx_df, session) -> None:
    col_level, col_period, col_unit = st.columns([2, 1, 1])
    with col_level:
        level_label = st.segmented_control(
            'level',
            options=['산업(대)', '산업(중)', '제품'],
            default='산업(대)',
            label_visibility='collapsed',
        ) or '산업(대)'
    level_map = {'산업(대)': 'sectors_major', '산업(중)': 'sectors_minor', '제품': 'products'}
    level_col = level_map[level_label]

    with col_period:
        period_label = st.selectbox('기간', list(PERIODS.keys()), index=1, key='cov_period')
    with col_unit:
        unit_label = st.selectbox('단위', list(UNITS.keys()), index=1, key='cov_unit')

    df_raw = _fetch_inscope_cached(db, _period_start_iso(period_label))

    # Distinct values for the chosen level — for the multiselect
    distinct = sorted({s for lst in df_raw[level_col].dropna()
                        for s in (lst or []) if s})
    items = st.multiselect(
        f'{level_label} 선택 (비워두면 발행량 top 10 자동)',
        options=distinct,
        key='cov_items',
    )

    chart_df = aggregate.sector_timeseries(df_raw, level=level_col, items=items,
                                            unit=UNITS[unit_label])
    col_chart, col_rank = st.columns([2, 1])
    with col_chart:
        st.plotly_chart(charts.timeseries_line(chart_df, title='Sector coverage'),
                         use_container_width=True)
    with col_rank:
        ranking_df = aggregate.sector_ranking(df_raw, level=level_col, items=items, limit=20)
        # Join name from KRX master for nicer labels — degrade gracefully if KRX missing
        if krx_df is not None and not ranking_df.empty:
            ranking_df = ranking_df.merge(krx_df[['code', 'name']], on='code', how='left')
            ranking_df['label'] = ranking_df['code'] + ' ' + ranking_df['name'].fillna('')
        else:
            ranking_df['label'] = ranking_df['code'] if not ranking_df.empty else []
        st.caption('coverage volume — 이 채널에서 다뤄진 횟수 (시장 hot 지표 아님)')
        st.plotly_chart(charts.ranking_bar(ranking_df), use_container_width=True)
        for _, row in ranking_df.iterrows():
            if st.button(row['label'], key=f"rank_{row['code']}"):
                session['current_stock'] = row['code']
                session['current_mode'] = 'stock'
                st.rerun()


def _render_report_type_volume(db, session) -> None:
    col_period, col_unit, col_toggle = st.columns([1, 1, 2])
    with col_period:
        period_label = st.selectbox('기간', list(PERIODS.keys()), index=1, key='rt_period')
    with col_unit:
        unit_label = st.selectbox('단위', list(UNITS.keys()), index=1, key='rt_unit')
    with col_toggle:
        include_oos = st.toggle('OOS 포함 (IR자료 / foreign 등)', value=False, key='rt_oos')

    df_raw = _fetch_inscope_or_oos_cached(db,
                                            _period_start_iso(period_label),
                                            include_oos)
    chart_df = aggregate.report_type_timeseries(df_raw,
                                                  unit=UNITS[unit_label],
                                                  include_oos=include_oos)
    st.plotly_chart(charts.report_type_lines(chart_df), use_container_width=True)
    st.caption('Default: in-scope only (OOS verified 행 제외). toggle 켜면 IR자료/foreign/private/digital 포함.')


@st.cache_data(ttl=180)
def _fetch_inscope_cached(_db, period_start_iso: str):
    return _db.fetch_inscope_rows(period_start_iso)


@st.cache_data(ttl=180)
def _fetch_inscope_or_oos_cached(_db, period_start_iso: str, include_oos: bool):
    return _db.fetch_inscope_or_oos_rows(period_start_iso, include_oos)
