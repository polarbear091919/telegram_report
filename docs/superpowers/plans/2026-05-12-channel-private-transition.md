# Channel Private Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 옛 `sunstudy1004` 채널이 username을 떼고 비공개 전환되어 username 기반 fetch가 불가해진 상황을 복구. **channel id 기반 fetch**로 우회하되, DB의 `chat_username` 라벨은 `'sunstudy1004'`로 유지해 기존 16,181건 데이터와의 연속성을 끊지 않는다.

**Architecture:**
- `Config`에 새 optional 필드 `telegram_channel_id: int | None` 추가 + 헬퍼 `channel_ref()` 추가.
- `collector.run` / `main._dry_run`에서 **fetch identifier**와 **DB label**을 분리: telethon 호출엔 `config.channel_ref()`, DB 저장(`chat_username`)엔 `config.telegram_channel`.
- `.env`엔 `TELEGRAM_CHANNEL_ID=1378197756` 추가, `TELEGRAM_CHANNEL=sunstudy1004` 그대로 유지. CHANNEL_ID 비어있으면 기존 동작 그대로 (backward-compatible).

**Tech Stack:** Python 3.11+, dotenv, telethon, pytest, pytest-asyncio.

**Why this shape (비유):** 단골 카페가 간판(`sunstudy1004`)을 떼고 회원제로 바꿈. 가게 자체는 그대로(id `1378197756`)고 회원증 가진 우리(Minjae 계정)는 안에서 평소처럼 커피 마실 수 있음. 우리 봇 코드에 "주소(id)로 찾아가되, 데이터에 적어두는 가게 별명은 옛것 그대로"라고 가르치는 작업.

---

## File Structure

수정할 파일 (전부 기존, 신규 없음):

| 파일 | 책임 | 변경 요약 |
|---|---|---|
| `config.py` | env 로딩 + Config dataclass | optional 필드 + `channel_ref()` 헬퍼 |
| `telegram_client.py` | telethon wrapper | type hint 확장 `int \| str` |
| `collector.py` | Stage A/B 오케스트레이션 | fetch에 ref, DB INSERT에 label 분리 |
| `main.py` | CLI + `_dry_run` | `_dry_run`도 동일 분리 |
| `.env.example` | 환경 변수 템플릿 | 새 `TELEGRAM_CHANNEL_ID` 항목 |
| `tests/test_config.py` | config 테스트 | 새 필드/헬퍼 테스트 |
| `tests/test_collector.py` | collector 테스트 | id-mode 사용 테스트 |
| `tests/test_main.py` | main 테스트 | `_dry_run` id-mode 테스트 |
| `tests/conftest.py` (필요시) | fake client/storage | (변경 없을 가능성 높음 — 검토만) |

운영(코드 외):
- 메인 레포 `.env` (커밋 안 함): `TELEGRAM_CHANNEL_ID=1378197756` 추가

---

## Task 1: `config.py` — `telegram_channel_id` 필드 + `channel_ref()` 헬퍼

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1.1: 새 필드 default None 테스트 (실패 예상)**

`tests/test_config.py` 끝에 추가:

```python
def test_load_config_telegram_channel_id_default_none(monkeypatch):
    """CHANNEL_ID 환경변수 없으면 telegram_channel_id는 None."""
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'sunstudy1004')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.delenv('TELEGRAM_CHANNEL_ID', raising=False)

    cfg = load_config()
    assert cfg.telegram_channel_id is None
```

- [ ] **Step 1.2: 테스트 실패 확인**

```bash
cd C:\Users\imyon\Projects\telegram_report\.claude\worktrees\sweet-dewdney-dc0ae1
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_config.py::test_load_config_telegram_channel_id_default_none -v
```

Expected: `AttributeError: 'Config' object has no attribute 'telegram_channel_id'`

- [ ] **Step 1.3: 필드 추가**

`config.py` `Config` dataclass에 필드 추가 (`log_level` 위, 위치는 backward compat 안전을 위해 끝쪽 keyword-only 형태로):

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
    telegram_channel_id: int | None = None
