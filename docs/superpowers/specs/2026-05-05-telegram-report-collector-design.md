# Telegram 증권 리포트 수집기 — 설계 문서

- **작성일**: 2026-05-05
- **대상 채널**: `samstudy1004` (Telegram 채널, broadcast 방식)
- **MVP 목표**: 사용자가 스크립트를 실행할 때마다, 직전 실행 이후 채널에 업로드된 PDF 리포트를 모두 수집하고 메타데이터를 Supabase에 기록한다.
- **확장 방향**: 수집된 리포트에 대한 메타데이터 태깅 워커 추가 → 리서치 자료 분석 워크플로우 자동화 → 프론트엔드(리포트 자동 분석 서비스).

---

## 1. 아키텍처 & 데이터 흐름

### 1.1 모듈 구성 및 책임

| 모듈 | 책임 | 의존하는 외부 시스템 |
|---|---|---|
| `main.py` | CLI 진입점, 로깅 설정, 최상위 에러 표시 | (없음 — 다른 모듈만 호출) |
| `config.py` | `.env` 로딩, 환경변수 → 타입 안전한 `Config` 객체로 변환 | `python-dotenv` |
| `telegram_client.py` | Telethon 연결, 메시지 조회, 미디어 다운로드 | Telegram API |
| `storage.py` | Supabase INSERT/SELECT, 로컬 파일 쓰기 | Supabase, 로컬 FS |
| `collector.py` | 오케스트레이션 (어떤 메시지를 받아서 어디에 넣을지 결정) | (telegram_client + storage 호출만) |

### 1.2 모듈 경계 원칙

- `telegram_client`는 Supabase를 모름. `storage`는 Telethon을 모름. 한쪽 변경이 다른 쪽에 새지 않음.
- `collector`가 둘을 연결하는 유일한 지점. 비즈니스 룰("어떤 게 다운로드 대상인가")이 여기 모임.
- `main`은 얇음. CLI args 파싱, 에러 표시, 종료 코드만.

### 1.3 실행 시 데이터 흐름

```
[user runs `python main.py`]
        │
        ▼
┌─────────────────┐
│  main.py        │ ── CLI args 파싱, 로거 셋업
└────────┬────────┘
         │ collector.run(client, storage, config)
         ▼
┌─────────────────┐
│  collector.py   │
└────────┬────────┘
         │
         │ 1) storage.get_last_processed_message_id(channel)
         │    → returns int | None
         │
         │ 2) telegram_client.iter_new_messages(channel, after_id, cutoff_days)
         │    → async generator of Message objects
         │      ├─ last_id is None  → offset_date = now - cutoff_days (첫 실행)
         │      └─ last_id existing → min_id = last_id - OVERLAP_BUFFER (재시도 위함)
         │
         │ for each message with PDF attachment:
         │
         │   3) storage.is_already_downloaded(channel, message_id)
         │      → 멱등성 체크 (OVERLAP 범위의 이미 받은 건 여기서 skip)
         │
         │   4) telegram_client.download_pdf(message, target_path)
         │      → 로컬 디스크에 PDF 저장 (atomic via .partial → rename)
         │
         │   5) storage.insert_report_metadata(meta_dict)
         │      → Supabase에 row INSERT
         │
         │ done
         ▼
   exit 0 (성공) / 1 (실패, 메시지 출력)
```

### 1.4 핵심 설계 결정

1. **단일 진실원**: "다음 실행 때 어디서부터 받을지"는 **Supabase의 `reports` 테이블의 `MAX(message_id)`** 로 도출. 별도 state 파일/테이블 없음. 이유:
   - 동기화 문제 없음 (Supabase가 그라운드 트루스)
   - 다운로드는 됐는데 INSERT 실패 시 → 다음 실행에서 재시도됨 (덮어쓰기, 멱등성 보장)
   - INSERT는 됐는데 다운로드 실패 시 → 발생하지 않음. 순서가 "다운로드 → INSERT" 이므로.

2. **멱등성**: `(chat_username, message_id)` 컬럼에 UNIQUE 제약. 두 번 실행해도 중복 row 안 생김.

