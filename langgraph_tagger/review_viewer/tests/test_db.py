from unittest.mock import MagicMock

import pytest

from langgraph_tagger.review_viewer.db import ReviewDB


# === count_review_queue ===

def test_count_review_queue_uses_status_filter():
    client = MagicMock()
    table = client.table.return_value
    table.select.return_value.eq.return_value.execute.return_value = MagicMock(count=42)

    db = ReviewDB(client)
    n = db.count_review_queue()

    assert n == 42
    client.table.assert_called_with('reports')
    table.select.assert_called_with('id', count='exact')
    table.select.return_value.eq.assert_called_with('tagging_status', 'review_needed')


# === fetch_next_review ===

def test_fetch_next_review_orders_by_tagged_at_asc():
    client = MagicMock()
    chain = (client.table.return_value
                       .select.return_value
                       .eq.return_value
                       .order.return_value
                       .limit.return_value)
    chain.execute.return_value = MagicMock(data=[{'id': 1, 'tagging_notes': 'krx_unmatched_in_scope'}])

    db = ReviewDB(client)
    row = db.fetch_next_review(skipped_ids=set())

    assert row['id'] == 1
    chain_root = client.table.return_value.select.return_value.eq.return_value
    chain_root.order.assert_called_with('tagged_at', desc=False)


def test_fetch_next_review_excludes_skipped():
    client = MagicMock()
    chain = (client.table.return_value
                       .select.return_value
                       .eq.return_value
                       .not_.return_value
                       .in_.return_value
                       .order.return_value
                       .limit.return_value)
    chain.execute.return_value = MagicMock(data=[{'id': 7}])

    db = ReviewDB(client)
    row = db.fetch_next_review(skipped_ids={1, 2, 3})

    assert row['id'] == 7
    not_in_args = client.table.return_value.select.return_value.eq.return_value.not_.return_value.in_.call_args
    assert not_in_args.args[0] == 'id'
    assert set(not_in_args.args[1]) == {1, 2, 3}


def test_fetch_next_review_returns_none_when_empty():
    client = MagicMock()
    chain = (client.table.return_value
                       .select.return_value
                       .eq.return_value
                       .order.return_value
                       .limit.return_value)
    chain.execute.return_value = MagicMock(data=[])
    db = ReviewDB(client)
    assert db.fetch_next_review(set()) is None


# === mark_verified ===

def test_mark_verified_updates_status_only():
    client = MagicMock()
    chain = client.table.return_value.update.return_value.eq.return_value
    chain.execute.return_value = MagicMock()

    db = ReviewDB(client)
    db.mark_verified(123, payload={'tagging_status': 'verified'})

    client.table.return_value.update.assert_called_with({'tagging_status': 'verified'})
    client.table.return_value.update.return_value.eq.assert_called_with('id', 123)


# === mark_oos ===

def test_mark_oos_updates_full_payload():
    client = MagicMock()
    chain = client.table.return_value.update.return_value.eq.return_value
    chain.execute.return_value = MagicMock()

    payload = {
        'tagging_status': 'verified',
        'out_of_scope_reason': 'foreign',
        'stock_codes': [],
        'report_type': '단일종목',
    }

    db = ReviewDB(client)
    db.mark_oos(456, payload=payload)

    client.table.return_value.update.assert_called_with(payload)
    client.table.return_value.update.return_value.eq.assert_called_with('id', 456)


# === mark_pending ===

def test_mark_pending_resets_all_fields():
    """mark_pending must use the reset payload from actions.build_pending_reset_payload."""
    from langgraph_tagger.review_viewer.actions import build_pending_reset_payload

    client = MagicMock()
    client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    db = ReviewDB(client)
    db.mark_pending(789)

    expected = build_pending_reset_payload()
    client.table.return_value.update.assert_called_with(expected)
    client.table.return_value.update.return_value.eq.assert_called_with('id', 789)


# === restore_snapshot ===

def test_restore_snapshot_applies_allowlist_only():
    from langgraph_tagger.review_viewer.actions import SNAPSHOT_COLUMNS

    client = MagicMock()
    client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    snapshot = {col: f"val_{col}" for col in SNAPSHOT_COLUMNS}
    # add a forbidden key — must not be passed to update
    snapshot_with_leak = {**snapshot, 'message_id': 999, 'file_path': 'leak.pdf'}

    db = ReviewDB(client)
    db.restore_snapshot(321, snapshot=snapshot_with_leak)

    update_arg = client.table.return_value.update.call_args.args[0]
    assert set(update_arg.keys()) == set(SNAPSHOT_COLUMNS)
    assert 'message_id' not in update_arg
    assert 'file_path' not in update_arg
    client.table.return_value.update.return_value.eq.assert_called_with('id', 321)
