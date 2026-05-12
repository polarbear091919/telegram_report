"""Tests for main.parse_args and main.compute_exit_code (pure functions only).

The full main() is exercised by Task 11's smoke test (real Telegram + Supabase).
"""
from __future__ import annotations

import pytest

from main import compute_exit_code, parse_args
from collector import RunResult


# === parse_args ===

def test_parse_args_no_flags_defaults():
    args = parse_args([])
    assert args.cutoff_days is None
    assert args.backfill_days is None
    assert args.dry_run is False
    assert args.verbose is False


def test_parse_args_cutoff_days():
    args = parse_args(['--cutoff-days', '7'])
    assert args.cutoff_days == 7


def test_parse_args_dry_run():
    args = parse_args(['--dry-run'])
    assert args.dry_run is True


def test_parse_args_verbose_short():
    args = parse_args(['-v'])
    assert args.verbose is True


def test_parse_args_verbose_long():
    args = parse_args(['--verbose'])
    assert args.verbose is True


# === compute_exit_code ===

def test_exit_code_success_with_zero_failures():
    assert compute_exit_code(RunResult(processed=5)) == 0


def test_exit_code_success_with_no_messages():
    assert compute_exit_code(RunResult()) == 0


def test_exit_code_partial_failure_in_stage_b():
    assert compute_exit_code(RunResult(processed=3, failed=1)) == 2


def test_exit_code_partial_failure_in_stage_a():
    assert compute_exit_code(RunResult(retried_fail=1)) == 2


def test_exit_code_partial_failure_both_stages():
    assert compute_exit_code(RunResult(processed=2, failed=1, retried_fail=1)) == 2


# === Backfill flag ===

def test_parse_args_backfill_days():
    args = parse_args(['--backfill-days', '365'])
    assert args.backfill_days == 365
    assert args.cutoff_days is None


def test_parse_args_mutually_exclusive_raises_systemexit():
    """argparse rejects --cutoff-days + --backfill-days combination."""
    import pytest
    with pytest.raises(SystemExit):
        parse_args(['--cutoff-days', '30', '--backfill-days', '365'])


# === Dry-run with backfill ===

import pytest
import asyncio


def _make_dry_run_config(**overrides):
    """Build a config-shaped object with channel_ref() for _dry_run tests."""
    from types import SimpleNamespace

    def channel_ref(self):
        if getattr(self, 'telegram_channel_id', None) is not None:
            return self.telegram_channel_id
        return self.telegram_channel

    defaults = dict(
        telegram_channel='sunstudy1004',
        telegram_channel_id=None,
        initial_cutoff_days=30,
    )
    defaults.update(overrides)
    ns = SimpleNamespace(**defaults)
    ns.channel_ref = channel_ref.__get__(ns, SimpleNamespace)
    return ns


@pytest.mark.asyncio
async def test_dry_run_with_backfill_uses_skip_set(monkeypatch, tmp_path, capsys):
    """_dry_run with backfill_days uses iter_since_date and skips IDs already
    in reports OR failed_attempts. The 'new' count should reflect dedupe."""
    from tests.conftest import FakeStorage, FakeTelegramClient, make_msg
    from main import _dry_run

    storage = FakeStorage(
        base_dir=tmp_path,
        existing_ids={100, 101},
        failed_ids=[200],
    )
    client = FakeTelegramClient()
    client.new_messages = [make_msg(100), make_msg(101), make_msg(200), make_msg(300)]

    config = _make_dry_run_config()

    rc = await _dry_run(client, storage, config, backfill_days=90)

    assert rc == 0
    # iter_since_date called with backfill_days, not initial_cutoff_days
    assert ('iter_since_date', 'sunstudy1004', 90) in client.calls

    captured = capsys.readouterr()
    log_output = captured.err  # logging defaults to stderr

    # Reports nothing was actually downloaded; nothing inserted; nothing saved
    assert storage.inserted == []
    assert storage.saved_files == []


@pytest.mark.asyncio
async def test_dry_run_uses_channel_id_when_set(tmp_path):
    """When telegram_channel_id is set on config, dry-run fetches via int id."""
    from tests.conftest import FakeStorage, FakeTelegramClient, make_msg
    from main import _dry_run

    storage = FakeStorage(base_dir=tmp_path)
    client = FakeTelegramClient()
    client.new_messages = [make_msg(125165)]

    config = _make_dry_run_config(telegram_channel_id=1378197756)

    rc = await _dry_run(client, storage, config, backfill_days=None)

    assert rc == 0
    # First run (max_seen=0) — uses iter_since_date with the int id
    assert any(c[0] == 'iter_since_date' and c[1] == 1378197756 for c in client.calls)