3. **수집 단위**: 메시지 단위. Media group(앨범)의 각 PDF는 별개 메시지로 처리. UNIQUE 제약으로 중복 방지.

---

## 2. Supabase 스키마

### 2.1 테이블 정의 (`migrations/001_init.sql`)

```sql
create table reports (
  -- 식별자
  id                bigserial primary key,
  message_id        bigint      not null,         -- Telegram 메시지 ID (chat 내에서 monotonic)
  chat_username     text        not null,         -- 'samstudy1004' (멀티채널 확장 대비)

  -- 시각 정보 (둘 다 UTC 저장; 표시 시 'Asia/Seoul' 변환)
  sent_at           timestamptz not null,         -- 메시지가 채널에 올라온 시각 (Telethon msg.date, UTC)
  downloaded_at     timestamptz not null default now(),

  -- 파일 정보
  file_name         text        not null,         -- Telegram 원본 파일명 (사람이 읽기용)
  file_path         text        not null,         -- STORAGE_BASE_DIR 기준 상대경로
  file_size_bytes   bigint      not null,
  file_hash_sha256  text        not null,         -- 무결성/재게시 탐지용

  -- 메시지 컨텍스트
  caption           text,                          -- 메시지 텍스트 (대부분 리포트 제목/요약 들어감)

  -- 향후 태깅 워커가 채울 컬럼 (MVP에서는 NULL)
  tags              text[],
  tagged_at         timestamptz,

  -- 멱등성 보장
  unique (chat_username, message_id)
);

-- 자주 쓸 쿼리용 인덱스
create index idx_reports_chat_msg on reports (chat_username, message_id desc);
create index idx_reports_sent_at  on reports (sent_at desc);
create index idx_reports_untagged on reports (tagged_at) where tagged_at is null;
```

### 2.2 컬럼별 의도

| 컬럼 | MVP에서의 용도 | 미래 용도 |
|---|---|---|
| `message_id` | "MAX 이후"로 신규 메시지 fetch | 원본 메시지 추적, 재처리 시 재참조 |
| `chat_username` | 단일 채널이지만 컬럼은 미리 둠 | 향후 다른 리서치 채널 추가 시 마이그레이션 불필요 |
| `caption` | 그냥 저장 | 태깅 워커가 첫 번째로 분석할 텍스트 (보통 종목명/섹터명 들어감) |
| `file_hash_sha256` | 같은 PDF가 재게시될 경우 탐지 | 중복 분석 회피 |
| `tags`, `tagged_at` | 빈 컬럼으로 시작 | 향후 워커가 채움. `tagged_at IS NULL` 인 row만 처리하면 됨 |

### 2.3 명시적으로 빼기로 한 항목 (YAGNI)

- ❌ `analysis JSONB` — 분석 결과 컬럼. 태깅 단계 시작할 때 추가.
- ❌ `category` 컬럼 — 분류 스키마 미정. `tags TEXT[]`로 통합.
- ❌ Row-Level Security 정책 — service_role key로 백엔드에서만 접근. 프론트엔드 붙일 때 정의.
- ❌ 별도 `state`/`config` 테이블 — `MAX(message_id)`로 도출.

### 2.4 마이그레이션 적용 방식

위 `CREATE TABLE` 문을 `migrations/001_init.sql`에 보관. **사용자가 Supabase 대시보드의 SQL Editor에 한 번 붙여넣기**로 실행. 자동 마이그레이션 도구(Alembic 등) 미도입.

---

## 3. Telegram 메시지 조회 전략

### 3.1 라이브러리 버전 결정

**Telethon v1.x 사용** (`telethon>=1.36,<2.0`).

배경:
- Telethon v2가 출시되어 있으나 **alpha 단계** (changelog에 `v2.0-alpha.0`로 표기)
- v2는 complete rewrite로 v1과 비호환 (`TelegramClient` → `Client`, `iter_messages` → `get_messages`)
- v1은 수년간 production 검증됨, 인터넷 예제 코드도 v1 기준

→ MVP는 v1으로 시작. 향후 v2가 stable로 전환되면 `telegram_client.py` 한 모듈만 수정하여 마이그레이션.

