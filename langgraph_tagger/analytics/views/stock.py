"""Stock dashboard page — header + timeseries + publisher dist + report list."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from langgraph_tagger.analytics import aggregate, charts, favorites, krx


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


def _open_locally(pdf_path: Path) -> None:
    path_str = str(pdf_path)
    if sys.platform == 'win32':
        os.startfile(path_str)   # type: ignore[attr-defined]
    elif sys.platform == 'darwin':
        subprocess.run(['open', path_str], check=False)
    else:
        subprocess.run(['xdg-open', path_str], check=False)


def render(db, krx_df, storage_base_dir: Path, favorites_path: Path, session) -> None:
    code = session.get('current_stock')
    if not code:
        st.warning('종목이 선택되지 않았습니다. sidebar의 검색 또는 즐겨찾기에서 선택해주세요.')
        return

    info = krx.lookup(krx_df, code) if krx_df is not None else None
    name = info[1] if info else '(unknown)'
    sector_major = info[2] if info else ''
    sector_minor = info[3] if info else ''

    # Header
    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.subheader(f'{code} {name}')
        sector_caption = ' · '.join(s for s in (sector_major, sector_minor) if s)
        prefix = f'{sector_caption} · ' if sector_caption else ''
        st.caption(f'{prefix}explicit KRX-mapped coverage only — 본문 mention 미포함')
    with col_right:
        col_p, col_fav = st.columns([1, 1])
        with col_p:
            period_label = st.selectbox('기간', list(PERIODS.keys()),
                                          index=3, key=f'stock_period_{code}')
        with col_fav:
            favs = favorites.load(favorites_path)
            if code in favs:
                if st.button('★ 즐겨찾기 해제', key=f'fav_off_{code}'):
                    favorites.remove(favorites_path, code)
                    st.rerun()
            else:
                if st.button('☆ 즐겨찾기 추가', key=f'fav_on_{code}'):
                    favorites.add(favorites_path, code)
                    st.rerun()

    period_iso = _period_start_iso(period_label)
    df_raw = _fetch_stock_cached(db, code, period_iso)

    if df_raw.empty:
        st.info('이 종목 다룬 in-scope 리서치가 아직 없습니다.')
        return

    # Total count
    st.caption(f'총 발행수 {len(df_raw)}건')

    # Top: timeseries + publisher pie
    col_ts, col_pie = st.columns([2, 1])
    with col_ts:
        ts_df = aggregate.stock_monthly(df_raw, code=code, unit='W')
        st.plotly_chart(charts.monthly_bar(ts_df, title='발행 시계열'),
                         use_container_width=True)
    with col_pie:
        pub_df = aggregate.publisher_dist(df_raw, top_k=5)
        st.plotly_chart(charts.publisher_pie(pub_df), use_container_width=True)

    # Bottom: report list
    st.markdown('**발행 리스트**')
    list_df = df_raw[['published_at', 'publisher', 'title', 'report_type', 'file_path']].copy()
    list_df = list_df.sort_values('published_at', ascending=False).reset_index(drop=True)

    page_size = 20
    if f'stock_page_{code}' not in st.session_state:
        st.session_state[f'stock_page_{code}'] = 1
    page = st.session_state[f'stock_page_{code}']
    display = list_df.head(page * page_size)

    for i, row in display.iterrows():
        c1, c2, c3, c4, c5 = st.columns([1, 1, 4, 1, 1])
        with c1:
            st.text(str(row['published_at'])[:10])
        with c2:
            st.text(row['publisher'] or '')
        with c3:
            st.text((row['title'] or '')[:80])
        with c4:
            st.text(row['report_type'] or '')
        with c5:
            file_path = Path(row['file_path']) if row['file_path'] else None
            full_path = (storage_base_dir / file_path) if file_path and not file_path.is_absolute() else file_path
            if full_path and full_path.exists():
                if st.button('📄', key=f'pdf_{code}_{i}'):
                    _open_locally(full_path)
            else:
                st.text('—')

    if len(list_df) > page * page_size:
        if st.button('더 보기', key=f'more_{code}'):
            st.session_state[f'stock_page_{code}'] += 1
            st.rerun()


@st.cache_data(ttl=180)
def _fetch_stock_cached(_db, code: str, period_start_iso: str):
    return _db.fetch_stock_rows(code, period_start_iso)
