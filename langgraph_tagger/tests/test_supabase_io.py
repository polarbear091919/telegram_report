"""Smoke tests for SQL constants — no live DB."""
from langgraph_tagger.supabase_io import (
    ATOMIC_CLAIM_SQL, DRY_RUN_SELECT_SQL, ESCALATION_PICK_SQL,
    INSPECT_SUMMARY_SQL, REVERT_TO_PENDING_SQL, ROW_IDS_FETCH_SQL,
    STALE_LOCK_RECLAIM_SQL, UPDATE_SQL,
)


def test_atomic_claim_uses_skip_locked():
    assert "FOR UPDATE SKIP LOCKED" in ATOMIC_CLAIM_SQL
    assert "tagging_status='processing'" in ATOMIC_CLAIM_SQL


def test_stale_reclaim_uses_param_threshold():
    # Threshold is parameterized via $1::int (LOCK_TTL_MINUTES from env), not hardcoded.
    assert "$1::int * interval '1 minute'" in STALE_LOCK_RECLAIM_SQL


def test_dry_run_select_does_not_mutate():
    assert "UPDATE" not in DRY_RUN_SELECT_SQL


def test_update_has_18_bound_params():
    # Count $N placeholders
    import re
    params = sorted(set(int(m) for m in re.findall(r"\$(\d+)", UPDATE_SQL)))
    assert params == list(range(1, 19))


def test_escalation_pick_filters_by_status_and_date():
    assert "tagging_status='review_needed'" in ESCALATION_PICK_SQL
    assert "$1" in ESCALATION_PICK_SQL


def test_revert_only_acts_on_processing():
    assert "tagging_status='processing'" in REVERT_TO_PENDING_SQL