### 3.2 통상 실행 (2번째 이후, `last_id IS NOT NULL`)

```python
last_id = storage.get_last_processed_message_id('samstudy1004')

OVERLAP_BUFFER = 50  # 과거 실패 메시지 자동 재시도용 버퍼

async for msg in client.iter_messages(
    'samstudy1004',
    min_id=max(0, last_id - OVERLAP_BUFFER),
    reverse=True,
):
    if not has_pdf(msg):
        continue
    if storage.is_already_downloaded('samstudy1004', msg.id):
        continue  # 이미 받은 건 skip (대부분 OVERLAP 범위 내 메시지가 여기 해당)
    await process(msg)
```

- `min_id=N` → ID > N 인 메시지만 (Telegram 서버 측 필터, 효율적)
- `reverse=True` → 오래된 → 최신 순 (도중에 끊겨도 자연스럽게 이어감)
- `OVERLAP_BUFFER=50` → 과거 50개 메시지를 재스캔. `is_already_downloaded` 가 대부분 즉시 skip시키지만, **과거 다운로드 실패한 메시지가 있다면 여기서 자동 재시도됨**. 추가 비용은 ~50회 DB SELECT (인덱스 사용으로 ms 단위).

이 OVERLAP 메커니즘이 "사용자 요구사항: **아직 다운로드 하지 않은** 리포트를 모두 수집" 을 보장.

**알려진 한계**: OVERLAP_BUFFER(=50) 보다 더 오래된 실패 메시지는 자동 재시도 안 됨. 발생 시 로그에 `Failed=N` 으로 보임 → 사용자가 인지 후 수동 조치(실패 row의 `INITIAL_CUTOFF_DAYS` 임시 늘려 재실행 등). MVP 후속으로 `--retry-failed` 플래그나 watermark 테이블 도입 검토.

### 3.3 첫 실행 (`last_id IS NULL` 인 경우)

`INITIAL_CUTOFF_DAYS=30` 환경변수 사용 (기본값 30일). 첫 실행 시:

```python
from datetime import datetime, timedelta, timezone

cutoff = datetime.now(timezone.utc) - timedelta(days=config.initial_cutoff_days)
async for msg in client.iter_messages(
    'samstudy1004',
    offset_date=cutoff,
    reverse=True,
):
    if has_pdf(msg):
        await process(msg)
```

→ 백필을 원하면 `INITIAL_CUTOFF_DAYS=90` 등으로 늘려서 한 번 실행 후 다시 30으로 돌림.

### 3.4 PDF 첨부 메시지 판별

```python
def has_pdf(msg) -> bool:
    if not msg.document:
        return False
    # MIME 타입 우선 (가장 신뢰도 높음)
    if msg.document.mime_type == 'application/pdf':
        return True
    # 백업: 파일명 확장자
    for attr in msg.document.attributes:
        if hasattr(attr, 'file_name') and attr.file_name.lower().endswith('.pdf'):
            return True
    return False
```

### 3.5 Media group(앨범) 처리

여러 파일이 묶인 앨범 메시지는 Telethon이 **각각을 별개 메시지로 반환**하지만 `msg.grouped_id`가 동일. MVP에서는 grouped_id 무시하고 각 메시지를 독립 처리. UNIQUE 제약으로 중복 방지.

### 3.6 Rate Limit 대응

```python
client.flood_sleep_threshold = 60  # 60초 미만 자동 sleep, 그 이상은 raise
```

- 60초 이상 대기 필요 시 `FloodWaitError` raise → main에서 잡아 사용자에게 메시지 출력 후 종료
- MVP 규모(채널 하나, 일일 수십 건)에서는 거의 발생 안 함

---

## 4. 파일 저장 / 명명 규칙 / 중복 처리

### 4.1 디렉토리 구조

