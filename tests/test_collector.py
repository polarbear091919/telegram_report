"""Tests for collector.run — the two-phase orchestration logic."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from collector import RunResult, run
from tests.conftest import FakeStorage, FakeTelegramClient, make_msg


@pytest.fixture
def cfg():
    """Minimal config-shaped object."""
    from types import SimpleNamespace
    return SimpleNamespace(telegram_channel='samstudy1004', initial_cutoff_days=30)


# === First-run behavior ===

@pytest.mark.asyncio
async def test_first_run_uses_iter_since_date(fake_client, fake_storage, cfg):
    fake_client.new_messages = [make_msg(101)]
    # max_seen=0 → first run path
    result = await run(fake_client, fake_storage, cfg)
    assert ('iter_since_date', 'samstudy1004', 30) in fake_client.calls


@pytest.mark.asyncio
async def test_subsequent_run_uses_iter_after_id(fake_client, fake_storage, cfg):
    fake_storage._max_seen = 100
    fake_client.new_messages = [make_msg(101)]
    await run(fake_client, fake_storage, cfg)
    assert ('iter_after_id', 'samstudy1004', 100) in fake_client.calls


# === Stage B: new-message processing ===

@pytest.mark.asyncio
async def test_new_pdf_message_is_downloaded_and_inserted(fake_client, fake_storage, cfg):
    msg = make_msg(101, file_name='samsung_q1.pdf', caption='삼성전자 Q1 실적')
    fake_client.new_messages = [msg]

    result = await run(fake_client, fake_storage, cfg)

    assert result.processed == 1
    assert result.failed == 0
    # File saved with correct name
    assert fake_storage.saved_files[0][0] == '101_samsung_q1.pdf'
    # Metadata inserted with correct keys
    assert len(fake_storage.inserted) == 1
    inserted = fake_storage.inserted[0]
    assert inserted['message_id'] == 101
    assert inserted['chat_username'] == 'samstudy1004'
    assert inserted['file_name'] == 'samsung_q1.pdf'
    assert inserted['file_path'] == '101_samsung_q1.pdf'
    assert inserted['caption'] == '삼성전자 Q1 실적'
    assert 'file_size_bytes' in inserted
    assert 'file_hash_sha256' in inserted
    assert inserted['sent_at'] == msg.date


@pytest.mark.asyncio
async def test_non_pdf_message_is_skipped(fake_client, fake_storage, cfg):
    fake_client.new_messages = [make_msg(101, has_pdf=False)]
    result = await run(fake_client, fake_storage, cfg)
    assert result.processed == 0
    assert result.skipped == 1
    assert fake_storage.inserted == []


@pytest.mark.asyncio
async def test_download_failure_records_failed_attempt(fake_client, fake_storage, cfg):
    fake_client.new_messages = [make_msg(101)]
    fake_client.download_errors[101] = RuntimeError('network glitch')

    result = await run(fake_client, fake_storage, cfg)

    assert result.processed == 0
    assert result.failed == 1
    assert fake_storage.inserted == []
    assert len(fake_storage.failed_upserts) == 1
    chat, mid, err = fake_storage.failed_upserts[0]
    assert chat == 'samstudy1004'
    assert mid == 101
    assert 'network glitch' in err


@pytest.mark.asyncio
async def test_one_failure_does_not_block_other_messages(fake_client, fake_storage, cfg):
    fake_client.new_messages = [make_msg(101), make_msg(102), make_msg(103)]
    fake_client.download_errors[102] = RuntimeError('boom')

    result = await run(fake_client, fake_storage, cfg)

    assert result.processed == 2
    assert result.failed == 1
    inserted_ids = [m['message_id'] for m in fake_storage.inserted]
    assert 101 in inserted_ids
    assert 103 in inserted_ids
    assert 102 not in inserted_ids
    # 102 went to failed_attempts
    assert any(mid == 102 for _, mid, _ in fake_storage.failed_upserts)


# === Stage A: failed-message retry ===

@pytest.mark.asyncio
async def test_failed_message_retried_at_start(fake_client, fake_storage, cfg):
    # 100 was previously failed; we'll retry it successfully
    fake_storage._failed_ids = [100]
    fake_storage._max_seen = 100
    fake_client.failed_lookups[100] = make_msg(100, file_name='retry.pdf')
    # Stage B: nothing new
    fake_client.new_messages = []

    result = await run(fake_client, fake_storage, cfg)

    assert result.retried_success == 1
    # Retry lookup happened
    assert ('get_by_id', 'samstudy1004', 100) in fake_client.calls
    # Insert happened for the retry
    assert any(m['message_id'] == 100 for m in fake_storage.inserted)
    # Failed_attempts row was removed
    assert ('samstudy1004', 100) in fake_storage.failed_removes


@pytest.mark.asyncio
async def test_failed_message_still_failing_increments_attempt(
    fake_client, fake_storage, cfg
):
    fake_storage._failed_ids = [100]
    fake_storage._max_seen = 100
    fake_client.failed_lookups[100] = make_msg(100)
    fake_client.download_errors[100] = RuntimeError('still broken')
    fake_client.new_messages = []

    result = await run(fake_client, fake_storage, cfg)

    assert result.retried_fail == 1
    # No insert
    assert fake_storage.inserted == []
    # Failed_attempts upsert (attempt_count++)
    assert any(mid == 100 for _, mid, _ in fake_storage.failed_upserts)
    # Was NOT removed
    assert ('samstudy1004', 100) not in fake_storage.failed_removes


@pytest.mark.asyncio
async def test_deleted_message_is_cleaned_from_failed_attempts(
    fake_client, fake_storage, cfg
):
    fake_storage._failed_ids = [100]
    fake_storage._max_seen = 100
    # Telegram returns None → message was deleted
    fake_client.failed_lookups[100] = None
    fake_client.new_messages = []

    result = await run(fake_client, fake_storage, cfg)

    assert ('samstudy1004', 100) in fake_storage.failed_removes
    assert result.retried_fail == 0
    assert result.retried_success == 0


@pytest.mark.asyncio
async def test_failed_lookup_returning_non_pdf_is_cleaned(
    fake_client, fake_storage, cfg
):
    # Edge case: a message that was once a PDF is now reported as something else
    fake_storage._failed_ids = [100]
    fake_storage._max_seen = 100
    fake_client.failed_lookups[100] = make_msg(100, has_pdf=False)
    fake_client.new_messages = []

    result = await run(fake_client, fake_storage, cfg)

    assert ('samstudy1004', 100) in fake_storage.failed_removes


# === RunResult shape ===

@pytest.mark.asyncio
async def test_run_returns_run_result_with_all_counters(fake_client, fake_storage, cfg):
    result = await run(fake_client, fake_storage, cfg)
    assert isinstance(result, RunResult)
    for attr in ('processed', 'skipped', 'failed', 'retried_success', 'retried_fail'):
        assert hasattr(result, attr)
        assert getattr(result, attr) == 0
