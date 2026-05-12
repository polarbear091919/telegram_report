"""Streamlit entry for the analytics dashboard.

Run via: python -m langgraph_tagger.analytics
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
from supabase import create_client

from langgraph_tagger.analytics import favorites, krx
from langgraph_tagger.analytics.config import load_analytics_config
from langgraph_tagger.analytics.db import AnalyticsDB
from langgraph_tagger.analytics.views import macro, stock


st.set_page_config(page_title='Analytics Dashboard', layout='wide')

FAVORITES_PATH = Path.home() / '.review_viewer' / 'favorites.json'


@st.cache_resource
def _bootstrap():
    cfg = load_analytics_config()
    sb = create_client(cfg.supabase_url, cfg.supabase_service_key)
    db = AnalyticsDB(sb)
    krx_df = krx.load_krx(cfg.krx_csv_path) if cfg.krx_csv_path.exists() else None
    return cfg, db, krx_df


cfg, db, krx_df = _bootstrap()


# session_state init
if 'current_mode' not in st.session_state:
    st.session_state.current_mode = 'macro'
if 'current_stock' not in st.session_state:
    st.session_state.current_stock = None


# -- Sidebar -----------------------------------------------------------------

with st.sidebar:
    st.markdown('### 🔍 종목 검색')
    if krx_df is not None:
        options = (krx_df['code'] + ' ' + krx_df['name']).tolist()
        selected = st.selectbox(
            '종목 (code 또는 회사명)',
            options=[''] + options,
            index=0,
            label_visibility='collapsed',
            key='search_box',
        )
        if selected:
            picked_code = selected.split(' ', 1)[0]
            if picked_code != st.session_state.current_stock:
                st.session_state.current_stock = picked_code
                st.session_state.current_mode = 'stock'
                st.rerun()
    else:
        st.warning(
            f'KRX 마스터 CSV가 없습니다: {cfg.krx_csv_path}\n\n'
            '검색·종목명 표시가 비활성화됩니다. 매크로는 정상 동작.'
        )

    st.markdown('### ⭐ 즐겨찾기')
    favs = favorites.load(FAVORITES_PATH)
    if not favs:
        st.caption('★ 즐겨찾기는 종목 dashboard의 ★ 버튼으로 추가')
    else:
        for code in favs:
            info = krx.lookup(krx_df, code) if krx_df is not None else None
            label = f'{code} {info[1]}' if info else code
            is_current = (st.session_state.current_mode == 'stock'
                            and st.session_state.current_stock == code)
            if st.button(('▶ ' if is_current else '') + label, key=f'fav_{code}'):
                st.session_state.current_stock = code
                st.session_state.current_mode = 'stock'
                st.rerun()

    st.divider()
    if st.button('📊 매크로'):
        st.session_state.current_mode = 'macro'
        st.rerun()


# -- Main --------------------------------------------------------------------

session = {
    'current_mode': st.session_state.current_mode,
    'current_stock': st.session_state.current_stock,
}

# Macro and stock both gracefully degrade when krx_df is None — pages handle
# absent KRX (ranking shows code only, stock header shows '(unknown)').
if st.session_state.current_mode == 'macro':
    macro.render(db, krx_df, session)
elif st.session_state.current_mode == 'stock':
    stock.render(db, krx_df, cfg.storage_base_dir, FAVORITES_PATH, session)
else:
    st.error(f'Unknown mode: {st.session_state.current_mode}')

# Sync session changes back to st.session_state (in case page handlers mutated)
for k in ('current_mode', 'current_stock'):
    if k in session and session[k] != st.session_state.get(k):
        st.session_state[k] = session[k]
        st.rerun()