```
telegram_report/
├── reports/                          # PDF 저장소 (gitignore)
│   ├── 12345_삼성전자_2026Q1_실적전망.pdf
│   ├── 12346_LG화학_배터리.pdf
│   └── ...
├── sessions/                          # Telethon 세션 (gitignore, 매우 중요한 비밀!)
│   └── samstudy.session
├── migrations/
│   └── 001_init.sql
├── docs/superpowers/specs/            # 설계 문서
├── .env                               # 환경변수 (gitignore)
├── .env.example                       # 템플릿 (커밋)
├── .gitignore
├── main.py
├── config.py
├── telegram_client.py
├── storage.py
├── collector.py
├── requirements.txt
└── README.md
```

### 4.2 파일명 규칙

**패턴**: `{message_id}_{sanitized_original_name}`

예시:
- `삼성전자_2026Q1.pdf` + message_id 12345 → `12345_삼성전자_2026Q1.pdf`
- 원본명 없음 → `12345_unnamed.pdf`

이 패턴의 이점:
- **충돌 불가** — message_id가 채널 내 monotonic이라 절대 안 겹침
- **사람이 읽기 좋음** — 원본 제목 보존
- **시간순 정렬됨** — message_id 단조 증가 = 게시 시간 순
- **DB 없이도 식별 가능** — message_id가 prefix

### 4.3 파일명 정제 (sanitize)

```python
import re

def sanitize_filename(name: str, max_len: int = 100) -> str:
    # OS 금지문자 → _ 치환
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    # 시작/끝의 점·공백 제거 (Windows 제약)
    name = name.strip('. ')
    # .pdf 확장자 보장
    if not name.lower().endswith('.pdf'):
        name = (name or 'unnamed') + '.pdf'
    # 너무 긴 이름 자르기 (Windows MAX_PATH 260자 고려)
    if len(name) > max_len:
        name = name[:max_len - 4] + '.pdf'
    return name
```

### 4.4 다운로드 절차 (atomic)

```
1) target = reports/12345_filename.pdf
2) temp   = reports/12345_filename.pdf.partial
3) Telethon download → temp 에 씀
4) 다운로드 완료 후 sha256 계산
5) os.replace(temp, target)   # atomic rename
6) Supabase INSERT (file_path, file_hash 등)
7) 실패 시: temp 파일 그대로 두고 raise (다음 실행에서 재시도)
```

`os.replace()`는 동일 파일시스템 내에서 atomic. 도중에 끊겨도 `.partial`만 남고 본 파일은 손상 안 됨.

### 4.5 중복 처리 시나리오

| 상황 | 처리 |
|---|---|
| 동일 message_id가 DB에 이미 있음 | UNIQUE 제약으로 INSERT 거부 → 사전 SELECT로 스킵 |
| 디스크에 같은 이름 파일이 이미 존재 | `os.replace()`로 덮어쓰기 (내용 동일하니 안전) |
| `.partial` 파일이 남아있음 | 다음 다운로드 시 덮어씀 |
| 같은 PDF가 다른 message_id로 재게시됨 | 별개 row로 저장. `file_hash_sha256` 동일 → 향후 dedup 가능 |

### 4.6 `insert_report_metadata()` 에 전달되는 dict

`storage.insert_report_metadata()` 함수가 받는 dict의 정확한 키 (스키마와 1:1 매칭):

```python
{
    'message_id':       12345,                              # int (Telethon msg.id)
    'chat_username':    'samstudy1004',                     # str (config에서)
    'sent_at':          msg.date,                           # datetime (UTC, Telethon이 timezone-aware 반환)
    # downloaded_at 은 DB의 default now() 가 채움 — 보내지 않음
    'file_name':        '삼성전자_2026Q1.pdf',               # str (Telegram 원본명)
    'file_path':        'reports/12345_삼성전자_2026Q1.pdf', # str (STORAGE_BASE_DIR 기준 상대경로)
    'file_size_bytes':  1_234_567,                          # int
    'file_hash_sha256': 'abc123...',                        # str (소문자 hex)
    'caption':          msg.message,                         # str | None (msg.message은 캡션 텍스트)
    # tags, tagged_at 은 NULL 로 시작 — 보내지 않음
}
```

### 4.7 `file_path` 컬럼 저장 형식

`STORAGE_BASE_DIR` 기준 상대경로 저장. 예: `reports/12345_삼성전자.pdf`.