```

`load_config()`에 다음 라인 추가 (return문 안):

```python
def _optional_int(key: str) -> int | None:
    v = os.getenv(key)
    if v is None or v == '':
        return None
    return int(v)

return Config(
    telegram_api_id=int(required('TELEGRAM_API_ID')),
    telegram_api_hash=required('TELEGRAM_API_HASH'),
    telegram_channel=required('TELEGRAM_CHANNEL'),
    telegram_session_path=Path('sessions') / session_name,
    supabase_url=required('SUPABASE_URL'),
    supabase_service_key=required('SUPABASE_SERVICE_KEY'),
    storage_base_dir=Path(os.getenv('STORAGE_BASE_DIR', './reports')),
    initial_cutoff_days=int(os.getenv('INITIAL_CUTOFF_DAYS', '30')),
    max_concurrent_downloads=int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '4')),
    log_level=os.getenv('LOG_LEVEL', 'INFO'),
    telegram_channel_id=_optional_int('TELEGRAM_CHANNEL_ID'),
)
```

- [ ] **Step 1.4: 테스트 통과 확인**

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_config.py::test_load_config_telegram_channel_id_default_none -v
```

Expected: PASS

- [ ] **Step 1.5: int 값 로딩 테스트 추가 (실패 예상→통과)**

`tests/test_config.py`에 추가:

```python
def test_load_config_telegram_channel_id_int_when_set(monkeypatch):
    """CHANNEL_ID 환경변수가 숫자 문자열이면 int로 캐스팅."""
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'sunstudy1004')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.setenv('TELEGRAM_CHANNEL_ID', '1378197756')

    cfg = load_config()
    assert cfg.telegram_channel_id == 1378197756
    assert isinstance(cfg.telegram_channel_id, int)
```

Run 후 PASS 확인. 이미 Step 1.3에서 구현됐으므로 통과해야 함:

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_config.py -v
```

Expected: 모든 config 테스트 PASS.

- [ ] **Step 1.6: `channel_ref()` 헬퍼 메서드 테스트 (실패 예상)**

`tests/test_config.py`에 추가:

```python
def test_channel_ref_returns_id_int_when_id_set(monkeypatch):
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'sunstudy1004')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.setenv('TELEGRAM_CHANNEL_ID', '1378197756')

    cfg = load_config()
    assert cfg.channel_ref() == 1378197756


def test_channel_ref_falls_back_to_username_when_id_unset(monkeypatch):
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'sunstudy1004')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.delenv('TELEGRAM_CHANNEL_ID', raising=False)

    cfg = load_config()
    assert cfg.channel_ref() == 'sunstudy1004'
```

Run, FAIL (`'Config' object has no attribute 'channel_ref'`).

- [ ] **Step 1.7: `channel_ref()` 메서드 추가**

`config.py` `Config` dataclass 안에 메서드 추가 (필드들 아래):

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
    telegram_channel_id: int | None = None

    def channel_ref(self) -> int | str:
        """Identifier for telethon fetch calls.

        Returns the numeric channel id if set (required for private channels
        with no public username), else falls back to the username string for
        backward compatibility.
        """
        if self.telegram_channel_id is not None:
            return self.telegram_channel_id
        return self.telegram_channel
```

- [ ] **Step 1.8: 통과 확인 + 전체 config 테스트**

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_config.py -v
```

Expected: PASS (모든 기존 + 신규 4개 테스트).

- [ ] **Step 1.9: 커밋**

```bash
git add config.py tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(config): optional TELEGRAM_CHANNEL_ID + channel_ref() helper

Private channels have no public username, so identification must happen
via the numeric channel id. Adds an optional TELEGRAM_CHANNEL_ID env
var and a channel_ref() helper that returns the id when set, else the
username (backward-compatible).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `telegram_client.py` — type hint 확장 `int | str`

**Files:**
- Modify: `telegram_client.py`

