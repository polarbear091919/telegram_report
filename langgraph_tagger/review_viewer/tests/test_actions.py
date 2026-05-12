import pytest

from langgraph_tagger.review_viewer.actions import (
    SNAPSHOT_COLUMNS,
    capture_snapshot,
    build_verified_payload,
    build_oos_payload,
    build_pending_reset_payload,
)


def make_row(**overrides):
    """Factory for a representative review_needed row dict (supabase-py response shape)."""
    base = {
        # original meta — must NEVER appear in snapshot or payload
        'id': 1234,
        'message_id': 124784,
        'chat_username': 'sunstudy1004',
        'file_path': '124784_some.pdf',
        'file_name': 'some.pdf',
        'file_size_bytes': 12345,
        'file_hash_sha256': 'a' * 64,
        'caption': 'Sample',
        'downloaded_at': '2026-05-07T08:04:14+00:00',
        'sent_at': '2026-05-07T08:04:14+00:00',
        # analysis body
        'published_at': '2026-05-07',
        'report_type': '단일종목',
        'publisher': '삼성증권',
        'publisher_type': 'broker',
        'analysts': ['홍길동'],
        'title': '삼성전자 Q1',
        'stock_codes': ['005930'],
        'company_names': ['삼성전자'],
        'stock_codes_raw': ['005935'],
        'company_names_raw': ['삼성전자우'],
        'sectors_major': ['반도체'],
        'sectors_minor': ['메모리'],
        'products': ['DRAM'],
        'out_of_scope_reason': None,
        # tagging meta
        'tagging_status': 'review_needed',
        'tagging_confidence': 'medium',
        'tagging_notes': 'krx_unmatched_in_scope',
        'tagged_at': '2026-05-07T08:30:00+00:00',
        'tagger_version': 'langgraph-tagger@2.0',
        'taxonomy_version': 'KRX@2026-05-08',
        'tagging_locked_at': None,
        'tagging_worker_id': None,
    }
    base.update(overrides)
    return base


# === SNAPSHOT_COLUMNS ===

def test_snapshot_columns_excludes_original_meta():
    """Original / message / file meta must never be in the allowlist —
    undo restores tagging state only, not the row's identity."""
    forbidden = {
        'id', 'message_id', 'chat_username', 'file_path', 'file_name',
        'file_size_bytes', 'file_hash_sha256', 'caption',
        'downloaded_at', 'sent_at',
    }
    assert forbidden.isdisjoint(set(SNAPSHOT_COLUMNS))


def test_snapshot_columns_covers_all_action_writes():
    """All columns that any action writes must be in the allowlist —
    otherwise undo can't restore them."""
    expected = {
        # analysis
        'published_at', 'report_type', 'publisher', 'publisher_type',
        'analysts', 'title', 'stock_codes', 'company_names',
        'stock_codes_raw', 'company_names_raw',
        'sectors_major', 'sectors_minor', 'products',
        'out_of_scope_reason',
        # tagging meta
        'tagging_status', 'tagging_confidence', 'tagging_notes',
        'tagged_at', 'tagger_version', 'taxonomy_version',
        'tagging_locked_at', 'tagging_worker_id',
    }
    assert set(SNAPSHOT_COLUMNS) == expected


# === capture_snapshot ===

def test_capture_snapshot_picks_only_allowlist():
    row = make_row()
    snap = capture_snapshot(row)
    assert set(snap.keys()) == set(SNAPSHOT_COLUMNS)
    assert snap['tagging_status'] == 'review_needed'
    assert snap['tagging_notes'] == 'krx_unmatched_in_scope'
    # original meta must not leak
    assert 'message_id' not in snap
    assert 'file_path' not in snap


# === build_verified_payload ===

def test_build_verified_payload_only_changes_status():
    row = make_row()
    payload = build_verified_payload(row)
    assert payload == {'tagging_status': 'verified'}


# === build_oos_payload ===

def test_build_oos_payload_matches_write_node_semantics():
    """OOS payload must mirror langgraph_tagger/nodes/write.py OOS branch:
    - tagging_status='verified' (manual review concluded)
    - out_of_scope_reason=<reason>
    - analysis-body fields cleared (stock_codes/names/sectors/products, published_at)
    - LLM classification preserved (report_type, publisher, title, analysts, *_raw)
    """
    row = make_row()
    payload = build_oos_payload(row, reason='foreign')

    assert payload['tagging_status'] == 'verified'
    assert payload['out_of_scope_reason'] == 'foreign'
    # cleared:
    assert payload['published_at'] is None
    assert payload['stock_codes'] == []
    assert payload['company_names'] == []
    assert payload['sectors_major'] == []
    assert payload['sectors_minor'] == []
    assert payload['products'] == []
    # preserved (from row):
    assert payload['report_type'] == '단일종목'
    assert payload['publisher'] == '삼성증권'
    assert payload['publisher_type'] == 'broker'
    assert payload['title'] == '삼성전자 Q1'
    assert payload['analysts'] == ['홍길동']
    assert payload['stock_codes_raw'] == ['005935']
    assert payload['company_names_raw'] == ['삼성전자우']


def test_build_oos_payload_rejects_unknown_reason():
    row = make_row()
    with pytest.raises(ValueError):
        build_oos_payload(row, reason='not_a_real_reason')


def test_build_oos_payload_accepts_all_v2_reasons():
    row = make_row()
    for reason in ('foreign', 'fund', 'digital', 'private', 'ir_self'):
        p = build_oos_payload(row, reason=reason)
        assert p['out_of_scope_reason'] == reason


# === build_pending_reset_payload ===

def test_build_pending_reset_clears_analysis_and_meta():
    """Re-tag must mirror migration 003's reset: every analysis column +
    every tagging-meta column gets emptied/nulled."""
    payload = build_pending_reset_payload()
    # status / meta
    assert payload['tagging_status'] == 'pending'
    assert payload['tagging_locked_at'] is None
    assert payload['tagging_worker_id'] is None
    assert payload['tagged_at'] is None
    assert payload['tagging_notes'] is None
    assert payload['tagging_confidence'] is None
    assert payload['tagger_version'] is None
    assert payload['taxonomy_version'] is None
    # analysis
    assert payload['published_at'] is None
    assert payload['report_type'] is None
    assert payload['publisher'] is None
    assert payload['publisher_type'] is None
    assert payload['analysts'] == []
    assert payload['title'] is None
    assert payload['stock_codes'] == []
    assert payload['company_names'] == []
    assert payload['stock_codes_raw'] == []
    assert payload['company_names_raw'] == []
    assert payload['sectors_major'] == []
    assert payload['sectors_minor'] == []
    assert payload['products'] == []
    assert payload['out_of_scope_reason'] is None


def test_build_pending_reset_does_not_touch_original_meta():
    payload = build_pending_reset_payload()
    forbidden = {
        'id', 'message_id', 'chat_username', 'file_path', 'file_name',
        'file_size_bytes', 'file_hash_sha256', 'caption',
        'downloaded_at', 'sent_at',
    }
    assert forbidden.isdisjoint(set(payload.keys()))


# === snapshot round-trip ===

def test_snapshot_restore_round_trip():
    """The snapshot returned by capture_snapshot must be applicable as an
    UPDATE payload that restores the row state."""
    row = make_row()
    snap = capture_snapshot(row)
    # Sanity: applying snap as payload would set every allowlist field back
    # to its original. Field-by-field equality.
    for col in SNAPSHOT_COLUMNS:
        assert snap[col] == row[col], f"round-trip failed for {col}"