이유:
- 사용자가 프로젝트 폴더를 옮겨도 DB row는 유효
- 향후 PDF를 클라우드로 옮길 때 `STORAGE_BASE_DIR`만 바꾸면 마이그레이션 가능

### 4.8 .gitignore 내용

```gitignore
# Secrets - DO NOT COMMIT
.env
*.session
*.session-journal
sessions/

# Downloaded data
reports/

# Python
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/

# IDE
.idea/
.vscode/
```

### 4.9 보안 주의사항

⚠️ Telethon `.session` 파일은 본인 Telegram 계정에 대한 **인증서 그 자체**. 유출되면 누구든 본인 계정으로 로그인 가능. 절대 git 커밋/공유 금지.

---

## 5. 에러 처리 / 로깅 / 재시도

### 5.1 핵심 원칙

> **"유저가 코드를 실행할 경우"** = on-demand 스크립트이므로, 멈춰도 **재실행하면 이어지도록** 설계. 복잡한 재시도 큐 불필요.

### 5.2 에러 분류 및 처리

| 에러 종류 | 예시 | 처리 |
|---|---|---|
| **① 설정 에러** | `.env` 없음, 필수 env 누락 | 즉시 fail-fast with 명확한 메시지 (어떤 키 빠졌는지) |
| **② 인증 에러** | Telegram 세션 만료, Supabase 401 | fail-loud + 안내 ("재실행 시 SMS 코드 입력 프롬프트") |
| **③ 네트워크 에러** | Telegram/Supabase 연결 실패 | fail-loud, 사용자 수동 재시도. Telethon 내부 재시도는 활용 |
| **④ FloodWaitError** | Telegram rate limit | 60초 미만 자동 sleep, 그 이상은 raise → 대기 시간 출력 후 종료 |
| **⑤ 파일시스템 에러** | 권한, 디스크 풀 | fail-loud. 한 메시지 단위면 skip하고 계속 |
| **⑥ 단일 메시지 처리 실패** | PDF 다운로드 깨짐, INSERT 실패 | log + skip + continue. 다음 실행에서 자동 재시도 |

### 5.3 메시지 단위 에러 격리 패턴

```python
processed = skipped = failed = 0
async for msg in client.iter_messages(channel, min_id=last_id, reverse=True):
    if not has_pdf(msg):
        skipped += 1
        continue
    try:
        await process_one_message(msg)
        processed += 1
    except Exception:
        log.exception("Failed to process message_id=%s", msg.id)
        failed += 1
        # 계속 다음 메시지로

log.info("Run complete. Processed=%d Skipped=%d Failed=%d", processed, skipped, failed)
```

### 5.4 로깅

- **도구**: Python 표준 `logging` 모듈
- **출력**: stderr (CLI 표준). 파일 로그는 MVP에서 미도입
- **포맷 예시**:
  ```
  2026-05-05 21:30:15 INFO     collector  Connected to Telegram as @myusername
  2026-05-05 21:30:16 INFO     collector  Last processed message_id: 12340
  2026-05-05 21:30:17 INFO     collector  Found 5 new messages with PDF attachments
  2026-05-05 21:30:18 INFO     storage    Downloaded reports/12341_삼성전자.pdf (1.2MB)
  2026-05-05 21:30:18 INFO     storage    Inserted DB row id=42 (msg_id=12341)
  2026-05-05 21:30:25 INFO     collector  Run complete. Processed=5 Skipped=0 Failed=0
  ```
- **레벨 사용**:
  - `INFO`: 정상 진행 (사용자가 보고 싶어할 정보)
  - `WARNING`: skip 사유
  - `ERROR`: 단일 메시지 실패
  - `CRITICAL`: 전체 중단 사유 (auth/network)

### 5.5 종료 코드

- `0` — 성공 (처리 0건이어도 OK)
- `1` — 모든 실패 (config / auth / network / unhandled)

### 5.6 명시적으로 빼는 항목 (YAGNI)

