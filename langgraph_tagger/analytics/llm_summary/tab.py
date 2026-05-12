"""Streamlit 탭 UI — 종목 dashboard 안 "🤖 LLM 분석" 탭.

기간 dropdown · 클릭 전 cache count 표시 · 분석 버튼 · progress · 카드 렌더링.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from langgraph_tagger.analytics.llm_summary import pipeline, summary_store
from langgraph_tagger.analytics.llm_summary.config import load_llm_summary_config


PERIODS = {
    '1주': 7, '1개월': 30, '3개월': 90,
    '6개월': 180, '1년': 365, '전체': 36500,
}


def _period_start_iso(label: str) -> str:
    days = PERIODS[label]
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


@st.cache_data(ttl=60)
def _fetch_summaries_cached(_sb, ids_tuple: tuple[int, ...], active_version: str):
    """Cached pre-click summary lookup. Streamlit reruns repeatedly on every
    widget interaction (period dropdown, stock switch, etc.) — avoid hammering
    Supabase REST. ttl=60 means stale-after-1-min is OK for "what's cached?" query.

    Args:
        _sb: supabase-py client (leading-underscore means st.cache_data treats it
             as opaque/non-hashable). This is the @st.cache_data convention.
        ids_tuple: tuple form so st.cache_data can hash it (lists aren't hashable).
        active_version: cache invalidation key — bump version → cache_data miss.
    """
    return summary_store.fetch_summaries(_sb, list(ids_tuple), active_version)


def _open_locally(pdf_path: Path) -> None:
    path_str = str(pdf_path)
    if sys.platform == 'win32':
        os.startfile(path_str)   # type: ignore[attr-defined]
    elif sys.platform == 'darwin':
        subprocess.run(['open', path_str], check=False)
    else:
        subprocess.run(['xdg-open', path_str], check=False)


def render(analytics_db, storage_base_dir: Path, stock_code: str) -> None:
    cfg = load_llm_summary_config()
    busy_key = f'llm_is_analyzing_{stock_code}'
    busy = st.session_state.get(busy_key, False)
    # Note: Streamlit is single-threaded so analyze_stock blocks until done.
    # `busy` flag is a defensive guard against future async-fire-and-forget patterns.

    # 상단 컨트롤
    col_period, col_button = st.columns([1, 2])
    with col_period:
        period_label = st.selectbox(
            '분석 기간', list(PERIODS.keys()), index=2,
            key=f'llm_period_{stock_code}',
        )
    period_start_iso = _period_start_iso(period_label)

    # 클릭 전 cache count 미리 표시
    df = analytics_db.fetch_stock_rows(stock_code, period_start_iso)
    if df.empty:
        st.info('선택한 기간에 리포트가 없습니다.')
        return
    single_df = df[df['report_type'] == '단일종목']
    if single_df.empty:
        other_count = len(df)
        st.info(
            f"이 기간엔 단일종목 리포트가 없습니다. "
            f"(다른 유형 {other_count}건은 📋 메타데이터 탭에서 확인 가능)"
        )
        return

    ids = single_df['id'].astype(int).tolist()
    cached = _fetch_summaries_cached(
        analytics_db._sb, tuple(ids), cfg.summary_version,
    )
    cache_hit = len(cached)
    new_count = len(ids) - cache_hit

    with col_button:
        st.caption(f'신규 분석 {new_count}건 · 캐시 {cache_hit}건')
        clicked = st.button(
            '🤖 LLM 분석', disabled=busy,
            key=f'llm_btn_{stock_code}',
            use_container_width=True,
        )

    # 분석 실행
    if clicked:
        st.session_state[busy_key] = True
        progress_box = st.empty()
        try:
            def cb(phase: int, done: int, total: int) -> None:
                label = '추출' if phase == 1 else 'diff'
                progress_box.progress(
                    done / max(total, 1),
                    text=f'{label} {done}/{total}건...',
                )
            cards = asyncio.run(pipeline.analyze_stock(
                analytics_db=analytics_db,
                storage_base_dir=storage_base_dir,
                stock_code=stock_code,
                period_start_iso=period_start_iso,
                progress_cb=cb,
                cfg=cfg,
            ))
        finally:
            progress_box.empty()
            st.session_state[busy_key] = False
        _render_cards(cards, storage_base_dir)
    else:
        # 클릭 안 했어도 기존 캐시는 보여줌 — fetched cached + meta
        cards = _build_cards_from_cache(single_df, cached)
        _render_cards(cards, storage_base_dir)


def _build_cards_from_cache(single_df, cached: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    for _, row in single_df.sort_values('published_at', ascending=False).iterrows():
        rid = int(row['id'])
        s = cached.get(rid)
        if s is not None:
            cards.append({'report_id': rid, 'summary': s, 'meta': row.to_dict()})
    return cards


def _render_cards(cards: list[dict[str, Any]], storage_base_dir: Path) -> None:
    if not cards:
        st.info('아직 분석된 카드가 없습니다. "🤖 LLM 분석" 버튼을 눌러주세요.')
        return
    for card in cards:
        _render_one_card(card, storage_base_dir)


def _arrow_for_dir(dir_: str) -> str:
    return {'상향': '⬆', '하향': '⬇', '불변': '→', '신규': '✨', 'N/A': '·'}.get(dir_, '·')


def _render_one_card(card: dict[str, Any], storage_base_dir: Path) -> None:
    meta = card['meta']
    rid = card['report_id']
    if 'error' in card:
        with st.container(border=True):
            st.warning(f"⚠ 분석 실패 — 다음 클릭 시 재시도 (report_id={rid})")
            _render_pdf_button(meta, storage_base_dir, key_suffix=str(rid))
        return

    s = card['summary']
    header = (
        f"**{meta['published_at']}** · {meta.get('publisher', '?')}  "
        f"{_arrow_for_dir(s['target_price_dir'])} "
        f"{(s.get('target_price_old') or '·')} → {(s.get('target_price_new') or '·')}  "
        f"· {s['recommendation']}({s['recommendation_dir']})"
    )
    with st.expander(header, expanded=False):
        st.caption(f"📝 {s['one_line_summary']}")
        st.markdown('---')

        if s.get('positive_points'):
            st.markdown('**✅ 긍정 포인트**')
            for p in s['positive_points']:
                st.markdown(f'- {p}')
        if s.get('risk_points'):
            st.markdown('**🟥 리스크**')
            for p in s['risk_points']:
                st.markdown(f'- {p}')

        if s.get('diff_narrative'):
            label = (
                '🔄 동일 발행처 변동' if s.get('prev_match_type') == 'same_publisher'
                else '📊 타 발행처 비교 (참고)'
            )
            st.markdown('---')
            st.markdown(f"**{label}**")
            st.write(s['diff_narrative'])

        with st.expander('▾ evidence 보기'):
            st.caption(f"raw: {s.get('target_price_raw', '·')} · {s.get('recommendation_raw', '·')}")
            st.caption(f"source pages: {s.get('source_pages', [])}")
            st.caption(f"confidence: `{s.get('extraction_confidence', '?')}`")
            if s.get('input_truncated'):
                st.warning(
                    f"⚠ PDF truncated — 토큰 cap "
                    f"({s.get('input_pages_used')}/{s.get('input_total_pages')} 페이지 사용)"
                )

        _render_pdf_button(meta, storage_base_dir, key_suffix=str(rid))


def _render_pdf_button(meta: dict, storage_base_dir: Path, key_suffix: str) -> None:
    if not meta.get('file_path'):
        return
    if st.button('📄 PDF 열기', key=f'pdf_open_{key_suffix}'):
        path = storage_base_dir / meta['file_path']
        _open_locally(path)