(behavior 변경 없음, telethon은 이미 둘 다 받음. 타입 명시만.)

- [ ] **Step 2.1: type hint 수정**

`telegram_client.py`에서 채널 인자 받는 메서드 4개의 시그니처 변경:

```python
async def iter_messages_after_id(
    self, channel: int | str, min_id: int
) -> AsyncIterator[Message]:
    """Yield messages with id > min_id, oldest first."""
    async for msg in self._client.iter_messages(channel, min_id=min_id, reverse=True):
        yield msg

async def iter_messages_since_date(
    self, channel: int | str, days_ago: int
) -> AsyncIterator[Message]:
    """First-run path: yield all messages since `days_ago` days ago, oldest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_ago)
    async for msg in self._client.iter_messages(channel, offset_date=cutoff, reverse=True):
        yield msg

async def get_message_by_id(self, channel: int | str, message_id: int) -> Message | None:
    """Fetch a single message by id. Returns None if deleted/not found."""
    return await self._client.get_messages(channel, ids=message_id)
```

(`download_pdf_bytes`는 channel 인자 없음, 그대로.)

- [ ] **Step 2.2: 기존 테스트 통과 확인**

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_telegram_pdf.py -v
```

Expected: PASS (변경된 동작 없으므로 그대로 통과).

- [ ] **Step 2.3: 커밋**

```bash
git add telegram_client.py
git commit -m "$(cat <<'EOF'
chore(telegram_client): widen channel arg type to int | str

telethon already accepts both; this just makes the type hint match
reality so callers can pass a numeric channel id.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `collector.py` — fetch에 `channel_ref`, DB에 `chat_username` 라벨 분리

**Files:**
- Modify: `collector.py` (전체 `run()` 함수)
- Modify: `tests/test_collector.py` (cfg fixture에 id 필드 + 새 테스트)

- [ ] **Step 3.1: cfg fixture 확장 + id-mode 테스트 추가 (실패 예상)**

`tests/test_collector.py`의 `cfg` fixture 수정 — `telegram_channel_id` 필드 + `channel_ref` 메서드 포함:

```python
@pytest.fixture
def cfg():
    """Minimal config-shaped object. channel_ref() falls back to username
    when telegram_channel_id is None (backward-compatible default)."""
    from types import SimpleNamespace

    def channel_ref(self):
        if self.telegram_channel_id is not None:
            return self.telegram_channel_id
        return self.telegram_channel

    ns = SimpleNamespace(
        telegram_channel='sunstudy1004',
        telegram_channel_id=None,
        initial_cutoff_days=30,
        max_concurrent_downloads=4,
    )
    ns.channel_ref = channel_ref.__get__(ns, SimpleNamespace)
    return ns
```

같은 파일 끝에 새 테스트 추가:

```python
# === Channel id mode (private channels) ===

@pytest.mark.asyncio
async def test_id_mode_uses_int_for_fetch_but_username_for_db(
    fake_client, fake_storage, cfg
):
    """When channel_id is set, telethon receives the int id, but
    storage rows still use the human-readable chat_username label."""
    cfg.telegram_channel_id = 1378197756
    fake_client.new_messages = [make_msg(101)]

    result = await run(fake_client, fake_storage, cfg)

    # Fetch goes with the int id
    assert any(c[0] == 'iter_since_date' and c[1] == 1378197756 for c in fake_client.calls)
    # DB row keeps the string label (continuity with existing data)
    assert result.processed == 1
    assert fake_storage.inserted[0]['chat_username'] == 'sunstudy1004'


@pytest.mark.asyncio
async def test_id_mode_storage_lookups_use_username(
    fake_client, fake_storage, cfg
):
    """Storage queries (get_max_seen, get_failed_ids, get_all_ids) must use
    the chat_username label so they hit the existing rows, not a new namespace."""
    cfg.telegram_channel_id = 1378197756
    fake_storage._max_seen = 125164
    fake_client.new_messages = [make_msg(125165)]

    await run(fake_client, fake_storage, cfg)

    # iter_after_id should be called with int id
    assert any(c[0] == 'iter_after_id' and c[1] == 1378197756 for c in fake_client.calls)
    # But fake_storage must have been asked under the username label
    # (FakeStorage.get_max_seen_message_id returns _max_seen regardless of
    # arg; here we just verify the call shape via inserted row label)
    assert fake_storage.inserted[0]['chat_username'] == 'sunstudy1004'
```

