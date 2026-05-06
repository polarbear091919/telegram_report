# 병렬 다운로드 + 백필 모드 — 설계 문서

- **작성일**: 2026-05-06
- **상위 프로젝트**: Telegram 증권 리포트 수집기 (`docs/superpowers/specs/2026-05-05-telegram-report-collector-design.md`)
- **목표**:
  1. 다운로드 처리량을 sequential → 병렬화하여 ~3x 단축
  2. `--backfill-days N` 옵션으로 과거 메시지 일괄 수집 가능 (기존 데이터 재다운로드 없음)
- **확장 방향 (이번 범위 외)**: Telegram takeout 모드 통합 (추가 ~2x), `--start-date X --end-date Y` 범위 fetch

## 동기

기준선 측정 (실제 smoke test, 12개 PDF, 평균 9초/파일, 총 106초):
- Telegram CDN throughput ~300 KB/s per connection
- collector가 download → hash → INSERT를 strictly sequential로 실행
- CPU/네트워크 모두 idle 시간 다수
- 12개월 백필(~4,380개)은 sequential로 ~8.5시간 추정 — 비현실적

또한 현재 구조는 백필 자체가 어려움: `last_seen > 0`이면 `min_id` 모드로 빠지므로 `--cutoff-days 365`로 재실행해도 과거로 거슬러 안 감.

---

## 1. 변경 범위

### 1.1 신규 환경변수

| 키 | 기본값 | 설명 |
|---|---|---|
| `MAX_CONCURRENT_DOWNLOADS` | `4` | Stage A/B에서 동시 처리할 메시지 수. 백필 시 `8` 권장. FloodWait 자주 뜨면 줄임. |

`Config` dataclass에 새 필드 `max_concurrent_downloads: int` 추가. `.env.example`에 주석 라인 추가.

### 1.2 신규 CLI 옵션

`--backfill-days N` (`--cutoff-days N`과 **mutually exclusive**, argparse 자동 거부).

```python
mode = p.add_mutually_exclusive_group()
mode.add_argument('--cutoff-days', type=int, default=None,
    help='Override INITIAL_CUTOFF_DAYS for this run (only effective on FIRST run when DB is empty).')
mode.add_argument('--backfill-days', type=int, default=None,
    help='Backfill mode: fetch from N days ago, skip already-downloaded ones. '
         'Ignores last_seen state. For one-off historical collection.')
```

### 1.3 `--dry-run --backfill-days N` 조합

`--dry-run`은 기존 옵션. 백필과 조합 시 동일한 분기 + dedupe set을 사용해 **"진짜로 다운로드 될 신규 메시지 수"**를 정확히 보고해야 함 (위험 mitigation 핵심). `_dry_run` 함수도 backfill_days 파라미터 받도록 확장:

```python
async def _dry_run(client, storage, config, backfill_days: int | None = None) -> int:
    channel = config.telegram_channel
    if backfill_days is not None:
        # 백필 모드 dry-run: 같은 dedupe set 사용
        existing_ids = storage.get_all_message_ids(channel)
        existing_ids.update(storage.get_failed_message_ids(channel))
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
    n_skipped = 0
    async for msg in msgs:
        if not has_pdf(msg):
            continue
        if existing_ids is not None and msg.id in existing_ids:
            n_skipped += 1
            continue
        log.info("  msg_id=%s sent_at=%s file=%s",
                 msg.id, msg.date.isoformat(), _get_original_filename(msg))
        n += 1
    log.info("DRY RUN — total %d new PDF messages", n)
    if existing_ids is not None:
        log.info("DRY RUN — also %d already-known messages skipped", n_skipped)
    return 0
```

→ 사용자는 `python main.py --dry-run --backfill-days 365` 로 "신규 4368개, 기존 12개 skip" 같은 결과를 받아 디스크 용량/시간 예측 후 본 실행 결정.

### 1.3 신규 메서드 / 시그니처 변경

| 위치 | 변경 | 비고 |
|---|---|---|
| `Storage.get_all_message_ids(chat_username) -> set[int]` | 신규 | 백필 모드 사전 fetch 용 |
| `collector.run(client, storage, config, backfill_days=None)` | 파라미터 1개 추가 (default None) | 기존 호출자 영향 없음 |
| `_process_one_message` | **변경 없음** | 동시 호출에 이미 안전 |
| `RunResult` | **변경 없음** | 5개 카운터 의미 그대로 |

