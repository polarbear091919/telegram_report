"""Streamlit entry for the review viewer.

Run via: python -m langgraph_tagger.review_viewer
(which subprocess-launches `streamlit run` on this file)
"""
from __future__ import annotations

import streamlit as st
from supabase import create_client

from langgraph_tagger.review_viewer.actions import (
    V2_OOS_REASONS,
    capture_snapshot,
    build_verified_payload,
    build_oos_payload,
)
from langgraph_tagger.review_viewer.config import load_review_viewer_config
from langgraph_tagger.review_viewer.db import ReviewDB
from langgraph_tagger.review_viewer.pdf import (
    resolve_path,
    render_pages,
    open_locally,
)


# ── Bootstrap ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Review Viewer", layout="wide")


@st.cache_resource
def _bootstrap():
    cfg = load_review_viewer_config()
    client = create_client(cfg.supabase_url, cfg.supabase_service_key)
    return cfg, ReviewDB(client)


cfg, db = _bootstrap()


# ── Session state init ───────────────────────────────────────────────────────

if 'skipped_ids' not in st.session_state:
    st.session_state.skipped_ids = set()
if 'last_snapshot' not in st.session_state:
    st.session_state.last_snapshot = None  # (row_id, snapshot_dict)
if 'total_at_start' not in st.session_state:
    st.session_state.total_at_start = db.count_review_queue()
if 'counts' not in st.session_state:
    st.session_state.counts = {'verified': 0, 'oos': 0, 'retag': 0, 'skip': 0}


# ── Fetch next row ───────────────────────────────────────────────────────────

row = db.fetch_next_review(st.session_state.skipped_ids)

if row is None:
    st.success("🎉 Review queue empty.")
    c = st.session_state.counts
    st.write(
        f"Session totals — verified: {c['verified']}, oos: {c['oos']}, "
        f"re-tag: {c['retag']}, skip: {c['skip']}"
    )
    st.stop()


# ── Layout ───────────────────────────────────────────────────────────────────

left, right = st.columns([2, 1])


# ── Left: PDF page images ────────────────────────────────────────────────────

with left:
    pdf_path = resolve_path(cfg.storage_base_dir, row['file_path'])
    if not pdf_path.exists():
        st.warning(f"PDF not found at {pdf_path}. Decide using metadata + LLM result only.")
    else:
        try:
            pages = render_pages(pdf_path, n=3, dpi=120)
            for png in pages:
                st.image(png, width="stretch")
        except Exception as e:
            st.error(f"PyMuPDF render failed: {e}")

        if st.button("📄 Open in OS viewer"):
            open_locally(pdf_path)


# ── Right: review panel ──────────────────────────────────────────────────────

def _highlight_reason(notes: str | None) -> None:
    if not notes:
        return
    color = '#fff3cd'
    border = '#f0ad4e'
    if 'first_page_unreadable' in (notes or ''):
        color, border = '#fde2e2', '#d9534f'
    st.markdown(
        f"<div style='background:{color};border-left:4px solid {border};"
        f"padding:8px 10px;font-size:13px'>"
        f"<strong>왜 review 큐?</strong><br/>"
        f"<code>{notes}</code></div>",
        unsafe_allow_html=True,
    )


with right:
    # Progress header
    c = st.session_state.counts
    n = c['verified'] + c['oos'] + c['retag'] + c['skip']
    N = st.session_state.total_at_start
    st.markdown(f"**{n} / {N}** &nbsp; ✓{c['verified']} ✗{c['oos']} ↺{c['retag']} ↻{c['skip']}")
    st.divider()

    _highlight_reason(row.get('tagging_notes'))

    st.markdown("**분류**")
    st.text(f"report_type:     {row.get('report_type')}")
    st.text(f"publisher:       {row.get('publisher')}")
    st.text(f"publisher_type:  {row.get('publisher_type')}")
    st.text(f"confidence:      {row.get('tagging_confidence')}")

    st.markdown("**종목 매핑**")
    st.text(f"codes (LLM raw):  {row.get('stock_codes_raw')}")
    st.text(f"codes (KRX):      {row.get('stock_codes')}")
    st.text(f"names (LLM raw):  {row.get('company_names_raw')}")
    st.text(f"names (KRX):      {row.get('company_names')}")

    st.markdown("**섹터 / 제품**")
    st.text(f"sectors_major: {row.get('sectors_major')}")
    st.text(f"sectors_minor: {row.get('sectors_minor')}")
    st.text(f"products:      {row.get('products')}")

    with st.expander("메시지 메타"):
        st.text(f"file_name: {row.get('file_name')}")
        st.text(f"sent_at:   {row.get('sent_at')}")
        st.text(f"caption:   {row.get('caption')}")

    st.divider()

    # Action buttons
    snapshot = capture_snapshot(row)
    rid = int(row['id'])

    bv, bo, br, bs = st.columns([1, 1, 1, 1])

    if bv.button("✓ verified", type="primary", width="stretch"):
        db.mark_verified(rid, payload=build_verified_payload(row))
        st.session_state.last_snapshot = (rid, snapshot)
        st.session_state.counts['verified'] += 1
        st.rerun()

    with bo:
        reason = st.selectbox(
            "OOS reason", V2_OOS_REASONS, key=f"oos_reason_{rid}",
            label_visibility='collapsed',
        )
        if st.button("✗ OOS", width="stretch", key=f"oos_btn_{rid}"):
            db.mark_oos(rid, payload=build_oos_payload(row, reason=reason))
            st.session_state.last_snapshot = (rid, snapshot)
            st.session_state.counts['oos'] += 1
            st.rerun()

    if br.button("↺ re-tag", width="stretch"):
        db.mark_pending(rid)
        st.session_state.last_snapshot = (rid, snapshot)
        st.session_state.counts['retag'] += 1
        st.rerun()

    if bs.button("↻ skip", width="stretch"):
        st.session_state.skipped_ids.add(rid)
        st.session_state.counts['skip'] += 1
        st.rerun()

    # Undo
    if st.session_state.last_snapshot is not None:
        last_id, last_snap = st.session_state.last_snapshot
        if st.button(f"↶ undo last (id={last_id})"):
            db.restore_snapshot(last_id, snapshot=last_snap)
            st.session_state.last_snapshot = None
            # If the undone id was in skipped, take it back out so it reappears
            st.session_state.skipped_ids.discard(last_id)
            st.rerun()
