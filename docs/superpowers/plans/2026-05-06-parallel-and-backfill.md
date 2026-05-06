# Parallel Downloads + Backfill Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parallelize the existing collector via `asyncio.Semaphore` (~3x speedup on normal runs) and add a `--backfill-days N` mode that fetches historical messages while skipping already-attempted ones (success + still-failing). Pre-fetch dedupe sets are paginated to overcome Supabase's default 1000-row response limit.

**Architecture:** Five existing files modified (`config.py`, `storage.py`, `collector.py`, `main.py`, `tests/conftest.py`); no new modules. Concurrency: `asyncio.Semaphore(N=config.max_concurrent_downloads)` shared by Stage A (failed-attempt retry) and Stage B (new-message fetch). Backfill mode: pre-fetch `existing_ids = reports IDs ∪ failed_attempts IDs` AFTER Stage A, then iter-since-date and skip pre-known IDs. `_process_one_message` unchanged (already concurrent-safe via atomic file rename + UPSERT).

**Tech Stack:** Python 3.10+, Telethon 1.x, supabase-py 2.x (paginated via `.range()`), pytest + pytest-asyncio. Reference spec: `docs/superpowers/specs/2026-05-06-parallel-and-backfill-design.md`.

---

## File Structure (post-implementation)

```
telegram_report/
├── config.py             # +1 field, +1 line in load_config
├── storage.py            # 2 methods (get_all_message_ids new, get_failed_message_ids paginated)
├── collector.py          # run() signature + Semaphore + backfill branch + dedupe set
├── main.py               # argparse mutually_exclusive + _dry_run extension
├── .env.example          # +1 commented line documenting MAX_CONCURRENT_DOWNLOADS
├── README.md             # +1 short paragraph documenting --backfill-days and concurrency tuning
└── tests/
    ├── conftest.py       # +TrackingFakeClient, +existing_ids field on FakeStorage,
    │                     # +get_all_message_ids on FakeStorage
    ├── test_config.py    # +2 tests
    ├── test_main.py      # +3 tests, +1 small fixture update
    └── test_collector.py # +5 backfill tests + 2 concurrency tests, cfg fixture updated
```

**Module responsibilities (unchanged from base spec)**: see `docs/superpowers/specs/2026-05-05-telegram-report-collector-design.md` §1.1.

---

## Tasks

### Task 1: Config — `max_concurrent_downloads` field (TDD)

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config.py` (after existing tests):

```python
def test_load_config_max_concurrent_downloads_default(monkeypatch):
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'c')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.delenv('MAX_CONCURRENT_DOWNLOADS', raising=False)

    cfg = load_config()

    assert cfg.max_concurrent_downloads == 4


def test_load_config_max_concurrent_downloads_override(monkeypatch):
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'c')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.setenv('MAX_CONCURRENT_DOWNLOADS', '8')

    cfg = load_config()

    assert cfg.max_concurrent_downloads == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: 2 new tests FAIL with `AttributeError: 'Config' object has no attribute 'max_concurrent_downloads'`. Existing 3 PASS.

- [ ] **Step 3: Implement in `config.py`**

Add new field to `Config` dataclass (preserve alphabetical or logical grouping; here we put it near other tunables):

Find:
```python
@dataclass(frozen=True)
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_channel: str
    telegram_session_path: Path
    supabase_url: str
    supabase_service_key: str
    storage_base_dir: Path
    initial_cutoff_days: int
    log_level: str
```

Replace with:
```python
@dataclass(frozen=True)
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_channel: str
    telegram_session_path: Path
    supabase_url: str
    supabase_service_key: str
    storage_base_dir: Path
    initial_cutoff_days: int
    max_concurrent_downloads: int
    log_level: str
```

In `load_config()`, find:
```python
        storage_base_dir=Path(os.getenv('STORAGE_BASE_DIR', './reports')),
        initial_cutoff_days=int(os.getenv('INITIAL_CUTOFF_DAYS', '30')),
        log_level=os.getenv('LOG_LEVEL', 'INFO'),
```

Replace with:
```python
        storage_base_dir=Path(os.getenv('STORAGE_BASE_DIR', './reports')),
        initial_cutoff_days=int(os.getenv('INITIAL_CUTOFF_DAYS', '30')),
        max_concurrent_downloads=int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '4')),
        log_level=os.getenv('LOG_LEVEL', 'INFO'),
```

- [ ] **Step 4: Update `.env.example`**

Find:
```bash
# === 선택: 기본값 사용하려면 비워두면 됨 ===
# TELEGRAM_SESSION_NAME=samstudy
# STORAGE_BASE_DIR=./reports
# INITIAL_CUTOFF_DAYS=30
# LOG_LEVEL=INFO
```

Replace with:
```bash
# === 선택: 기본값 사용하려면 비워두면 됨 ===
# TELEGRAM_SESSION_NAME=samstudy
# STORAGE_BASE_DIR=./reports
# INITIAL_CUTOFF_DAYS=30
# MAX_CONCURRENT_DOWNLOADS=4   # 동시 다운로드 수. 백필 시 8 권장. FloodWait 자주 뜨면 줄이세요.
# LOG_LEVEL=INFO
```

- [ ] **Step 5: Update existing happy-path test for new field**

In `tests/test_config.py`, find the existing `test_load_config_happy_path`:

```python
    # Defaults
    assert cfg.telegram_session_path == Path('sessions') / 'samstudy'
    assert cfg.storage_base_dir == Path('./reports')
    assert cfg.initial_cutoff_days == 30
    assert cfg.log_level == 'INFO'
```

Replace with:

```python
    # Defaults
    assert cfg.telegram_session_path == Path('sessions') / 'samstudy'
    assert cfg.storage_base_dir == Path('./reports')
    assert cfg.initial_cutoff_days == 30
    assert cfg.max_concurrent_downloads == 4
    assert cfg.log_level == 'INFO'
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: 5/5 PASS (3 existing + 2 new).

- [ ] **Step 7: Run full test suite**

Run: `.venv/Scripts/pytest tests/ -v 2>&1 | tail -5`
Expected: All 50 PASS (Config-using fixtures elsewhere will not be affected since `cfg` in test_collector.py uses SimpleNamespace, not Config).

- [ ] **Step 8: Commit**

```bash
git add config.py tests/test_config.py .env.example
git commit -m "feat: add MAX_CONCURRENT_DOWNLOADS env var with default 4"
```

---

### Task 2: Storage — paginated `get_all_message_ids` + paginated `get_failed_message_ids`

**Files:**
- Modify: `storage.py`

No unit tests added (matches Task 7 of the original plan: `Storage` Supabase methods rely on smoke tests, since the chained-builder API mocking is awkward and provides little verification value over real exercise). Task 7 of THIS plan (smoke test) verifies behavior.

- [ ] **Step 1: Add `get_all_message_ids` to `Storage` class**

In `storage.py`, locate the existing `get_failed_message_ids` method inside the `Storage` class. Insert this new method directly above it:

```python
    def get_all_message_ids(self, chat_username: str) -> set[int]:
        """Return ALL message_ids already in reports for this chat.

        Pages through results explicitly because PostgREST/Supabase enforces a
        default max of 1000 rows per request — without pagination, this returns
        an incomplete set once the table exceeds that, breaking backfill dedupe
        (spec §3.1).
        """
        PAGE_SIZE = 1000
        ids: set[int] = set()
        offset = 0
        while True:
            result = (
                self._sb.table('reports')
                .select('message_id')
                .eq('chat_username', chat_username)
                .order('message_id')  # stable order for predictable paging
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            batch = result.data or []
            ids.update(int(row['message_id']) for row in batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        return ids
```

- [ ] **Step 2: Replace `get_failed_message_ids` with paginated version**

Find the existing implementation:

```python
    def get_failed_message_ids(self, chat_username: str) -> list[int]:
        """Return all message_ids currently in failed_attempts for this chat (oldest first)."""
        result = (
            self._sb.table('failed_attempts')
            .select('message_id')
            .eq('chat_username', chat_username)
            .order('message_id', desc=False)
            .execute()
        )
        return [int(row['message_id']) for row in (result.data or [])]
```

Replace with:

```python
    def get_failed_message_ids(self, chat_username: str) -> list[int]:
        """Return all message_ids currently in failed_attempts for this chat (oldest first).

        Paginates to defeat Supabase's default 1000-row response limit
        (spec §3.2). Same pattern as get_all_message_ids.
        """
        PAGE_SIZE = 1000
        ids: list[int] = []
        offset = 0
        while True:
            result = (
                self._sb.table('failed_attempts')
                .select('message_id')
                .eq('chat_username', chat_username)
                .order('message_id', desc=False)
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            batch = result.data or []
            ids.extend(int(row['message_id']) for row in batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        return ids
```

(Signature unchanged — return is still `list[int]`, oldest-first.)

- [ ] **Step 3: Run full test suite to verify no regressions**

Run: `.venv/Scripts/pytest tests/ -v 2>&1 | tail -5`
Expected: All 50 still PASS. The paginated version is a drop-in replacement; existing collector tests use `FakeStorage.get_failed_message_ids` (which is unaffected) so they don't exercise the paging code.

- [ ] **Step 4: Commit**

```bash
git add storage.py
git commit -m "feat(storage): paginate get_all_message_ids and get_failed_message_ids

Adds new get_all_message_ids method and re-implements
get_failed_message_ids with the same pagination loop. Both use
.range(offset, offset+999) + .order('message_id') and stop when
batch < PAGE_SIZE. Required because Supabase enforces a default
1000-row response cap that would otherwise truncate the backfill
dedupe set (spec §3.1, §3.2)."
```

---

### Task 3: Collector — Parallelize Stage A + Stage B with Semaphore (TDD)

**Files:**
- Modify: `tests/conftest.py` (add `TrackingFakeClient`, update fixtures)
- Modify: `tests/test_collector.py` (update local `cfg` fixture, add 2 concurrency tests)
- Modify: `collector.py` (add Semaphore, parallelize both stages)

No new behavior other than parallelism. Backfill comes in Task 4. The 11 existing tests should still pass after this task.

- [ ] **Step 1: Add `TrackingFakeClient` to `tests/conftest.py`**

Insert this class definition AFTER the existing `FakeTelegramClient` class (and before the `FakeStorage` class):

```python
class TrackingFakeClient(FakeTelegramClient):
    """FakeTelegramClient that records max concurrent download_pdf_bytes calls.

    Used by concurrency tests to observe whether the collector's Semaphore
    bound is honored.
    """

    def __init__(self) -> None:
        super().__init__()
        self.current_concurrent = 0
        self.max_concurrent_observed = 0

    async def download_pdf_bytes(self, msg) -> bytes:
        self.calls.append(('download', msg.id))
        self.current_concurrent += 1
        self.max_concurrent_observed = max(
            self.max_concurrent_observed, self.current_concurrent
        )
        # Yield to other tasks so concurrency can actually be observed
        import asyncio
        await asyncio.sleep(0.01)
        self.current_concurrent -= 1
        if msg.id in self.download_errors:
            raise self.download_errors[msg.id]
        return self.download_results.get(msg.id, b'fake pdf bytes')
```

- [ ] **Step 2: Update `cfg` fixture in `tests/test_collector.py`**

Find:

```python
@pytest.fixture
def cfg():
    """Minimal config-shaped object."""
    from types import SimpleNamespace
    return SimpleNamespace(telegram_channel='sunstudy1004', initial_cutoff_days=30)
```

Replace with:

```python
@pytest.fixture
def cfg():
    """Minimal config-shaped object."""
    from types import SimpleNamespace
    return SimpleNamespace(
        telegram_channel='sunstudy1004',
        initial_cutoff_days=30,
        max_concurrent_downloads=4,
    )
```

- [ ] **Step 3: Add 2 concurrency tests to `tests/test_collector.py`**

Append at the end of `tests/test_collector.py`:

```python
# === Concurrency observation ===

@pytest.mark.asyncio
async def test_concurrency_respects_semaphore_limit(fake_storage):
    """With N=3 and 10 messages, max concurrent downloads should be at most 3
    AND at least 2 (proving real parallelism)."""
    from types import SimpleNamespace
    from tests.conftest import TrackingFakeClient

    cfg = SimpleNamespace(
        telegram_channel='sunstudy1004',
        initial_cutoff_days=30,
        max_concurrent_downloads=3,
    )
    client = TrackingFakeClient()
    client.new_messages = [make_msg(100 + i) for i in range(10)]

    await run(client, fake_storage, cfg)

    assert client.max_concurrent_observed <= 3, \
        f"Semaphore breach: {client.max_concurrent_observed} > 3"
    assert client.max_concurrent_observed >= 2, \
        f"No real parallelism observed (max={client.max_concurrent_observed})"


@pytest.mark.asyncio
async def test_concurrency_n1_is_serial(fake_storage):
    """With N=1 (Semaphore(1)), only one download at a time."""
    from types import SimpleNamespace
    from tests.conftest import TrackingFakeClient

    cfg = SimpleNamespace(
        telegram_channel='sunstudy1004',
        initial_cutoff_days=30,
        max_concurrent_downloads=1,
    )
    client = TrackingFakeClient()
    client.new_messages = [make_msg(100 + i) for i in range(5)]

    await run(client, fake_storage, cfg)

    assert client.max_concurrent_observed == 1
```

- [ ] **Step 4: Run new tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_collector.py::test_concurrency_respects_semaphore_limit tests/test_collector.py::test_concurrency_n1_is_serial -v`
Expected: Both FAIL — `test_concurrency_respects_semaphore_limit` because current code is sequential (max_observed will be 1, not ≥2); `test_concurrency_n1_is_serial` may PASS (since current is sequential, N=1 happens to match) but the first one will fail.

- [ ] **Step 5: Implement parallelization in `collector.py`**

Replace the entire body of `async def run(...)` (NOT the helpers) with the parallelized version. Find:

```python
async def run(client: Any, storage: Any, config: Any) -> RunResult:
    """Run one collection cycle for the configured channel.

    Stage A: re-attempt every msg_id currently in failed_attempts.
    Stage B: fetch messages with id > max_seen and process them.
    """
    channel = config.telegram_channel

    # === Stage A: retry past failures ===
    failed_ids = storage.get_failed_message_ids(channel)
    log.info("Stage A: retrying %d previously failed messages", len(failed_ids))
    retried_success = 0
    retried_fail = 0
    for msg_id in failed_ids:
        msg = await client.get_message_by_id(channel, msg_id)
        if msg is None or not has_pdf(msg):
            log.info("Cleaning failed_attempts row for msg_id=%s (deleted or not PDF)", msg_id)
            storage.remove_failed_attempt(channel, msg_id)
            continue
        try:
            await _process_one_message(client, storage, channel, msg)
            storage.remove_failed_attempt(channel, msg_id)
            retried_success += 1
        except Exception as e:
            log.exception("Retry still failing for msg_id=%s", msg_id)
            new_count = storage.upsert_failed_attempt(channel, msg_id, str(e))
            if new_count >= ATTEMPT_WARN_THRESHOLD:
                log.warning("msg_id=%s has failed %d times — investigate manually",
                            msg_id, new_count)
            retried_fail += 1

    # === Stage B: fetch new messages ===
    last_seen = storage.get_max_seen_message_id(channel)
    log.info("Stage B: last_seen_message_id=%s", last_seen)

    if last_seen == 0:
        log.info("First run; using cutoff=%d days", config.initial_cutoff_days)
        message_iter = client.iter_messages_since_date(channel, config.initial_cutoff_days)
    else:
        message_iter = client.iter_messages_after_id(channel, last_seen)

    processed = 0
    skipped = 0
    failed = 0
    async for msg in message_iter:
        if not has_pdf(msg):
            skipped += 1
            continue
        try:
            await _process_one_message(client, storage, channel, msg)
            processed += 1
        except Exception as e:
            log.exception("Failed to process message_id=%s", msg.id)
            new_count = storage.upsert_failed_attempt(channel, msg.id, str(e))
            if new_count >= ATTEMPT_WARN_THRESHOLD:
                log.warning("msg_id=%s has failed %d times — investigate manually",
                            msg.id, new_count)
            failed += 1

    log.info(
        "Run complete. Stage A: retried_success=%d retried_fail=%d. "
        "Stage B: processed=%d skipped=%d failed=%d",
        retried_success, retried_fail, processed, skipped, failed,
    )
    return RunResult(
        processed=processed,
        skipped=skipped,
        failed=failed,
        retried_success=retried_success,
        retried_fail=retried_fail,
    )
```

Replace with:

```python
async def run(client: Any, storage: Any, config: Any) -> RunResult:
    """Run one collection cycle for the configured channel.

    Stage A: re-attempt every msg_id currently in failed_attempts (parallelized).
    Stage B: fetch messages with id > max_seen and process them (parallelized).

    Both stages share a single Semaphore so total concurrent downloads
    cannot exceed config.max_concurrent_downloads.
    """
    import asyncio

    channel = config.telegram_channel
    sem = asyncio.Semaphore(config.max_concurrent_downloads)

    # === Stage A: retry past failures (parallel) ===
    failed_ids = storage.get_failed_message_ids(channel)
    log.info("Stage A: retrying %d previously failed messages (concurrency=%d)",
             len(failed_ids), config.max_concurrent_downloads)

    async def retry_one(msg_id: int) -> str:
        async with sem:
            msg = await client.get_message_by_id(channel, msg_id)
            if msg is None or not has_pdf(msg):
                log.info("Cleaning failed_attempts row for msg_id=%s (deleted or not PDF)", msg_id)
                storage.remove_failed_attempt(channel, msg_id)
                return 'cleaned'
            try:
                await _process_one_message(client, storage, channel, msg)
                storage.remove_failed_attempt(channel, msg_id)
                return 'success'
            except Exception as e:
                log.exception("Retry still failing for msg_id=%s", msg_id)
                new_count = storage.upsert_failed_attempt(channel, msg_id, str(e))
                if new_count >= ATTEMPT_WARN_THRESHOLD:
                    log.warning("msg_id=%s has failed %d times — investigate manually",
                                msg_id, new_count)
                return 'fail'

    stage_a_results = await asyncio.gather(*[retry_one(mid) for mid in failed_ids])
    retried_success = sum(1 for r in stage_a_results if r == 'success')
    retried_fail = sum(1 for r in stage_a_results if r == 'fail')

    # === Stage B: fetch new messages (parallel) ===
    last_seen = storage.get_max_seen_message_id(channel)
    log.info("Stage B: last_seen_message_id=%s", last_seen)

    if last_seen == 0:
        log.info("First run; using cutoff=%d days", config.initial_cutoff_days)
        message_iter = client.iter_messages_since_date(channel, config.initial_cutoff_days)
    else:
        message_iter = client.iter_messages_after_id(channel, last_seen)

    async def process_new(msg) -> str:
        async with sem:
            try:
                await _process_one_message(client, storage, channel, msg)
                return 'processed'
            except Exception as e:
                log.exception("Failed to process message_id=%s", msg.id)
                new_count = storage.upsert_failed_attempt(channel, msg.id, str(e))
                if new_count >= ATTEMPT_WARN_THRESHOLD:
                    log.warning("msg_id=%s has failed %d times — investigate manually",
                                msg.id, new_count)
                return 'failed'

    tasks = []
    skipped = 0
    async for msg in message_iter:
        if not has_pdf(msg):
            skipped += 1
            continue
        tasks.append(asyncio.create_task(process_new(msg)))

    stage_b_results = await asyncio.gather(*tasks)
    processed = sum(1 for r in stage_b_results if r == 'processed')
    failed = sum(1 for r in stage_b_results if r == 'failed')

    log.info(
        "Run complete. Stage A: retried_success=%d retried_fail=%d. "
        "Stage B: processed=%d skipped=%d failed=%d",
        retried_success, retried_fail, processed, skipped, failed,
    )
    return RunResult(
        processed=processed,
        skipped=skipped,
        failed=failed,
        retried_success=retried_success,
        retried_fail=retried_fail,
    )
```

(Note: top-level `import asyncio` is fine to add at the top of the file too if not already imported via collector module — verify in the file. If already imported, the local `import asyncio` line inside `run()` is redundant; safe to keep or remove.)

- [ ] **Step 6: Run new + existing collector tests**

Run: `.venv/Scripts/pytest tests/test_collector.py -v`
Expected: 13/13 PASS (11 original + 2 concurrency).

- [ ] **Step 7: Run full test suite**

Run: `.venv/Scripts/pytest tests/ -v 2>&1 | tail -5`
Expected: 52/52 PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/conftest.py tests/test_collector.py collector.py
git commit -m "feat(collector): parallelize Stage A and Stage B via asyncio.Semaphore

Single Semaphore(config.max_concurrent_downloads) shared by both
phases so total concurrent downloads stay bounded. Each stage's
per-message handler is wrapped in an async function and dispatched
via asyncio.gather. _process_one_message is unchanged (already
concurrent-safe via atomic file rename + Supabase UPSERT).

Adds TrackingFakeClient + 2 observational concurrency tests."
```

---

### Task 4: Collector — Backfill mode + dedupe set (TDD)

**Files:**
- Modify: `tests/conftest.py` (extend `FakeStorage` with `existing_ids` field + `get_all_message_ids`)
- Modify: `tests/test_collector.py` (add 5 backfill tests)
- Modify: `collector.py` (add `backfill_days` parameter, dedupe-set construction, branching)

- [ ] **Step 1: Extend `FakeStorage` in `tests/conftest.py`**

Find the existing `FakeStorage.__init__`:

```python
    def __init__(self, base_dir: Path, max_seen: int = 0,
                 failed_ids: list[int] | None = None) -> None:
        self.base_dir = base_dir
        self._max_seen = max_seen
        self._failed_ids = list(failed_ids or [])
        self.inserted: list[dict] = []
        self.failed_upserts: list[tuple[str, int, str]] = []
        self.failed_removes: list[tuple[str, int]] = []
        self.saved_files: list[tuple[str, bytes]] = []
```

Replace with:

```python
    def __init__(self, base_dir: Path, max_seen: int = 0,
                 failed_ids: list[int] | None = None,
                 existing_ids: set[int] | None = None) -> None:
        self.base_dir = base_dir
        self._max_seen = max_seen
        self._failed_ids = list(failed_ids or [])
        self._existing_ids: set[int] = set(existing_ids or [])
        self.inserted: list[dict] = []
        self.failed_upserts: list[tuple[str, int, str]] = []
        self.failed_removes: list[tuple[str, int]] = []
        self.saved_files: list[tuple[str, bytes]] = []
```

Then add a new method INSIDE the `FakeStorage` class (next to `get_failed_message_ids`):

```python
    def get_all_message_ids(self, chat_username: str) -> set[int]:
        return set(self._existing_ids)
```

- [ ] **Step 2: Add 5 backfill tests to `tests/test_collector.py`**

Append at the end of `tests/test_collector.py` (after concurrency tests from Task 3):

```python
# === Backfill mode ===

@pytest.mark.asyncio
async def test_backfill_mode_pre_fetches_existing_ids(fake_client, fake_storage, cfg):
    """Backfill mode skips messages whose id is already in reports."""
    fake_storage._existing_ids = {100, 101}
    fake_client.new_messages = [make_msg(100), make_msg(101), make_msg(102)]

    result = await run(fake_client, fake_storage, cfg, backfill_days=30)

    assert result.processed == 1  # only 102 is new
    assert result.skipped == 2     # 100, 101 are pre-known
    inserted_ids = [m['message_id'] for m in fake_storage.inserted]
    assert 102 in inserted_ids
    assert 100 not in inserted_ids
    assert 101 not in inserted_ids


@pytest.mark.asyncio
async def test_backfill_mode_includes_failed_attempts_in_skip_set(
    fake_client, fake_storage, cfg
):
    """Messages still in failed_attempts after Stage A must be skipped in Stage B,
    otherwise we double-process them in the same run."""
    # Stage A: msg_id=200 is in failed_attempts, retry will fail again
    fake_storage._failed_ids = [200]
    fake_storage._max_seen = 200
    fake_client.failed_lookups[200] = make_msg(200)
    fake_client.download_errors[200] = RuntimeError('persistent fail')
    # Stage B: cutoff_date iter returns the same msg_id 200 + a new 201
    fake_client.new_messages = [make_msg(200), make_msg(201)]

    result = await run(fake_client, fake_storage, cfg, backfill_days=30)

    # Stage A should record one fail
    assert result.retried_fail == 1
    # Stage B should NOT re-process 200 (it's in failed_attempts post-Stage-A)
    inserted_ids = [m['message_id'] for m in fake_storage.inserted]
    assert 201 in inserted_ids
    assert 200 not in inserted_ids
    assert result.processed == 1  # only 201
    # 200 should appear EXACTLY ONCE in download attempts (Stage A only)
    download_calls = [c for c in fake_client.calls if c[0] == 'download' and c[1] == 200]
    assert len(download_calls) == 1


@pytest.mark.asyncio
async def test_backfill_mode_uses_since_date_iter(fake_client, fake_storage, cfg):
    """In backfill mode, iter_messages_since_date is called with backfill_days,
    even when last_seen > 0."""
    fake_storage._max_seen = 999  # nonzero — would normally trigger after_id mode
    fake_client.new_messages = [make_msg(101)]

    await run(fake_client, fake_storage, cfg, backfill_days=90)

    assert ('iter_since_date', 'sunstudy1004', 90) in fake_client.calls
    assert not any(c[0] == 'iter_after_id' for c in fake_client.calls)


@pytest.mark.asyncio
async def test_backfill_mode_runs_stage_a(fake_client, fake_storage, cfg):
    """Backfill mode does NOT skip Stage A — failed retries still happen."""
    fake_storage._failed_ids = [50]
    fake_client.failed_lookups[50] = make_msg(50)
    fake_client.new_messages = []

    await run(fake_client, fake_storage, cfg, backfill_days=30)

    assert ('get_by_id', 'sunstudy1004', 50) in fake_client.calls


@pytest.mark.asyncio
async def test_normal_mode_does_not_pre_fetch_existing_ids(
    fake_client, fake_storage, cfg
):
    """Without backfill_days, get_all_message_ids should never be called."""
    # Set existing_ids to non-empty; if the collector mistakenly calls
    # get_all_message_ids in normal mode, msg 101 would be skipped.
    fake_storage._existing_ids = {101}
    fake_client.new_messages = [make_msg(101)]

    result = await run(fake_client, fake_storage, cfg)  # no backfill_days

    # Normal mode uses min_id/since_date, not the pre-fetched set,
    # so 101 should be processed normally.
    assert result.processed == 1
    inserted_ids = [m['message_id'] for m in fake_storage.inserted]
    assert 101 in inserted_ids
```

- [ ] **Step 3: Run new tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_collector.py -k backfill -v`
Expected: 5 tests FAIL with `TypeError: run() got an unexpected keyword argument 'backfill_days'`.

- [ ] **Step 4: Implement backfill in `collector.py`**

Modify the `run()` function signature (top of function):

Find:
```python
async def run(client: Any, storage: Any, config: Any) -> RunResult:
```

Replace with:
```python
async def run(
    client: Any,
    storage: Any,
    config: Any,
    backfill_days: int | None = None,
) -> RunResult:
```

Then update its docstring (immediately below the signature). Find:
```python
    """Run one collection cycle for the configured channel.

    Stage A: re-attempt every msg_id currently in failed_attempts (parallelized).
    Stage B: fetch messages with id > max_seen and process them (parallelized).

    Both stages share a single Semaphore so total concurrent downloads
    cannot exceed config.max_concurrent_downloads.
    """
```

Replace with:
```python
    """Run one collection cycle for the configured channel.

    Stage A: re-attempt every msg_id currently in failed_attempts (parallelized).
    Stage B: fetch messages and process them (parallelized).
      - Normal mode (backfill_days=None): start from MAX(reports + failed_attempts).
      - Backfill mode (backfill_days=int): iterate from N days ago, skipping
        message_ids already in reports OR still in failed_attempts after Stage A.

    Both stages share a single Semaphore so total concurrent downloads
    cannot exceed config.max_concurrent_downloads.
    """
```

Then replace the Stage B branching block. Find:

```python
    # === Stage B: fetch new messages (parallel) ===
    last_seen = storage.get_max_seen_message_id(channel)
    log.info("Stage B: last_seen_message_id=%s", last_seen)

    if last_seen == 0:
        log.info("First run; using cutoff=%d days", config.initial_cutoff_days)
        message_iter = client.iter_messages_since_date(channel, config.initial_cutoff_days)
    else:
        message_iter = client.iter_messages_after_id(channel, last_seen)
```

Replace with:

```python
    # === Stage B: fetch new messages (parallel) ===
    if backfill_days is not None:
        # Backfill mode: pre-fetch dedupe set AFTER Stage A so newly-added
        # reports rows AND still-failing failed_attempts rows are both included.
        # Skipping the latter avoids double-processing the same msg_id in one run
        # (spec §3.3).
        existing_ids = storage.get_all_message_ids(channel)
        existing_ids.update(storage.get_failed_message_ids(channel))
        log.info(
            "Backfill mode: %d existing message_ids will be skipped "
            "(reports + still-failed), fetching from %d days ago",
            len(existing_ids), backfill_days,
        )
        message_iter = client.iter_messages_since_date(channel, backfill_days)
    else:
        existing_ids = None
        last_seen = storage.get_max_seen_message_id(channel)
        log.info("Stage B: last_seen_message_id=%s", last_seen)
        if last_seen == 0:
            log.info("First run; using cutoff=%d days", config.initial_cutoff_days)
            message_iter = client.iter_messages_since_date(channel, config.initial_cutoff_days)
        else:
            message_iter = client.iter_messages_after_id(channel, last_seen)
```

Then update the Stage B iteration loop to honor `existing_ids`. Find:

```python
    tasks = []
    skipped = 0
    async for msg in message_iter:
        if not has_pdf(msg):
            skipped += 1
            continue
        tasks.append(asyncio.create_task(process_new(msg)))
```

Replace with:

```python
    tasks = []
    skipped = 0
    async for msg in message_iter:
        if not has_pdf(msg):
            skipped += 1
            continue
        if existing_ids is not None and msg.id in existing_ids:
            skipped += 1
            continue
        tasks.append(asyncio.create_task(process_new(msg)))
```

- [ ] **Step 5: Run backfill tests + full collector suite**

Run: `.venv/Scripts/pytest tests/test_collector.py -v`
Expected: 18/18 PASS (11 original + 2 concurrency + 5 backfill).

- [ ] **Step 6: Run full test suite**

Run: `.venv/Scripts/pytest tests/ -v 2>&1 | tail -5`
Expected: 57/57 PASS (52 from Task 3 + 5 new).

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py tests/test_collector.py collector.py
git commit -m "feat(collector): add backfill mode with reports+failed_attempts dedupe

run() gains backfill_days parameter (default None preserves existing
behavior). When set, Stage B uses iter_messages_since_date(backfill_days)
regardless of last_seen, and skips any msg_id already in reports OR
still in failed_attempts after Stage A. Pre-fetch happens after Stage A
so newly-added rows and persistent failures are both included in the
skip set, avoiding double-processing in the same run."
```

---

### Task 5: Main — argparse mutually-exclusive + wire `backfill_days` (TDD)

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Add 3 main tests to `tests/test_main.py`**

Append at the end of `tests/test_main.py`:

```python
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
```

Also UPDATE the existing `test_parse_args_no_flags_defaults` to assert `backfill_days` defaults to None:

Find:
```python
def test_parse_args_no_flags_defaults():
    args = parse_args([])
    assert args.cutoff_days is None
    assert args.dry_run is False
    assert args.verbose is False
```

Replace with:
```python
def test_parse_args_no_flags_defaults():
    args = parse_args([])
    assert args.cutoff_days is None
    assert args.backfill_days is None
    assert args.dry_run is False
    assert args.verbose is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_main.py -v`
Expected: 3 tests FAIL — the 2 new ones (`backfill_days` not in args namespace) + the updated default test.

- [ ] **Step 3: Implement argparse changes in `main.py`**

In the `parse_args` function, find:

```python
    p.add_argument(
        '--cutoff-days',
        type=int,
        default=None,
        help='Override INITIAL_CUTOFF_DAYS for this run (only affects first run).',
    )
```

Replace with:

```python
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        '--cutoff-days',
        type=int,
        default=None,
        help='Override INITIAL_CUTOFF_DAYS for this run (only effective on FIRST run when DB is empty).',
    )
    mode.add_argument(
        '--backfill-days',
        type=int,
        default=None,
        help='Backfill mode: fetch from N days ago, skip already-downloaded ones. '
             'Ignores last_seen state. For one-off historical collection.',
    )
```

- [ ] **Step 4: Wire `backfill_days` into collector call**

In `_amain`, find:

```python
async def _amain(args: argparse.Namespace, config: Config) -> int:
    async with TelegramClient(
        api_id=config.telegram_api_id,
        api_hash=config.telegram_api_hash,
        session_path=config.telegram_session_path,
    ) as client:
        storage = build_storage(
            supabase_url=config.supabase_url,
            supabase_service_key=config.supabase_service_key,
            base_dir=config.storage_base_dir,
        )
        if args.dry_run:
            return await _dry_run(client, storage, config)
        result = await collector.run(client, storage, config)
        return compute_exit_code(result)
```

Replace with:

```python
async def _amain(args: argparse.Namespace, config: Config) -> int:
    async with TelegramClient(
        api_id=config.telegram_api_id,
        api_hash=config.telegram_api_hash,
        session_path=config.telegram_session_path,
    ) as client:
        storage = build_storage(
            supabase_url=config.supabase_url,
            supabase_service_key=config.supabase_service_key,
            base_dir=config.storage_base_dir,
        )
        if args.dry_run:
            return await _dry_run(client, storage, config, backfill_days=args.backfill_days)
        result = await collector.run(client, storage, config, backfill_days=args.backfill_days)
        return compute_exit_code(result)
```

(Note: `_dry_run` does not yet accept `backfill_days` — that's Task 6. This call passes the kwarg and will be handled there. Until Task 6 lands, the test suite passes because no dry-run-with-backfill test exists yet.)

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/pytest tests/test_main.py -v`
Expected: 13/13 PASS (10 original + 2 new + 1 updated).

- [ ] **Step 6: Run full test suite**

Run: `.venv/Scripts/pytest tests/ -v 2>&1 | tail -5`
Expected: 60/60 PASS.

Wait — at this stage, Task 6 hasn't extended `_dry_run` yet. If any test exercises `_dry_run` with `backfill_days`, it would fail. But there's none yet (we add it in Task 6). So Task 5 is self-contained.

Also: a regular `--dry-run` (no `--backfill-days`) call now passes `backfill_days=None` to `_dry_run`, which still has its old signature accepting only `(client, storage, config)`. This will break! Need to fix this in step 4 OR fold dry-run extension into this task.

Revised Step 4 — temporarily handle the missing `backfill_days` param in `_dry_run`:

Actually easier: just don't pass `backfill_days` to `_dry_run` yet (Task 5 only wires backfill to `collector.run`, not `_dry_run`). Task 6 wires it to `_dry_run`. Replacing Step 4 above:

In `_amain`, find:

```python
        if args.dry_run:
            return await _dry_run(client, storage, config)
        result = await collector.run(client, storage, config)
        return compute_exit_code(result)
```

Replace with:

```python
        if args.dry_run:
            return await _dry_run(client, storage, config)
        result = await collector.run(client, storage, config, backfill_days=args.backfill_days)
        return compute_exit_code(result)
```

(The `_dry_run` extension comes in Task 6. Until then, `python main.py --dry-run --backfill-days 365` would silently ignore `--backfill-days` for dry-run preview — that's OK because Task 6 finishes within the same change set.)

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat(main): add --backfill-days flag (mutex with --cutoff-days), wire to collector

argparse mutually_exclusive_group rejects --cutoff-days +
--backfill-days combination at parse time. _amain passes
backfill_days through to collector.run. _dry_run is wired in
the next commit (Task 6) so the parameter doesn't yet flow
through preview mode."
```

---

### Task 6: `_dry_run` — extend with `backfill_days` (TDD)

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Add test for dry-run with backfill**

Append to `tests/test_main.py`:

```python
# === Dry-run with backfill ===

import pytest
import asyncio


@pytest.mark.asyncio
async def test_dry_run_with_backfill_uses_skip_set(monkeypatch, tmp_path, capsys):
    """_dry_run with backfill_days uses iter_since_date and skips IDs already
    in reports OR failed_attempts. The 'new' count should reflect dedupe."""
    from types import SimpleNamespace
    from tests.conftest import FakeStorage, FakeTelegramClient, make_msg
    from main import _dry_run

    storage = FakeStorage(
        base_dir=tmp_path,
        existing_ids={100, 101},
        failed_ids=[200],
    )
    client = FakeTelegramClient()
    client.new_messages = [make_msg(100), make_msg(101), make_msg(200), make_msg(300)]

    config = SimpleNamespace(
        telegram_channel='sunstudy1004',
        initial_cutoff_days=30,
    )

    rc = await _dry_run(client, storage, config, backfill_days=90)

    assert rc == 0
    # iter_since_date called with backfill_days, not initial_cutoff_days
    assert ('iter_since_date', 'sunstudy1004', 90) in client.calls

    captured = capsys.readouterr()
    log_output = captured.err  # logging defaults to stderr

    # Reports nothing was actually downloaded; nothing inserted; nothing saved
    assert storage.inserted == []
    assert storage.saved_files == []
```

(Note: the test verifies behavior, not exact log output. The log includes counts of new vs skipped, but those are observable via the counters captured in the function's own log calls — verifying `inserted == []` and `saved_files == []` proves dry-run did not write anything.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_main.py::test_dry_run_with_backfill_uses_skip_set -v`
Expected: FAIL with `TypeError: _dry_run() got an unexpected keyword argument 'backfill_days'`.

- [ ] **Step 3: Implement `_dry_run` extension in `main.py`**

Find the existing `_dry_run` function:

```python
async def _dry_run(client, storage, config: Config) -> int:
    """List which messages would be processed, without writing anything."""
    from telegram_client import has_pdf, _get_original_filename
    channel = config.telegram_channel
    last_seen = storage.get_max_seen_message_id(channel)
    if last_seen == 0:
        msgs = client.iter_messages_since_date(channel, config.initial_cutoff_days)
    else:
        msgs = client.iter_messages_after_id(channel, last_seen)
    log.info("DRY RUN — would process the following:")
    n = 0
    async for msg in msgs:
        if has_pdf(msg):
            log.info("  msg_id=%s sent_at=%s file=%s",
                     msg.id, msg.date.isoformat(), _get_original_filename(msg))
            n += 1
    log.info("DRY RUN — total %d PDF messages", n)
    return 0
```

Replace with:

```python
async def _dry_run(client, storage, config, backfill_days: int | None = None) -> int:
    """List which messages would be processed, without writing anything.

    With backfill_days set, mirrors the real backfill-mode dedupe: fetch
    from N days ago and skip ids already in reports OR failed_attempts.
    Reports separate counts of "new" vs "already-known skipped" so the
    user can size disk and time before launching the real run (spec §1.3).
    """
    from telegram_client import has_pdf, _get_original_filename
    channel = config.telegram_channel

    if backfill_days is not None:
        existing_ids = storage.get_all_message_ids(channel)
        existing_ids.update(storage.get_failed_message_ids(channel))
        log.info(
            "DRY RUN (backfill mode): %d existing message_ids will be skipped, "
            "fetching from %d days ago",
            len(existing_ids), backfill_days,
        )
        msgs = client.iter_messages_since_date(channel, backfill_days)
    else:
        existing_ids = None
        last_seen = storage.get_max_seen_message_id(channel)
        if last_seen == 0:
            msgs = client.iter_messages_since_date(channel, config.initial_cutoff_days)
        else:
            msgs = client.iter_messages_after_id(channel, last_seen)

    log.info("DRY RUN — would process the following:")
    n = 0
    n_skipped_existing = 0
    async for msg in msgs:
        if not has_pdf(msg):
            continue
        if existing_ids is not None and msg.id in existing_ids:
            n_skipped_existing += 1
            continue
        log.info("  msg_id=%s sent_at=%s file=%s",
                 msg.id, msg.date.isoformat(), _get_original_filename(msg))
        n += 1

    log.info("DRY RUN — total %d new PDF messages", n)
    if existing_ids is not None:
        log.info("DRY RUN — also %d already-known messages skipped", n_skipped_existing)
    return 0
```

- [ ] **Step 4: Update the `_amain` call to pass `backfill_days` through**

In `_amain`, find:

```python
        if args.dry_run:
            return await _dry_run(client, storage, config)
```

Replace with:

```python
        if args.dry_run:
            return await _dry_run(client, storage, config, backfill_days=args.backfill_days)
```

- [ ] **Step 5: Run new test + full main suite**

Run: `.venv/Scripts/pytest tests/test_main.py -v`
Expected: 14/14 PASS.

- [ ] **Step 6: Run full test suite**

Run: `.venv/Scripts/pytest tests/ -v 2>&1 | tail -5`
Expected: 61/61 PASS.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat(main): extend _dry_run with backfill_days for accurate preview

_dry_run gains a backfill_days kwarg (default None preserves existing
behavior). When set, uses the same iter_messages_since_date branch
and the same reports+failed_attempts dedupe set as the real run, then
reports 'new' vs 'already-known skipped' counts. Lets the user size
disk usage before committing to a multi-hour backfill (spec §1.3)."
```

---

### Task 7: Documentation + smoke test

**Files:**
- Modify: `README.md`

The smoke test portion (Steps 2–4) requires real Telegram + Supabase. The user runs them; the implementer writes only the README updates and prepares the commands.

- [ ] **Step 1: Update README.md**

Find the Usage table:

```markdown
| Command | Effect |
|---|---|
| `python main.py` | Normal run: collect new PDFs since last run |
| `python main.py --dry-run` | List what would be downloaded; write nothing |
| `python main.py --cutoff-days 7` | Override INITIAL_CUTOFF_DAYS for this run |
| `python main.py -v` | Verbose (DEBUG level) logging |
```

Replace with:

```markdown
| Command | Effect |
|---|---|
| `python main.py` | Normal run: collect new PDFs since last run (parallel by default, N=4) |
| `python main.py --dry-run` | List what would be downloaded; write nothing |
| `python main.py --cutoff-days 7` | Override INITIAL_CUTOFF_DAYS for this run (FIRST run only) |
| `python main.py --backfill-days 365` | One-off historical backfill: fetch from N days ago, skip already-downloaded |
| `python main.py --dry-run --backfill-days 365` | Preview backfill: count "new" vs "already-known skipped" before committing |
| `python main.py -v` | Verbose (DEBUG level) logging |

Mutually exclusive: `--cutoff-days` and `--backfill-days` cannot be used together.

### Concurrency tuning

`MAX_CONCURRENT_DOWNLOADS` env var (default `4`) controls how many PDFs
download in parallel. Bump to `8` for faster backfill if FloodWait
warnings are absent; lower to `1` for strictly sequential behavior.
Single Semaphore is shared by Stage A retries and Stage B new fetches,
so total in-flight downloads stay bounded.
```

- [ ] **Step 2: Commit README**

```bash
git add README.md
git commit -m "docs: document --backfill-days, --dry-run preview, and concurrency tuning"
```

- [ ] **Step 3: Smoke test — sanity check normal run still works (manual)**

User runs:
```bash
.venv\Scripts\python main.py 2>&1 | grep -v "DEBUG\|telethon.network\|telethon.extensions" | tail -10
```

Expected:
- Stage A: `retrying 0 previously failed messages` (assuming clean state from prior smoke)
- Stage B: `last_seen_message_id=124631` (or similar)
- `Run complete. Stage A: retried_success=0 retried_fail=0. Stage B: processed=0 skipped=0 failed=0`
- Exit code 0
- Concurrency=4 in the Stage A log line

If new messages have arrived since the last run, processed > 0 and they will have been downloaded in parallel.

- [ ] **Step 4: Smoke test — backfill dry-run (7 days, manual)**

User runs:
```bash
.venv\Scripts\python main.py --dry-run --backfill-days 7 2>&1 | grep -v "DEBUG\|telethon.network\|telethon.extensions" | tail -30
```

Expected:
- Log line: `DRY RUN (backfill mode): 12 existing message_ids will be skipped, fetching from 7 days ago`
  (12 = the rows from the original smoke test; may differ if more were collected since)
- A list of NEW msg_ids (those NOT in the 12 already-known) printed individually
- Final lines:
  - `DRY RUN — total N new PDF messages`
  - `DRY RUN — also M already-known messages skipped`
  - `M` should equal the number of message_ids that exist in both the channel's last-7-days history AND in the reports table (typically ~12 if all of them were sent in the last 7 days; could be 0 if they're older than 7 days now).

- [ ] **Step 5: Smoke test — small real backfill (manual, optional but recommended)**

User runs:
```bash
.venv\Scripts\python main.py --backfill-days 7 2>&1 | grep -v "DEBUG\|telethon.network\|telethon.extensions" | tail -10
```

Expected:
- All "new" PDFs from the dry-run are downloaded in parallel
- Existing rows are NOT re-downloaded (verify by `ls -la reports/` showing no duplicate / overwritten files except those that legitimately appear in the backfill window)
- Time noticeably faster than the original sequential run (compare wall-clock to the 106 seconds the 12-PDF first run took)

- [ ] **Step 6: Verify in Supabase via MCP (optional, manual)**

User can verify row count grew correctly:
```
mcp__supabase__execute_sql with query:
  select count(*) as total, max(message_id) as max_msg
  from reports where chat_username = 'sunstudy1004';
```

Expected: `total` = (12 baseline) + (new msgs from backfill window). `max_msg` advances if there were newer messages.

If smoke test passes, the implementation is verified end-to-end.

---

## Self-Review Notes (for the implementer / reviewer)

This plan addresses every concrete requirement in `docs/superpowers/specs/2026-05-06-parallel-and-backfill-design.md`:

- §1.1 (`MAX_CONCURRENT_DOWNLOADS` env var): Task 1
- §1.2 (`--backfill-days` argparse mutually-exclusive): Task 5
- §1.3 (`--dry-run --backfill-days` behavior): Task 6
- §2.1 (Semaphore + gather pattern): Task 3
- §2.2 (Stage A parallel retry_one): Task 3
- §2.3 (Stage B with backfill branch + dedupe set): Task 4
- §2.4 (`_process_one_message` unchanged + concurrent-safe): preserved across all tasks
- §3.1 (paginated `get_all_message_ids`): Task 2
- §3.2 (paginated `get_failed_message_ids`): Task 2
- §3.3 (dedupe set composition): Task 4
- §4.1–4.3 (all test categories): Tasks 1, 3, 4, 5, 6
- §4.4 (regression on existing 50 tests): verified after each task
- §5 (compatibility matrix): default-None backfill_days param preserves all existing call sites
- §6 (risk register): mitigations are encoded (paged dedupe, dry-run with backfill, semaphore tuning via env var)
- §7 (performance): smoke test (Task 7 step 5) validates wall-clock improvement
- §8 (rollback): `MAX_CONCURRENT_DOWNLOADS=1` reduces to serial without code change
- §9 (limits): paging implemented; 100K+ regime noted as future work
- §10 (decision record): all decisions reflected in code structure