- [ ] **Step 3.2: 테스트 실패 확인**

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_collector.py -v
```

Expected: 두 신규 테스트 FAIL (collector 아직 channel_ref 안 씀), 기존 테스트는 PASS.

- [ ] **Step 3.3: `collector.run` refactor — fetch와 label 분리**

`collector.py`의 `run()` 함수 본문에서 `channel = config.telegram_channel` 한 줄을 두 줄로 분리하고, 사용처 정리:

```python
async def run(
    client: Any,
    storage: Any,
    config: Any,
    backfill_days: int | None = None,
) -> RunResult:
    """Run one collection cycle for the configured channel.

    Stage A: re-attempt every msg_id currently in failed_attempts (parallelized).
    Stage B: fetch messages and process them (parallelized).
      - Normal mode (backfill_days=None): start from MAX(reports + failed_attempts).
      - Backfill mode (backfill_days=int): iterate from N days ago, skipping
        message_ids already in reports OR still in failed_attempts after Stage A.

    Telegram fetch uses config.channel_ref() (an int channel id for private
    channels, or username str for public). DB rows always use
    config.telegram_channel as the chat_username label so legacy and new
    data live in the same namespace.
    """
    import asyncio

    channel_ref = config.channel_ref()       # for telethon
    chat_label = config.telegram_channel     # for storage (DB column)
    sem = asyncio.Semaphore(config.max_concurrent_downloads)

    # === Stage A: retry past failures (parallel) ===
    failed_ids = storage.get_failed_message_ids(chat_label)
    log.info("Stage A: retrying %d previously failed messages (concurrency=%d)",
             len(failed_ids), config.max_concurrent_downloads)

    async def retry_one(msg_id: int) -> str:
        async with sem:
            msg = await client.get_message_by_id(channel_ref, msg_id)
            if msg is None or not has_pdf(msg):
                log.info("Cleaning failed_attempts row for msg_id=%s (deleted or not PDF)", msg_id)
                storage.remove_failed_attempt(chat_label, msg_id)
                return 'cleaned'
            try:
                await _process_one_message(client, storage, chat_label, msg)
                storage.remove_failed_attempt(chat_label, msg_id)
                return 'success'
            except Exception as e:
                log.exception("Retry still failing for msg_id=%s", msg_id)
                new_count = storage.upsert_failed_attempt(chat_label, msg_id, str(e))
                if new_count >= ATTEMPT_WARN_THRESHOLD:
                    log.warning("msg_id=%s has failed %d times — investigate manually",
                                msg_id, new_count)
                return 'fail'

    stage_a_results = await asyncio.gather(*[retry_one(mid) for mid in failed_ids])
    retried_success = sum(1 for r in stage_a_results if r == 'success')
    retried_fail = sum(1 for r in stage_a_results if r == 'fail')

    # === Stage B: fetch new messages (parallel) ===
    if backfill_days is not None:
        existing_ids = storage.get_all_message_ids(chat_label)
        existing_ids.update(storage.get_failed_message_ids(chat_label))
        log.info(
            "Backfill mode: %d existing message_ids will be skipped "
            "(reports + still-failed), fetching from %d days ago",
            len(existing_ids), backfill_days,
        )
        message_iter = client.iter_messages_since_date(channel_ref, backfill_days)
    else:
        existing_ids = None
        last_seen = storage.get_max_seen_message_id(chat_label)
        log.info("Stage B: last_seen_message_id=%s", last_seen)
        if last_seen == 0:
            log.info("First run; using cutoff=%d days", config.initial_cutoff_days)
            message_iter = client.iter_messages_since_date(channel_ref, config.initial_cutoff_days)
        else:
            message_iter = client.iter_messages_after_id(channel_ref, last_seen)

    async def process_new(msg) -> str:
        async with sem:
            try:
                await _process_one_message(client, storage, chat_label, msg)
                return 'processed'
            except Exception as e:
                log.exception("Failed to process message_id=%s", msg.id)
                new_count = storage.upsert_failed_attempt(chat_label, msg.id, str(e))
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
        if existing_ids is not None and msg.id in existing_ids:
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

