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
    existing_ids = storage.get_all_message_ids(channel)
    log.info("Backfill mode: %d existing message_ids will be skipped, "
             "fetching from %d days ago", len(existing_ids), backfill_days)
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

## 3. Storage 새 메서드: `get_all_message_ids`

```python
def get_all_message_ids(self, chat_username: str) -> set[int]:
    """Return ALL message_ids already in reports for this chat.

    Used by backfill mode to skip messages we already have, avoiding
    redundant downloads. For typical scale (<100K rows per chat), one
    SELECT is fine. If table grows much larger, paginate.
    """
    result = (
        self._sb.table('reports')
        .select('message_id')
        .eq('chat_username', chat_username)
        .execute()
    )
    return {int(row['message_id']) for row in (result.data or [])}
```

`failed_attempts`는 의도적으로 제외:
- Stage A에서 별도 재시도되므로 Stage B에서 또 보면 중복 처리
- Stage A 종료 후 `get_all_message_ids` 호출하므로, Stage A에서 새로 성공한 row는 set에 포함됨

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

**`test_collector.py`** — 신규 4개:
- `test_backfill_mode_pre_fetches_existing_ids`: existing_ids 안의 msg는 skip
- `test_backfill_mode_uses_since_date_iter`: `iter_messages_since_date(channel, backfill_days)` 호출 확인
- `test_backfill_mode_runs_stage_a`: Stage A 여전히 실행 확인
- `test_normal_mode_does_not_pre_fetch`: backfill_days=None일 때 get_all_message_ids 호출 안 됨

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

신규 약 10개 (config 2 + main 2 + backfill 4 + concurrency 2) + 수정 ~3개 → 총 50 → 약 60개.

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
| 백필 시 디스크 풀 (~13GB 추정) | 중 | 디스크 풀 위험 | 사용자 사전 dry-run + 단계적 확장 가이드 README 명시 |
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

- `get_all_message_ids` 페이징 없음. 100K+ rows 시 메모리/시간 부담. 현 규모 OK.
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
| 백필 사전 fetch 대상 | `reports` 만 (failed_attempts 제외) | 둘 다 / 사전 fetch 안 함 |
| 사전 fetch 시점 | Stage A 종료 후, Stage B 시작 전 | run 시작 시 한 번 |
| `_process_one_message` | 변경 없음 | streaming hash, 다른 인터페이스 |
| `Config.backfill_days` 필드 | 추가 안 함 (CLI args로 전달) | Config에 영속화 |
| 신규 의존성 | 없음 | tenacity, aiometer 등 |
| Takeout 모드 | 이번엔 X (priority 3) | 함께 도입 |