- ❌ `tenacity` / 재시도 데코레이터 — 자연 재실행으로 충분
- ❌ 백오프 큐 / 작업 영속화
- ❌ 별도 체크포인트 파일 — DB의 MAX(message_id)가 자연 체크포인트
- ❌ Sentry / 외부 에러 트래킹
- ❌ Slack/Telegram 실패 알림
- ❌ 로그 파일 회전(rotation)

---

## 6. 환경변수 / 의존성 / 실행 방법

### 6.1 Python 버전

**Python 3.10+** 권장. 최소 3.8 이상.

### 6.2 의존성 (`requirements.txt`)

```
telethon>=1.36,<2.0
supabase>=2.0
python-dotenv>=1.0
```

명시적으로 빼는 것:
- ❌ `tenacity` — 자연 재실행으로 충분
- ❌ `click`/`typer` — `argparse` 표준 라이브러리로 충분
- ❌ `pydantic` — `dataclass` + 수동 검증으로 충분

### 6.3 환경변수

**필수**:

| 키 | 예시값 | 설명 |
|---|---|---|
| `TELEGRAM_API_ID` | `12345` | my.telegram.org에서 발급 |
| `TELEGRAM_API_HASH` | `abc...` (32자) | my.telegram.org에서 발급 |
| `TELEGRAM_CHANNEL` | `samstudy1004` | 대상 채널 username (@ 없이) |
| `SUPABASE_URL` | `https://iaphhvzddllabzgmhthj.supabase.co` | Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_KEY` | `eyJ...` | Supabase Settings → API → service_role key |

**선택 (기본값 제공)**:

| 키 | 기본값 | 설명 |
|---|---|---|
| `TELEGRAM_SESSION_NAME` | `samstudy` | `sessions/{name}.session` 파일 이름 |
| `STORAGE_BASE_DIR` | `./reports` | PDF 저장 폴더 |
| `INITIAL_CUTOFF_DAYS` | `30` | 첫 실행 시 며칠 전부터 수집할지 |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |

### 6.4 `.env.example`

```bash
# === Telegram API ===
# https://my.telegram.org 에서 발급
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

# 대상 채널 (username만, @는 제외)
TELEGRAM_CHANNEL=samstudy1004

# === Supabase ===
SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_SERVICE_KEY=

# === 선택: 기본값 사용하려면 비워두면 됨 ===
# TELEGRAM_SESSION_NAME=samstudy
# STORAGE_BASE_DIR=./reports
# INITIAL_CUTOFF_DAYS=30
# LOG_LEVEL=INFO
```

### 6.5 `config.py` 설계

```python
from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

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

def load_config() -> Config:
    load_dotenv()
    def req(key: str) -> str:
        v = os.getenv(key)
        if not v:
            raise SystemExit(f"Missing required env var: {key}")
        return v
    session_name = os.getenv('TELEGRAM_SESSION_NAME', 'samstudy')
    return Config(
        telegram_api_id=int(req('TELEGRAM_API_ID')),
        telegram_api_hash=req('TELEGRAM_API_HASH'),
        telegram_channel=req('TELEGRAM_CHANNEL'),
        telegram_session_path=Path('sessions') / session_name,
        supabase_url=req('SUPABASE_URL'),
        supabase_service_key=req('SUPABASE_SERVICE_KEY'),
        storage_base_dir=Path(os.getenv('STORAGE_BASE_DIR', './reports')),
        initial_cutoff_days=int(os.getenv('INITIAL_CUTOFF_DAYS', '30')),
        log_level=os.getenv('LOG_LEVEL', 'INFO'),
    )
```

→ 누락 키 있으면 시작 시점에 즉시 종료 with 명확한 메시지.

### 6.6 실행 방법

**기본 실행** (모든 옵션은 .env에서):
```bash
python main.py
```

**CLI 옵션**:

| 옵션 | 효과 |
|---|---|
| `--cutoff-days N` | 첫 실행 cutoff을 N일로 임시 변경 (.env 값 override) |
| `--dry-run` | 다운로드/INSERT 안 하고 어떤 메시지가 매칭되는지만 출력 |
| `-v` / `--verbose` | LOG_LEVEL=DEBUG로 상세 출력 |

`argparse` 표준 라이브러리만 사용. CLI args는 .env 값을 override.

### 6.7 초기 셋업 절차 (README에 기록)

```
1. 코드 클론 / 다운로드
2. python -m venv .venv
   .venv\Scripts\activate           (Windows)
   source .venv/bin/activate         (Mac/Linux)