Note: `_process_one_message`의 세 번째 인자 이름은 그대로 `channel` (시그니처: `_process_one_message(client, storage, channel: str, msg)`) — DB 컬럼 값으로 그대로 들어가니까 라벨이 맞다. 의미 명확화를 위해 함수 시그니처도 살짝 손봐도 좋지만 이름 변경은 별도 task로 분리(또는 생략).

- [ ] **Step 3.4: 모든 collector 테스트 통과 확인**

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_collector.py -v
```

Expected: 기존 + 신규 2개 모두 PASS.

기존 테스트들이 `('iter_since_date', 'sunstudy1004', 30)` 같은 패턴으로 검증한다는 점에 유의. cfg fixture가 `telegram_channel_id=None`이라 `channel_ref()`가 `'sunstudy1004'` 반환 → 기존 테스트 그대로 통과.

- [ ] **Step 3.5: 커밋**

```bash
git add collector.py tests/test_collector.py
git commit -m "$(cat <<'EOF'
refactor(collector): separate channel_ref (fetch) from chat_label (DB)

Telethon now receives config.channel_ref() — an int channel id when set,
else the username — so private channels (no username) are reachable.
Storage calls still use config.telegram_channel as the chat_username so
legacy rows (16,181 from the public-channel era) and new rows share one
namespace.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `main.py:_dry_run` — 동일 분리

**Files:**
- Modify: `main.py` (`_dry_run` 함수)
- Modify: `tests/test_main.py`

- [ ] **Step 4.1: id-mode `_dry_run` 테스트 추가 (실패 예상)**

`tests/test_main.py` 끝에 추가:

```python
@pytest.mark.asyncio
async def test_dry_run_uses_channel_id_when_set(monkeypatch, tmp_path, capsys):
    """When telegram_channel_id is set on config, dry-run fetches via int id."""
    from types import SimpleNamespace
    from tests.conftest import FakeStorage, FakeTelegramClient, make_msg
    from main import _dry_run

    storage = FakeStorage(base_dir=tmp_path)
    client = FakeTelegramClient()
    client.new_messages = [make_msg(125165)]

    def channel_ref(self):
        if self.telegram_channel_id is not None:
            return self.telegram_channel_id
        return self.telegram_channel

    config = SimpleNamespace(
        telegram_channel='sunstudy1004',
        telegram_channel_id=1378197756,
        initial_cutoff_days=30,
    )
    config.channel_ref = channel_ref.__get__(config, SimpleNamespace)

    rc = await _dry_run(client, storage, config, backfill_days=None)

    assert rc == 0
    # First run (max_seen=0) — uses iter_since_date with the int id
    assert any(c[0] == 'iter_since_date' and c[1] == 1378197756 for c in client.calls)
```