---

## 2. 동시성 패턴

### 2.1 핵심: `asyncio.Semaphore` + `asyncio.gather`

`run()` 시작에서 Semaphore 1개 생성, Stage A/B 모두 공유:

```python
sem = asyncio.Semaphore(config.max_concurrent_downloads)
```

각 메시지 처리는 `async with sem:` 블록 내부에서 실행. `asyncio.create_task` + `gather`로 동시 실행, Semaphore가 동시 진입 수를 N으로 제한.

### 2.2 Stage A (실패 메시지 재시도, 병렬화)

```python
failed_ids = storage.get_failed_message_ids(channel)
log.info("Stage A: retrying %d previously failed messages", len(failed_ids))

async def retry_one(msg_id):
    async with sem:
        msg = await client.get_message_by_id(channel, msg_id)
        if msg is None or not has_pdf(msg):
            storage.remove_failed_attempt(channel, msg_id)
            return 'cleaned'
        try:
            await _process_one_message(client, storage, channel, msg)
            storage.remove_failed_attempt(channel, msg_id)
            return 'success'
        except Exception as e:
            log.exception("Stage A retry still failing for msg_id=%s", msg_id)
            new_count = storage.upsert_failed_attempt(channel, msg_id, str(e))
            if new_count >= ATTEMPT_WARN_THRESHOLD:
                log.warning("msg_id=%s has failed %d times — investigate manually",
                            msg_id, new_count)
            return 'fail'

stage_a_results = await asyncio.gather(*[retry_one(mid) for mid in failed_ids])
retried_success = sum(1 for r in stage_a_results if r == 'success')
retried_fail = sum(1 for r in stage_a_results if r == 'fail')
# 'cleaned' (메시지 삭제됨/PDF 아님): 어느 카운터에도 안 들어감 (기존 동작 보존)
```

### 2.3 Stage B (신규 메시지 + 백필 모드, 병렬화)

```python
# 백필 모드: Stage A 결과까지 반영된 ID set 사전 fetch
if backfill_days is not None:
    # 이미 처리된 모든 message_id 사전 fetch:
    #  - reports: Stage A에서 막 추가된 row 포함 (성공한 retry 결과)
    #  - failed_attempts: Stage A 후 여전히 failed인 메시지 (이번 실행에서 또 시도하면 중복 처리)
    # 둘 다 페이징해서 1000-row 제한 대응. 합치면 "이번 실행에서 더 이상 건드리지 말 것" 집합.
    existing_ids = storage.get_all_message_ids(channel)
    existing_ids.update(storage.get_failed_message_ids(channel))
    log.info("Backfill mode: %d existing message_ids will be skipped "
             "(reports + still-failed), fetching from %d days ago",
             len(existing_ids), backfill_days)
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

async def process_new(msg):
    async with sem:
        try:
            await _process_one_message(client, storage, channel, msg)
            return 'processed'
        except Exception as e:
            log.exception("Stage B failed to process message_id=%s", msg.id)
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
    if existing_ids is not None and msg.id in existing_ids:
        skipped += 1
        continue
    tasks.append(asyncio.create_task(process_new(msg)))

stage_b_results = await asyncio.gather(*tasks)
processed = sum(1 for r in stage_b_results if r == 'processed')
failed = sum(1 for r in stage_b_results if r == 'failed')
```

### 2.4 동시 호출 안전성 (`_process_one_message`)

| 작업 | 안전 이유 |
|---|---|
| `download_pdf_bytes` | 동일 msg_id 동시 호출 거의 불가 (iter_messages는 unique) |
| `save_pdf_atomically` | `.partial → os.replace` atomic |
| `compute_sha256` | 순수 함수, 다른 파일 |
| `insert_report_metadata` | upsert + UNIQUE(chat_username, message_id), 동시 INSERT도 안전 |

→ `_process_one_message` 코드 한 줄도 안 바꿈.

---

## 3. Storage 새 메서드 + 기존 메서드 페이징 보강

### 3.1 신규: `get_all_message_ids` (페이징)