3. pip install -r requirements.txt
4. cp .env.example .env              (Windows: copy .env.example .env)
   → .env 열어서 값 채우기
5. Supabase 대시보드 → SQL Editor → migrations/001_init.sql 내용 붙여넣고 Run
6. python main.py
   → 첫 실행 시 휴대폰 SMS 인증코드 입력 (한 번만)
7. 이후 실행은 그냥 python main.py
```

### 6.8 PyCharm Run Configuration

- Script path: `main.py`
- Working directory: 프로젝트 루트
- Python interpreter: `.venv` 가리키도록 설정
- Environment variables: 비워두면 `.env`에서 자동 로딩

→ 한 번 설정 후 ▶ 버튼으로 반복 실행 가능.

---

## 7. 향후 확장 방향 (참고용, MVP 구현 범위 외)

이 섹션은 **MVP 범위가 아님**. 설계 시 미래 확장 가능성을 고려한 부분을 기록.

### 7.1 메타데이터 태깅 워커

- 별도 모듈 `tagger.py` 추가
- `SELECT * FROM reports WHERE tagged_at IS NULL ORDER BY message_id` 로 미처리 row 조회
- PDF 텍스트 추출 (e.g., `pypdf`, `pdfplumber`) → LLM 호출 → 태그 생성
- `UPDATE reports SET tags = ?, tagged_at = NOW() WHERE id = ?`
- 인덱스 `idx_reports_untagged`로 효율적 처리

### 7.2 멀티 채널 지원

- `TELEGRAM_CHANNEL` 환경변수 → 콤마 구분 리스트로 확장
- `chat_username` 컬럼이 이미 있어 스키마 변경 불필요

### 7.3 PDF 클라우드 스토리지 마이그레이션

- `STORAGE_BASE_DIR` 추상화를 통해 로컬 → S3/Supabase Storage로 전환
- `file_path` 컬럼 의미는 그대로 유지

### 7.4 프론트엔드 연동

- Supabase에 RLS 정책 추가 (anon key로 읽기 전용 접근)
- React/Next.js 프론트가 `reports` 테이블 직접 조회
- PDF 본체는 클라우드 스토리지 URL로 제공

### 7.5 대량 백필 시 분할 다운로드

- 현재 `INITIAL_CUTOFF_DAYS=30` 기본값으로 안전장치
- 수년치 백필이 필요하면 별도 `--backfill --start-date YYYY-MM-DD --end-date YYYY-MM-DD` 옵션 추가 검토

---

## 8. 결정 요약 (의사결정 기록)

| 결정 항목 | 선택 | 대안 (기각) |
|---|---|---|
| 아키텍처 | 모듈형 4-5 파일 분리 | 단일 파일 / 비동기 파이프라인 |
| 메타데이터 저장소 | Supabase (Postgres) | SQLite 로컬 |
| PDF 저장소 | 로컬 단일 폴더 | Supabase Storage / 카테고리별 분류 |
| 상태 추적 | `MAX(message_id)` 도출 + OVERLAP_BUFFER=50 | 별도 state.json / state 테이블 / per-message 상태 |
| Telethon 버전 | v1.x (`>=1.36,<2.0`) | v2 (alpha라 기각) |
| 첫 실행 정책 | `INITIAL_CUTOFF_DAYS=30` | 전체 히스토리 / baseline만 |
| 파일명 패턴 | `{message_id}_{sanitized_원본}` | 원본만 / 해시 / 날짜 prefix |
| 재시도 전략 | 자연 재실행 (skill 미도입) | tenacity / DLQ / 백오프 |
| CLI 프레임워크 | `argparse` (stdlib) | click / typer |
| 설정 검증 | `dataclass` + 수동 | pydantic |
| Python 버전 | 3.10+ | 3.8/3.9 |