- [ ] **Step 4.2: 테스트 실패 확인**

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_main.py::test_dry_run_uses_channel_id_when_set -v
```

Expected: FAIL (현재 `_dry_run`은 `config.telegram_channel` 사용).

- [ ] **Step 4.3: `_dry_run` refactor**

`main.py`의 `_dry_run` 함수 본문에서 첫 줄을 분리:

```python
async def _dry_run(client, storage, config, backfill_days: int | None = None) -> int:
    """List which messages would be processed, without writing anything.

    Telegram fetch uses config.channel_ref(); storage lookups use the
    chat_username label (config.telegram_channel) so existing rows are
    deduped correctly.
    """
    from telegram_client import has_pdf, _get_original_filename
    channel_ref = config.channel_ref()
    chat_label = config.telegram_channel

    if backfill_days is not None:
        existing_ids = storage.get_all_message_ids(chat_label)
        existing_ids.update(storage.get_failed_message_ids(chat_label))
        log.info(
            "DRY RUN (backfill mode): %d existing message_ids will be skipped, "
            "fetching from %d days ago",
            len(existing_ids), backfill_days,
        )
        msgs = client.iter_messages_since_date(channel_ref, backfill_days)
    else:
        existing_ids = None
        last_seen = storage.get_max_seen_message_id(chat_label)
        if last_seen == 0:
            msgs = client.iter_messages_since_date(channel_ref, config.initial_cutoff_days)
        else:
            msgs = client.iter_messages_after_id(channel_ref, last_seen)

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

- [ ] **Step 4.4: 통과 확인**

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/test_main.py -v
```

Expected: 신규 + 기존 (test_dry_run_with_backfill_uses_skip_set) 모두 PASS.

기존 `test_dry_run_with_backfill_uses_skip_set`은 `config = SimpleNamespace(telegram_channel='sunstudy1004', initial_cutoff_days=30)` 형태인데, 이제 `_dry_run`이 `config.channel_ref()`를 부르려고 함 → AttributeError 위험. 그 테스트의 config에도 `channel_ref` 메서드 추가 필요:

```python
# tests/test_main.py:test_dry_run_with_backfill_uses_skip_set 안에서
def channel_ref(self):
    if getattr(self, 'telegram_channel_id', None) is not None:
        return self.telegram_channel_id
    return self.telegram_channel

config = SimpleNamespace(
    telegram_channel='sunstudy1004',
    telegram_channel_id=None,
    initial_cutoff_days=30,
)
config.channel_ref = channel_ref.__get__(config, SimpleNamespace)
```

수정 후 다시 run.

- [ ] **Step 4.5: 전체 테스트 한 번 통과 확인 (회귀 체크)**

```bash
& C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: 모든 테스트 PASS. (langgraph_tagger 관련 별도 — `tests/`에는 collector 측만.)

- [ ] **Step 4.6: 커밋**

```bash
git add main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
refactor(main): _dry_run uses channel_ref + chat_label split

Mirrors the same separation as collector.run so dry-run can preview new
private-channel messages.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `.env.example` 갱신

**Files:**
- Modify: `.env.example`

- [ ] **Step 5.1: 새 환경변수 항목 추가**

`.env.example`의 텔레그램 채널 섹션을 다음으로 교체:

```
# 대상 채널
#  - public 채널: TELEGRAM_CHANNEL=username (예: sunstudy1004)
#  - private 채널: TELEGRAM_CHANNEL_ID=<int>  +  TELEGRAM_CHANNEL=<라벨>
#    (라벨은 DB의 chat_username 컬럼에 저장됨. 기존 데이터와 같은 값을
#     유지하면 옛 데이터와의 연속성이 유지됨.)
TELEGRAM_CHANNEL=sunstudy1004
# TELEGRAM_CHANNEL_ID=1378197756
```

- [ ] **Step 5.2: 커밋**

```bash
git add .env.example
git commit -m "$(cat <<'EOF'
docs(.env.example): document TELEGRAM_CHANNEL_ID for private channels

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 운영 적용 + dry-run 검증

**Files:**
- Modify: `C:\Users\imyon\Projects\telegram_report\.env` (메인 레포, 커밋 안 됨 — gitignore)

- [ ] **Step 6.1: 메인 레포 `.env`에 CHANNEL_ID 추가**

`C:\Users\imyon\Projects\telegram_report\.env`를 열고, `TELEGRAM_CHANNEL=sunstudy1004` 줄 아래에 다음 추가:

```
TELEGRAM_CHANNEL_ID=1378197756
```