PostgREST/Supabase는 단일 `.execute()`에 기본 1000 row 제한 적용. 12개월 백필 누적 시 reports가 1000 row를 넘으면 dedupe set이 불완전해져 **이미 받은 메시지를 다시 다운로드** 하게 됨. 명시적 페이징 loop 필수.

```python
def get_all_message_ids(self, chat_username: str) -> set[int]:
    """Return ALL message_ids already in reports for this chat.

    Pages through results explicitly because PostgREST/Supabase enforces a
    default max of 1000 rows per request — without pagination, this returns
    an incomplete set once the table exceeds that, breaking backfill dedupe.
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

### 3.2 기존 메서드 페이징 보강: `get_failed_message_ids`

같은 1000-row 제한이 `failed_attempts` 조회에도 걸린다. 일상 사용에서는 거의 발생 안 하지만(failed_attempts는 transient 오류 누적분), 백필 모드의 dedupe set에서 사용되므로 누락되면 동일 문제 발생. 동일한 페이징 패턴 적용:

```python
def get_failed_message_ids(self, chat_username: str) -> list[int]:
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

(시그니처/반환 형식은 그대로 — 외부 호출자 영향 없음.)

### 3.3 dedupe set 구성 (collector에서)

`existing_ids = reports IDs ∪ failed_attempts IDs`, **Stage A 종료 후** 호출. 두 테이블 합쳐 "이번 실행에서 더 이상 건드리지 말 것" 의미.

- `reports` 포함 이유: 이미 성공한 메시지는 다시 받을 필요 없음
- `failed_attempts` (post-Stage-A) 포함 이유: Stage A에서 재시도했으나 또 실패한 메시지를 Stage B에서 또 시도하면 같은 메시지 1회 실행에 2번 처리 + attempt_count 2회 증가 (의도와 어긋남)
- 영구 실패 메시지를 백필에서 다시 시도하려면 사용자가 수동으로 `DELETE FROM failed_attempts WHERE ...` 후 재실행

---

## 4. 테스트 전략

### 4.1 단위 테스트 (TDD)

**`test_config.py`** — 신규 2개:
- `test_load_config_max_concurrent_downloads_default`: env var 미설정 시 4
- `test_load_config_max_concurrent_downloads_override`: env var 설정 시 그 값

**`test_main.py`** — 신규 2개 + 기존 1개 수정:
- `test_parse_args_backfill_days`: `--backfill-days 365` 정상 파싱
- `test_parse_args_mutually_exclusive_raises_systemexit`: 두 옵션 동시 입력 시 SystemExit
- `test_parse_args_no_flags_defaults` 수정: `args.backfill_days is None` 추가 검증

### 4.2 백필 모드 통합 (TDD with fakes)

**`tests/conftest.py`** — `FakeStorage` 확장:
```python
def __init__(self, base_dir, max_seen=0, failed_ids=None, existing_ids=None):
    ...
    self._existing_ids = set(existing_ids or [])

def get_all_message_ids(self, chat_username):
    return set(self._existing_ids)
```

**`test_collector.py`** — 신규 5개:
- `test_backfill_mode_pre_fetches_existing_ids`: existing_ids 안의 msg는 skip
- `test_backfill_mode_includes_failed_attempts_in_skip_set`: Stage A에서 또 실패한 msg는 Stage B에서 skip (같은 실행 내 중복 처리 방지)
- `test_backfill_mode_uses_since_date_iter`: `iter_messages_since_date(channel, backfill_days)` 호출 확인
- `test_backfill_mode_runs_stage_a`: Stage A 여전히 실행 확인
- `test_normal_mode_does_not_pre_fetch`: backfill_days=None일 때 get_all_message_ids 호출 안 됨

**`test_main.py`** — 신규 1개 추가:
- `test_dry_run_with_backfill_uses_skip_set`: `_dry_run`이 backfill_days 받으면 reports + failed_attempts dedupe set으로 skip 카운트 보고

### 4.3 동시성 검증 (Observational)

**`test_collector.py`** — `TrackingFakeClient` 도입:
```python
class TrackingFakeClient(FakeTelegramClient):
    """Tracks max concurrent download_pdf_bytes calls."""
    def __init__(self):
        super().__init__()
        self.current_concurrent = 0
        self.max_concurrent_observed = 0

    async def download_pdf_bytes(self, msg):
        self.current_concurrent += 1
        self.max_concurrent_observed = max(
            self.max_concurrent_observed, self.current_concurrent
        )
        await asyncio.sleep(0.01)  # yield to other tasks
        self.current_concurrent -= 1
        return b'fake pdf bytes'
```

신규 2개:
- `test_concurrency_respects_semaphore_limit`: 10개 메시지, N=3 → max_observed ≤ 3 AND ≥ 2
- `test_concurrency_n1_is_serial`: N=1 → max_observed == 1

### 4.4 회귀 보장

기존 11개 collector 테스트 + 50/50 전체 모두 통과해야 함. `Config`에 새 필드 추가됐으니 일부 테스트의 `SimpleNamespace cfg`에 `max_concurrent_downloads=N` 추가 (작은 conftest 수정).

신규 약 12개 (config 2 + main 3 + backfill 5 + concurrency 2) + 수정 ~3개 → 총 50 → 약 62개.

**페이징 회귀 보장 (FakeStorage 동작 검증)**: FakeStorage는 메모리 set/list 반환이라 PostgREST 페이징 limit 영향 없음 (테스트 자체는 통과). 실제 페이징은 smoke test에서 1000+ row 케이스 만나기 전엔 검증 불가 — `_max_in_table` 패턴과 동일하게 단순한 페이징 loop이라 코드 리뷰로 충분. 향후 1000 넘는 백필 실행 시 결과 검증.

### 4.5 명시적으로 안 테스트하는 것 (YAGNI)

- ❌ 실제 FloodWaitError 시뮬레이션 (Telethon 내부 동작)
- ❌ 실 Supabase 동시 INSERT 부하 (smoke로 충분)
- ❌ 4380개 메시지 시뮬레이션 (성능 테스트, smoke로 충분)

---

## 5. 호환성 매트릭스

| 시나리오 | 기존 동작 | 변경 후 | 사용자 영향 |
|---|---|---|---|
| `python main.py` (옵션 없음) | sequential | **N=4 병렬** | ⚡ ~3x 빨라짐. 의미 동일. |
| `python main.py --cutoff-days 30` | sequential cutoff (DB 비어있을 때만) | 동일 + 병렬 | ⚡ 빨라짐. 의미 동일. |
| `python main.py --backfill-days 365` | (에러) | 신규: 백필 모드 | ✨ 신규 기능 |
| `python main.py --cutoff-days 30 --backfill-days 365` | (해당 없음) | argparse 자동 에러 | 명시적 거부 |
| `Config` 인스턴스화 | 9 필드 | 10 필드 | 외부 영향 없음 (main만 사용) |
| `await collector.run(client, storage, config)` | 정상 | 정상 (default `backfill_days=None`) | 시그니처 호환 |

→ 일반 사용자: `git pull` + `python main.py` → 즉시 빨라진 속도 체감, 동작 의미 동일.

---

## 6. 위험 요소 및 mitigation

| 위험 | 가능성 | 영향 | Mitigation |
|---|---|---|---|
| FloodWaitError 빈발 (특히 백필) | 중 | 60초 미만 자동 sleep, 60초 이상 task 1개 raise → failed_attempts → 다음 실행 재시도 | `MAX_CONCURRENT_DOWNLOADS` 낮춰 재시도. 다른 task는 영향 없음. |
| 동시 supabase upsert로 connection pool 포화 | 매우 낮음 | 일시적 INSERT 지연 | 기본 동작으로 충분 (httpx 기본 pool). |
| 4380개 task 객체 메모리 (백필) | 낮음 (~5MB) | 무시 가능 | 현 규모 OK. 100K+ 시 producer-consumer 전환 검토. |
| 동일 message_id 동시 다운로드 race | 사실상 0 | atomic `os.replace` + upsert로 안전 | 무방어 (이미 안전) |
| 백필 시 디스크 풀 (~13GB 추정) | 중 | 디스크 풀 위험 | `python main.py --dry-run --backfill-days N`으로 신규 PDF 개수 사전 측정 (§1.3). 단계적 확장 가이드 README 명시. |
| 1000+ 누적 reports에서 dedupe 누락 | **해결됨** | (있었다면) 백필이 기존 PDF 재다운로드 | `get_all_message_ids` 페이징 loop (§3.1) |
| Stage A 후 failed_attempts msg를 Stage B가 다시 처리 | **해결됨** | (있었다면) 동일 메시지 1회 실행에 2회 시도, attempt_count 2회씩 ++ | dedupe set에 failed_attempts 포함 (§3.3) |
| Stage A 병렬화로 attempt_count race | 매우 낮음 | upsert SELECT-then-UPDATE 비원자적 | 기존부터의 한계, MVP 범위에선 OK. UNIQUE 제약이 안전망. |