`TELEGRAM_CHANNEL=sunstudy1004` 는 **그대로 둠** (DB 라벨용).

- [ ] **Step 6.2: 메인 레포에서 dry-run으로 새 메시지 잡히는지 확인**

```powershell
Push-Location 'C:\Users\imyon\Projects\telegram_report'
& .\.venv\Scripts\python.exe main.py --dry-run 2>&1 | Select-String 'DRY RUN','last_seen|Stage B','Run complete' | Select-Object -Last 30 | ForEach-Object { $_.Line }
Pop-Location
```

Expected: 최근 텔레그램 채널 fetch 결과로 `would process` 메시지 N건 (방금 raw로 확인했을 때 14건 정도). `DRY RUN — total <N> new PDF messages` 출력.

⚠️ 주의 — 첫 dry-run 직후 같은 telethon caching 현상이 또 발생할 수 있음 (이전 진단에서 본 패턴). 그 경우 dry-run의 N건 결과가 cache hit일 수 있고, 다음 실제 run에서 0건일 위험. **dry-run에서 N건 보이면 곧바로 실제 collect로 진행**해서 cache 영향 최소화.

- [ ] **Step 6.3: 실제 수집**

```powershell
Push-Location 'C:\Users\imyon\Projects\telegram_report'
& .\.venv\Scripts\python.exe main.py
$rc = $LASTEXITCODE
Pop-Location
"exit=$rc"
```

Expected: `Stage B: processed=N skipped=K failed=0` 형태. exit=0 또는 2 (partial). N >= 1.

- [ ] **Step 6.4: inspect로 pending 증가 확인**

```bash
python -m langgraph_tagger inspect
```

Expected: 이전 대비 `pending` 증가 (`processed` 만큼). 다른 카운터는 그대로.

문제 시 (pending 증가 0): Step 6.2의 caching 시나리오일 수 있음 → 잠시 후 한 번 더 `python main.py` 시도.

---

## Task 7: 태거 wrapper로 신규 pending 처리

**Files:** (없음 — 운영만)

- [ ] **Step 7.1: tagger wrapper 한 번 돌려서 신규 pending 흡수**

batch=10이 운영 정석. 신규 pending이 ~14건이면 2 iter면 끝. 안전하게 3 iter:

```powershell
Push-Location 'C:\Users\imyon\Projects\telegram_report'
pwsh -File scripts\run-batches.ps1 -Iterations 3 -BatchSize 10
Pop-Location
```

Expected: 각 iteration ~22~25초. 신규 pending이 `auto` 또는 `review_needed`로 마감.

- [ ] **Step 7.2: 최종 inspect**

```bash
python -m langgraph_tagger inspect
```

Expected:
- `pending = 0`
- `auto`/`review_needed` 둘 중 하나 또는 둘 다 증가
- 합계 = 16,181 + Step 6.3의 N
- `last_24h > 0`

- [ ] **Step 7.3: 사용자에게 결과 보고**

리포트 내용 (텍스트 출력만, 파일 작성 아님):
- 새 채널 식별 변경 요약 (1 줄)
- Step 6.3 수집 결과: 신규 PDF N건 다운로드
- Step 7.1 태깅 결과: auto K건, review_needed M건
- review 큐 현재 총합 (기존 440 + 신규 M)
- 다음 단계 제안: review 작업 시작할지

---

## Self-Review Notes

- [x] Spec 커버리지: channel id fetch, DB label 유지, backward compat, 운영 검증 — 다 task로 분해됨.
- [x] Placeholder 스캔: 모든 step에 실제 코드/명령. "TBD" 없음.
- [x] Type 일관성: `channel_ref` 메서드 이름은 Task 1/3/4 모두 동일. `telegram_channel_id` 필드명 동일.
- [x] Backward compat: `telegram_channel_id=None`일 때 모든 기존 테스트 통과 가정 (`channel_ref()` → `telegram_channel` 반환).
- [x] 운영 위험 노트: Task 6.2에 telethon caching 주의사항 명시.