---

## 7. 성능 기대치

기준선: 12개 PDF, sequential, 평균 9초/파일, 총 106초 (실측).

| 시나리오 | N | 예상 시간 | 비고 |
|---|---|---|---|
| 12개 일상 실행 | 1 (sequential) | 106초 | 변경 전 |
| 12개 일상 실행 | 4 (기본값) | **30–40초** | 약 3x |
| 12개 일상 실행 | 8 | 25–35초 | FloodWait 가끔 |
| 12개월 백필 (~4380개) | 4 | **2.5–3시간** | 기본 설정 |
| 12개월 백필 | 8 | 1.5–2.5시간 | 적극 설정 |

---

## 8. Rollback 시나리오

운영 문제 발생 시:
1. **즉시**: `MAX_CONCURRENT_DOWNLOADS=1` env var → 사실상 sequential (Semaphore 1)
2. **영구**: Git revert (단일 PR 단위)

설정 1줄로 rollback 가능 → 위험 매우 낮음.

---

## 9. 알려진 한계 / 향후 작업

- `get_all_message_ids` / `get_failed_message_ids` 둘 다 페이징 적용됨 (§3.1, §3.2). 단 100K+ rows 시 페이징 round-trip 자체가 늘어 시간 부담 발생 (100 round trips). 그 규모 도달 시 `range`보다 RPC + cursor 전환 검토.
- `--start-date X --end-date Y` 범위 fetch 미지원. 별도 use case 발생 시 추가.
- Telegram takeout 모드 미도입. 1+2 결과 보고 ROI 평가 후 결정.
- Stage A의 `upsert_failed_attempt` race는 싱글유저 MVP에선 무해.

---

## 10. 의사결정 기록

| 결정 항목 | 선택 | 대안 (기각) |
|---|---|---|
| 동시성 패턴 | `asyncio.Semaphore` + `gather` | producer-consumer queue (오버엔지니어링) |
| 동시성 N 설정 방식 | `MAX_CONCURRENT_DOWNLOADS` env var, 기본 4 | 하드코딩 4 / CLI 옵션만 / N=8 기본 |
| Stage A 병렬화 | 함 | sequential 유지 |
| `--backfill-days` + `--cutoff-days` | argparse mutually exclusive | 한쪽 우선순위 / 동시 허용 |
| 백필 사전 fetch 대상 | `reports` ∪ `failed_attempts` (post-Stage-A) | reports만 (Stage A 후 잔존 failures가 Stage B에서 재처리되는 버그) |
| 사전 fetch 시점 | Stage A 종료 후, Stage B 시작 전 | run 시작 시 한 번 (Stage A에서 추가/잔존한 row 미반영) |
| 페이징 전략 | `range(offset, offset+999)` loop, ordered, until batch < 1000 | 단일 `.execute()` (1000-row 제한으로 dedupe 깨짐) / RPC 함수 (오버엔지니어링) |
| `--dry-run` + `--backfill-days` | 동일 분기 + 동일 dedupe set 재사용. 신규/skip 카운트 별도 보고 | dry-run 항상 normal 모드 (백필 mitigation 깨짐) |
| `_process_one_message` | 변경 없음 | streaming hash, 다른 인터페이스 |
| `Config.backfill_days` 필드 | 추가 안 함 (CLI args로 전달) | Config에 영속화 |
| 신규 의존성 | 없음 | tenacity, aiometer 등 |
| Takeout 모드 | 이번엔 X (priority 3) | 함께 도입 |
