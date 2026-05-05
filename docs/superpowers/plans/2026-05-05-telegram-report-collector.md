# Telegram Report Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MVP CLI tool that, on each user-triggered run, collects PDF reports from a single Telegram channel (`sunstudy1004`) into a local `./reports/` folder and writes metadata to a Supabase Postgres table. Failed downloads are tracked in a separate `failed_attempts` table and auto-retried on subsequent runs.

**Architecture:** Modular Python script with five files (`main`, `config`, `telegram_client`, `storage`, `collector`). Each run executes two phases: (A) retry every message currently in `failed_attempts`, (B) fetch new messages via `min_id = MAX(reports ∪ failed_attempts)` and process each one. PDFs are saved with atomic `.partial → rename`. State of "what we've seen" is derived purely from the two DB tables — no separate state file.

**Tech Stack:** Python 3.10+, Telethon 1.x (`>=1.36,<2.0`), supabase-py 2.x, python-dotenv. Tests use pytest + pytest-asyncio + stdlib `unittest.mock`. Reference spec: `docs/superpowers/specs/2026-05-05-telegram-report-collector-design.md`.

---

## File Structure (post-implementation)

```
telegram_report/
├── reports/                          # PDF storage (gitignored, runtime-created)
├── sessions/                          # Telethon sessions (gitignored, runtime-created)
├── migrations/
│   └── 001_init.sql                  # Supabase DDL — user pastes into SQL editor
├── docs/superpowers/
│   ├── specs/2026-05-05-telegram-report-collector-design.md
│   └── plans/2026-05-05-telegram-report-collector.md
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_storage_pure.py          # sanitize_filename, compute_sha256
│   ├── test_storage_files.py         # save_pdf with tmp_path
│   ├── test_telegram_pdf.py          # has_pdf, _get_original_filename
│   └── test_collector.py             # run() with mocks
├── .env.example                       # Committed template
├── .gitignore
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── main.py                            # CLI entry point (~80 lines)
├── config.py                          # Config dataclass + load_config (~60 lines)
├── telegram_client.py                 # TelegramClient wrapper + has_pdf (~100 lines)
├── storage.py                         # Storage class + pure helpers (~150 lines)
└── collector.py                       # run() + _process_one_message (~120 lines)
```

**Module responsibilities** (from spec §1.1):

- `main.py` — CLI entry, argparse, logger setup, exit-code translation. Knows nothing about Telegram/Supabase internals.
- `config.py` — Loads `.env` into a frozen `Config` dataclass. Fails fast on missing required keys.
- `telegram_client.py` — Thin wrapper over Telethon. Exposes `iter_messages_after_id`, `iter_messages_since_date`, `get_message_by_id`, `download_pdf`, plus the pure `has_pdf` predicate.
- `storage.py` — `Storage` class wraps a supabase client + filesystem base dir. Two pure helpers (`sanitize_filename`, `compute_sha256`) live at module level.
- `collector.py` — Pure orchestration: `async def run(client, storage, config) -> RunResult`. Holds the two-phase logic from spec §3.2.

---

## Tasks

### Task 1: Project skeleton

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py` (empty marker)
- Create: `tests/conftest.py` (empty for now, fixtures added in later tasks)

- [ ] **Step 1: Create `requirements.txt`**

```
telethon>=1.36,<2.0
supabase>=2.0,<3.0
python-dotenv>=1.0,<2.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 3: Create `.env.example`**

```bash
# === Telegram API ===
# https://my.telegram.org 에서 발급
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

# 대상 채널 (username만, @ 제외)
TELEGRAM_CHANNEL=sunstudy1004

# === Supabase ===
SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_SERVICE_KEY=

# === 선택: 기본값 사용하려면 비워두면 됨 ===
# TELEGRAM_SESSION_NAME=samstudy
# STORAGE_BASE_DIR=./reports
# INITIAL_CUTOFF_DAYS=30
# LOG_LEVEL=INFO
```

- [ ] **Step 4: Create `.gitignore`**

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

- [ ] **Step 5: Create `tests/__init__.py`**

(Empty file. Marks `tests/` as a package so pytest can discover it cleanly.)

```python
```

- [ ] **Step 6: Create `tests/conftest.py`**

(Empty for now; fixtures added in later tasks.)

```python
```

- [ ] **Step 7: Set up venv and install deps**

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux
pip install -r requirements-dev.txt
```

Expected: pip installs telethon, supabase, python-dotenv, pytest, pytest-asyncio with no errors.

- [ ] **Step 8: Verify pytest discovers nothing yet**

```bash
pytest -q
```

Expected: `no tests ran` (exit 5 on pytest, that's normal — no tests written yet).

- [ ] **Step 9: Commit**

```bash
git add requirements.txt requirements-dev.txt .env.example .gitignore tests/
git commit -m "chore: project skeleton (deps, env template, gitignore, test dir)"
```

---

### Task 2: SQL migration

**Files:**
- Create: `migrations/001_init.sql`

This file is static SQL that the user pastes into Supabase SQL Editor. No tests — verified manually when the user runs it (Task 11).

- [ ] **Step 1: Create `migrations/001_init.sql`**

```sql
-- 성공적으로 다운로드된 리포트
create table reports (
  id                bigserial primary key,
  message_id        bigint      not null,
  chat_username     text        not null,

  -- 시각 정보 (둘 다 UTC; 표시 시 'Asia/Seoul' 변환)
  sent_at           timestamptz not null,
  downloaded_at     timestamptz not null default now(),

  -- 파일 정보
  file_name         text        not null,
  file_path         text        not null,         -- STORAGE_BASE_DIR-relative (filename only in MVP)
  file_size_bytes   bigint      not null,
  file_hash_sha256  text        not null,

  -- 메시지 컨텍스트
  caption           text,

  -- 향후 태깅 워커가 채울 컬럼
  tags              text[],
  tagged_at         timestamptz,

  unique (chat_username, message_id)
);

-- 다운로드 실패한 메시지 (다음 실행에서 재시도 대상)
create table failed_attempts (
  id              bigserial primary key,
  message_id      bigint      not null,
  chat_username   text        not null,

  first_failed_at timestamptz not null default now(),
  last_failed_at  timestamptz not null default now(),
  attempt_count   int         not null default 1,
  error_message   text,

  unique (chat_username, message_id)
);

create index idx_reports_chat_msg on reports (chat_username, message_id desc);
create index idx_reports_sent_at  on reports (sent_at desc);
create index idx_reports_untagged on reports (tagged_at) where tagged_at is null;
create index idx_failed_chat on failed_attempts (chat_username, message_id);

-- RLS: 정책 없음 = anon/authenticated 거부. service_role은 우회.
alter table reports enable row level security;
alter table failed_attempts enable row level security;
```

- [ ] **Step 2: Commit**

```bash
git add migrations/001_init.sql
git commit -m "feat: add Supabase schema (reports + failed_attempts) with RLS"
```

---

### Task 3: Config module (TDD)

**Files:**
- Create: `tests/test_config.py`
- Create: `config.py`

- [ ] **Step 1: Write failing test for happy path**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from config import Config, load_config


def test_load_config_happy_path(monkeypatch):
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'abcdef0123456789')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'sunstudy1004')
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'eyJtest')
    # Don't set optional vars — they should pick up defaults

    cfg = load_config()

    assert isinstance(cfg, Config)
    assert cfg.telegram_api_id == 12345
    assert cfg.telegram_api_hash == 'abcdef0123456789'
    assert cfg.telegram_channel == 'sunstudy1004'
    assert cfg.supabase_url == 'https://test.supabase.co'
    assert cfg.supabase_service_key == 'eyJtest'
    # Defaults
    assert cfg.telegram_session_path == Path('sessions') / 'samstudy'
    assert cfg.storage_base_dir == Path('./reports')
    assert cfg.initial_cutoff_days == 30
    assert cfg.log_level == 'INFO'


def test_load_config_missing_required_var_exits(monkeypatch):
    # Only set some of the required vars
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.delenv('TELEGRAM_API_HASH', raising=False)
    monkeypatch.delenv('TELEGRAM_CHANNEL', raising=False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_KEY', raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_config()
    # Message should mention which key is missing
    assert 'TELEGRAM_API_HASH' in str(exc_info.value)


def test_load_config_optional_overrides(monkeypatch):
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'c')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.setenv('TELEGRAM_SESSION_NAME', 'mysess')
    monkeypatch.setenv('STORAGE_BASE_DIR', '/tmp/my_reports')
    monkeypatch.setenv('INITIAL_CUTOFF_DAYS', '7')
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')

    cfg = load_config()

    assert cfg.telegram_session_path == Path('sessions') / 'mysess'
    assert cfg.storage_base_dir == Path('/tmp/my_reports')
    assert cfg.initial_cutoff_days == 7
    assert cfg.log_level == 'DEBUG'
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: All 3 tests FAIL with `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Implement `config.py`**

```python
"""Load environment variables into a typed, frozen Config object.

Fails fast on missing required keys.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

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
    """Load env vars from .env (if present) and process environment.

    Raises SystemExit (with a descriptive message) if any required key is missing.
    """
    load_dotenv()

    def required(key: str) -> str:
        v = os.getenv(key)
        if not v:
            raise SystemExit(f"Missing required env var: {key}")
        return v

    session_name = os.getenv('TELEGRAM_SESSION_NAME', 'samstudy')

    return Config(
        telegram_api_id=int(required('TELEGRAM_API_ID')),
        telegram_api_hash=required('TELEGRAM_API_HASH'),
        telegram_channel=required('TELEGRAM_CHANNEL'),
        telegram_session_path=Path('sessions') / session_name,
        supabase_url=required('SUPABASE_URL'),
        supabase_service_key=required('SUPABASE_SERVICE_KEY'),
        storage_base_dir=Path(os.getenv('STORAGE_BASE_DIR', './reports')),
        initial_cutoff_days=int(os.getenv('INITIAL_CUTOFF_DAYS', '30')),
        log_level=os.getenv('LOG_LEVEL', 'INFO'),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config module with .env loading and validation"
```

---

### Task 4: Pure utilities — sanitize_filename + compute_sha256 (TDD)

**Files:**
- Create: `tests/test_storage_pure.py`
- Create: `storage.py` (initial — only the two pure functions for now)

- [ ] **Step 1: Write failing tests**

`tests/test_storage_pure.py`:

```python
from pathlib import Path

import pytest

from storage import compute_sha256, sanitize_filename


# === sanitize_filename ===

def test_sanitize_normal_filename_unchanged():
    assert sanitize_filename('삼성전자_2026Q1.pdf') == '삼성전자_2026Q1.pdf'


def test_sanitize_strips_forbidden_chars():
    # Windows-forbidden: < > : " / \ | ? *
    raw = 'bad<name>:"with"/forbidden\\chars|?.pdf'
    out = sanitize_filename(raw)
    for ch in '<>:"/\\|?':
        assert ch not in out
    assert out.endswith('.pdf')


def test_sanitize_strips_control_chars():
    raw = 'file\x00with\x1fcontrol.pdf'
    out = sanitize_filename(raw)
    assert '\x00' not in out
    assert '\x1f' not in out


def test_sanitize_strips_leading_trailing_dots_spaces():
    assert sanitize_filename('  .file.pdf.  ').strip('. ') == sanitize_filename('  .file.pdf.  ')
    assert not sanitize_filename('  .file.pdf.  ').startswith('.')
    assert not sanitize_filename('  .file.pdf.  ').endswith(' ')


def test_sanitize_appends_pdf_when_missing():
    assert sanitize_filename('no_extension').endswith('.pdf')


def test_sanitize_keeps_pdf_when_present():
    out = sanitize_filename('already.pdf')
    assert out.lower().count('.pdf') == 1


def test_sanitize_truncates_long_names():
    long_name = 'x' * 200 + '.pdf'
    out = sanitize_filename(long_name, max_len=100)
    assert len(out) <= 100
    assert out.endswith('.pdf')


def test_sanitize_empty_input_becomes_unnamed():
    assert sanitize_filename('') == 'unnamed.pdf'


def test_sanitize_only_dots_and_spaces_becomes_unnamed():
    out = sanitize_filename('   ...   ')
    # After stripping dots/spaces, empty → fallback to 'unnamed' + '.pdf'
    assert out == 'unnamed.pdf'


# === compute_sha256 ===

def test_compute_sha256_known_value(tmp_path):
    f = tmp_path / 'test.bin'
    f.write_bytes(b'hello world')
    # Known sha256 of "hello world"
    expected = 'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9'
    assert compute_sha256(f) == expected


def test_compute_sha256_empty_file(tmp_path):
    f = tmp_path / 'empty.bin'
    f.write_bytes(b'')
    expected = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    assert compute_sha256(f) == expected


def test_compute_sha256_handles_large_file_in_chunks(tmp_path):
    # Verify we don't OOM by reading whole file at once
    f = tmp_path / 'big.bin'
    # 5 MB file
    f.write_bytes(b'A' * (5 * 1024 * 1024))
    result = compute_sha256(f)
    assert isinstance(result, str)
    assert len(result) == 64  # sha256 hex digest length
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_storage_pure.py -v
```

Expected: All tests FAIL with `ImportError` from `storage`.

- [ ] **Step 3: Implement `storage.py` (pure functions only)**

```python
"""Storage layer: Supabase metadata + local PDF filesystem.

This module also exports two pure helpers:
- sanitize_filename: make a Telegram-supplied name safe for the filesystem.
- compute_sha256: chunked file hash for integrity tracking.

The Storage class (Supabase + filesystem operations) is added in later tasks.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Windows-forbidden filename chars + ASCII control chars (\x00–\x1f)
_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, max_len: int = 100) -> str:
    """Convert an arbitrary string into a safe filename.

    Rules (in order):
      1. Replace OS-forbidden chars with '_'
      2. Strip leading/trailing dots and spaces (Windows quirk)
      3. Ensure name is non-empty (fallback to 'unnamed')
      4. Ensure '.pdf' extension
      5. Truncate to max_len, preserving '.pdf' suffix
    """
    # 1. Remove forbidden chars
    name = _FORBIDDEN_CHARS.sub('_', name)
    # 2. Strip dots/spaces from edges
    name = name.strip('. ')
    # 3. Empty fallback
    if not name:
        name = 'unnamed'
    # 4. Ensure .pdf
    if not name.lower().endswith('.pdf'):
        name = name + '.pdf'
    # 5. Truncate (keep .pdf suffix)
    if len(name) > max_len:
        name = name[: max_len - 4] + '.pdf'
    return name


def compute_sha256(file_path: Path, chunk_size: int = 64 * 1024) -> str:
    """Compute SHA-256 of a file by streaming in chunks.

    Returns lowercase hex digest. Avoids loading the whole file into memory.
    """
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_storage_pure.py -v
```

Expected: All ~10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage_pure.py
git commit -m "feat: add sanitize_filename and compute_sha256 pure helpers"
```

---

### Task 5: PDF detection — has_pdf + filename extractor (TDD)

**Files:**
- Create: `tests/test_telegram_pdf.py`
- Create: `telegram_client.py` (initial — only the two pure functions)

- [ ] **Step 1: Write failing tests**

`tests/test_telegram_pdf.py`:

```python
"""Tests for has_pdf and _get_original_filename — both pure given a Telethon-shaped object.

We use simple namespace objects to mimic Telethon's Message structure without importing it.
"""
from __future__ import annotations

from types import SimpleNamespace

from telegram_client import has_pdf, _get_original_filename


def _msg_with_doc(mime_type: str | None, file_name: str | None) -> SimpleNamespace:
    """Build a minimal Telethon-Message-like object for testing."""
    attrs = []
    if file_name is not None:
        attrs.append(SimpleNamespace(file_name=file_name))
    doc = SimpleNamespace(mime_type=mime_type, attributes=attrs)
    return SimpleNamespace(document=doc)


def _msg_text_only() -> SimpleNamespace:
    return SimpleNamespace(document=None)


# === has_pdf ===

def test_has_pdf_text_only_message_returns_false():
    assert has_pdf(_msg_text_only()) is False


def test_has_pdf_pdf_mime_returns_true():
    msg = _msg_with_doc(mime_type='application/pdf', file_name='report.pdf')
    assert has_pdf(msg) is True


def test_has_pdf_falls_back_to_extension_when_mime_missing():
    msg = _msg_with_doc(mime_type='application/octet-stream', file_name='report.PDF')
    assert has_pdf(msg) is True


def test_has_pdf_no_mime_no_pdf_extension_returns_false():
    msg = _msg_with_doc(mime_type='application/zip', file_name='archive.zip')
    assert has_pdf(msg) is False


def test_has_pdf_no_filename_attr_falls_back_to_mime():
    msg = _msg_with_doc(mime_type='application/pdf', file_name=None)
    assert has_pdf(msg) is True


def test_has_pdf_no_filename_no_mime_returns_false():
    msg = _msg_with_doc(mime_type=None, file_name=None)
    assert has_pdf(msg) is False


# === _get_original_filename ===

def test_get_filename_returns_attr_value():
    msg = _msg_with_doc(mime_type='application/pdf', file_name='hello.pdf')
    assert _get_original_filename(msg) == 'hello.pdf'


def test_get_filename_returns_none_when_no_document():
    assert _get_original_filename(_msg_text_only()) is None


def test_get_filename_returns_none_when_no_filename_attribute():
    msg = _msg_with_doc(mime_type='application/pdf', file_name=None)
    assert _get_original_filename(msg) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_telegram_pdf.py -v
```

Expected: All tests FAIL with `ImportError` from `telegram_client`.

- [ ] **Step 3: Implement initial `telegram_client.py`**

```python
"""Telethon wrapper + pure PDF predicates.

Only the pure functions (`has_pdf`, `_get_original_filename`) are in this initial cut.
The async TelegramClient class is added in Task 8.
"""
from __future__ import annotations

from typing import Any


def has_pdf(msg: Any) -> bool:
    """Return True if the message has a PDF attachment.

    Strategy:
      1. If no document at all → False
      2. If document.mime_type == 'application/pdf' → True (most reliable)
      3. Else, scan attributes for any file_name ending in .pdf (case-insensitive)
      4. Else → False
    """
    if not getattr(msg, 'document', None):
        return False
    if msg.document.mime_type == 'application/pdf':
        return True
    for attr in getattr(msg.document, 'attributes', []):
        file_name = getattr(attr, 'file_name', None)
        if file_name and file_name.lower().endswith('.pdf'):
            return True
    return False


def _get_original_filename(msg: Any) -> str | None:
    """Extract the Telegram-original file_name attribute, or None."""
    if not getattr(msg, 'document', None):
        return None
    for attr in getattr(msg.document, 'attributes', []):
        file_name = getattr(attr, 'file_name', None)
        if file_name:
            return file_name
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_telegram_pdf.py -v
```

Expected: All ~9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telegram_client.py tests/test_telegram_pdf.py
git commit -m "feat: add has_pdf and filename extractor for Telethon messages"
```

---

### Task 6: Storage — atomic file save (TDD with tmp_path)

**Files:**
- Modify: `storage.py` (add `Storage` class skeleton + `save_pdf_atomically` method)
- Create: `tests/test_storage_files.py`

- [ ] **Step 1: Write failing tests**

`tests/test_storage_files.py`:

```python
"""Tests for Storage.save_pdf_atomically — uses tmp_path; no Supabase needed."""
from __future__ import annotations

from pathlib import Path

import pytest

from storage import Storage


@pytest.fixture
def storage(tmp_path) -> Storage:
    """Storage with a None supabase client (filesystem-only tests)."""
    return Storage(supabase_client=None, base_dir=tmp_path)


def test_save_pdf_writes_file_to_base_dir(storage, tmp_path):
    target = storage.save_pdf_atomically(b'fake pdf content', '12345_report.pdf')
    assert target == tmp_path / '12345_report.pdf'
    assert target.read_bytes() == b'fake pdf content'


def test_save_pdf_creates_base_dir_if_missing(tmp_path):
    nested = tmp_path / 'nested' / 'dir'
    storage = Storage(supabase_client=None, base_dir=nested)
    target = storage.save_pdf_atomically(b'data', 'x.pdf')
    assert nested.exists()
    assert target.read_bytes() == b'data'


def test_save_pdf_is_atomic_no_partial_left_after_success(storage, tmp_path):
    storage.save_pdf_atomically(b'ok', '1_a.pdf')
    partials = list(tmp_path.glob('*.partial'))
    assert partials == []


def test_save_pdf_overwrites_existing_target(storage, tmp_path):
    target = tmp_path / 'dup.pdf'
    target.write_bytes(b'old')
    storage.save_pdf_atomically(b'new', 'dup.pdf')
    assert target.read_bytes() == b'new'


def test_save_pdf_overwrites_stale_partial(storage, tmp_path):
    # Simulate leftover from a previous interrupted run
    stale = tmp_path / 'fresh.pdf.partial'
    stale.write_bytes(b'leftover')
    storage.save_pdf_atomically(b'fresh', 'fresh.pdf')
    assert (tmp_path / 'fresh.pdf').read_bytes() == b'fresh'
    # Atomic rename should have consumed/replaced the .partial
    assert not stale.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_storage_files.py -v
```

Expected: All tests FAIL with `ImportError` (no Storage class yet).

- [ ] **Step 3: Add Storage class skeleton + `save_pdf_atomically`**

Append to `storage.py`:

```python
import os
from typing import Any


class Storage:
    """Storage facade over Supabase (metadata) + local filesystem (PDF blobs).

    The supabase_client is `Any` to keep this module decoupled from supabase-py
    types; pass a real `supabase.Client` in production, or `None` in
    filesystem-only tests.
    """

    def __init__(self, supabase_client: Any, base_dir: Path) -> None:
        self._sb = supabase_client
        self.base_dir = Path(base_dir)

    # === Filesystem ===

    def save_pdf_atomically(self, content: bytes, filename: str) -> Path:
        """Write `content` to `base_dir/filename` atomically.

        Strategy: write to `<filename>.partial`, then `os.replace()` to
        the final name (atomic on the same filesystem).

        Returns the final Path on success. Raises on filesystem errors.
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
        target = self.base_dir / filename
        partial = target.with_suffix(target.suffix + '.partial')
        partial.write_bytes(content)
        os.replace(partial, target)
        return target
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_storage_files.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage_files.py
git commit -m "feat: add Storage class with atomic PDF write"
```

---

### Task 7: Storage — Supabase methods (no unit tests; manual smoke verification in Task 11)

**Files:**
- Modify: `storage.py` (add Supabase methods + `build_storage` factory)

Rationale: supabase-py uses chained-builder API (`sb.table().select().eq().execute()`) that's awkward to mock meaningfully. We rely on Task 11's smoke test against the real Supabase project for behavioral verification. The methods are kept tiny to minimize risk.

- [ ] **Step 1: Add Supabase methods to `Storage` class**

Append to `storage.py` (inside the `Storage` class):

```python
    # === Supabase ===

    def get_max_seen_message_id(self, chat_username: str) -> int:
        """Return max(message_id) from reports ∪ failed_attempts for this chat.

        Returns 0 if the channel has no rows yet (= first run).
        """
        # Two queries → max in Python. Cleaner than UNION via the supabase-py builder.
        max_reports = self._max_in_table('reports', chat_username)
        max_failed = self._max_in_table('failed_attempts', chat_username)
        return max(max_reports, max_failed)

    def _max_in_table(self, table: str, chat_username: str) -> int:
        result = (
            self._sb.table(table)
            .select('message_id')
            .eq('chat_username', chat_username)
            .order('message_id', desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return 0
        return int(result.data[0]['message_id'])

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

    def insert_report_metadata(self, meta: dict) -> None:
        """Upsert a row into reports keyed on (chat_username, message_id).

        Idempotent at the DB layer: re-running with the same key updates the row
        with identical data (harmless), avoiding stuck-retry loops when an INSERT
        appears to fail but actually committed (transient timeouts).

        Required keys (see spec §4.6):
          message_id, chat_username, sent_at, file_name, file_path,
          file_size_bytes, file_hash_sha256
        Optional: caption.
        """
        # sent_at must be ISO-format string for supabase-py over REST
        payload = dict(meta)
        sent_at = payload.get('sent_at')
        if sent_at is not None and not isinstance(sent_at, str):
            payload['sent_at'] = sent_at.isoformat()
        self._sb.table('reports').upsert(
            payload,
            on_conflict='chat_username,message_id',
        ).execute()

    def upsert_failed_attempt(
        self, chat_username: str, message_id: int, error_message: str
    ) -> int:
        """Insert a new failed_attempts row, or increment attempt_count if it exists.

        Returns the NEW attempt_count value (1 on first failure, prev+1 on retry).
        Caller can use this for threshold-based warnings (spec §5.3).
        """
        # supabase-py `upsert` with on_conflict requires us to manage attempt_count
        # manually, since we want += 1 on conflict. So: SELECT first, then INSERT or UPDATE.
        existing = (
            self._sb.table('failed_attempts')
            .select('id, attempt_count')
            .eq('chat_username', chat_username)
            .eq('message_id', message_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            row = existing.data[0]
            new_count = int(row['attempt_count']) + 1
            self._sb.table('failed_attempts').update({
                'attempt_count': new_count,
                'last_failed_at': datetime.now(timezone.utc).isoformat(),
                'error_message': error_message,
            }).eq('id', row['id']).execute()
            return new_count
        else:
            self._sb.table('failed_attempts').insert({
                'message_id': message_id,
                'chat_username': chat_username,
                'attempt_count': 1,
                'error_message': error_message,
            }).execute()
            return 1

    def remove_failed_attempt(self, chat_username: str, message_id: int) -> None:
        """Delete the failed_attempts row for this message (no-op if absent)."""
        (
            self._sb.table('failed_attempts')
            .delete()
            .eq('chat_username', chat_username)
            .eq('message_id', message_id)
            .execute()
        )
```

- [ ] **Step 2: Add `build_storage` factory at module bottom**

Append at the end of `storage.py`:

```python
def build_storage(supabase_url: str, supabase_service_key: str, base_dir: Path) -> Storage:
    """Construct a Storage with a real supabase client. Used by main.py."""
    from supabase import create_client  # imported lazily to keep tests fast

    client = create_client(supabase_url, supabase_service_key)
    return Storage(supabase_client=client, base_dir=base_dir)
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
pytest tests/ -v
```

Expected: all previous tests (config, storage_pure, storage_files, telegram_pdf) still PASS. No new tests added in this task.

- [ ] **Step 4: Commit**

```bash
git add storage.py
git commit -m "feat: add Storage methods for reports + failed_attempts tables"
```

---

### Task 8: TelegramClient class (no unit tests; behavior verified via collector tests + smoke)

**Files:**
- Modify: `telegram_client.py` (add `TelegramClient` class)

Rationale: Telethon's API is async + stateful (network connection, session DB). Mocking it for unit tests provides little value. The collector tests in Task 9 use a fake TelegramClient. End-to-end behavior is verified in Task 11.

- [ ] **Step 1: Add `TelegramClient` class to `telegram_client.py`**

Append to `telegram_client.py`:

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from telethon import TelegramClient as _TelethonClient
from telethon.tl.custom.message import Message  # type: ignore


class TelegramClient:
    """Thin async wrapper around Telethon for our specific use case.

    Use as an async context manager:
        async with TelegramClient(api_id, api_hash, session_path) as client:
            async for msg in client.iter_messages_after_id(...):
                ...
    """

    def __init__(self, api_id: int, api_hash: str, session_path: Path) -> None:
        # Ensure parent dir exists; Telethon won't create it
        session_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = _TelethonClient(
            session=str(session_path),
            api_id=api_id,
            api_hash=api_hash,
        )
        # Auto-sleep on FloodWaitError under 60s; raise above
        self._client.flood_sleep_threshold = 60

    async def __aenter__(self) -> 'TelegramClient':
        await self._client.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.disconnect()

    async def iter_messages_after_id(
        self, channel: str, min_id: int
    ) -> AsyncIterator[Message]:
        """Yield messages with id > min_id, oldest first."""
        async for msg in self._client.iter_messages(channel, min_id=min_id, reverse=True):
            yield msg

    async def iter_messages_since_date(
        self, channel: str, days_ago: int
    ) -> AsyncIterator[Message]:
        """First-run path: yield all messages since `days_ago` days ago, oldest first."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_ago)
        async for msg in self._client.iter_messages(channel, offset_date=cutoff, reverse=True):
            yield msg

    async def get_message_by_id(self, channel: str, message_id: int) -> Message | None:
        """Fetch a single message by id. Returns None if deleted/not found."""
        return await self._client.get_messages(channel, ids=message_id)

    async def download_pdf_bytes(self, msg: Message) -> bytes:
        """Download the PDF attached to `msg` and return its bytes.

        We download into memory so storage.save_pdf_atomically can handle the
        atomic write. Reports are typically ~1–10 MB, well within RAM.
        """
        result = await self._client.download_media(msg, file=bytes)
        if not isinstance(result, (bytes, bytearray)):
            raise RuntimeError(f'download_media returned unexpected type: {type(result)}')
        return bytes(result)
```

- [ ] **Step 2: Verify existing tests still pass + import works**

```bash
pytest tests/ -v
python -c "from telegram_client import TelegramClient, has_pdf; print('OK')"
```

Expected: all tests PASS, import prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add telegram_client.py
git commit -m "feat: add TelegramClient async wrapper around Telethon"
```

---

### Task 9: Collector orchestration (TDD with mocks)

**Files:**
- Create: `tests/test_collector.py`
- Create: `collector.py`

This is the core business logic. We test it with fake `TelegramClient` and `Storage` that record their calls and return scripted results — no real network or DB.

- [ ] **Step 1: Add shared fixtures to `tests/conftest.py`**

Replace the empty `tests/conftest.py` with:

```python
"""Shared pytest fixtures for collector tests."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def make_msg(msg_id: int, *, has_pdf: bool = True, file_name: str = 'r.pdf',
             caption: str | None = None,
             sent_at: datetime | None = None) -> SimpleNamespace:
    """Build a fake Telethon-Message-like object for collector tests."""
    if has_pdf:
        attrs = [SimpleNamespace(file_name=file_name)]
        doc = SimpleNamespace(mime_type='application/pdf', attributes=attrs)
    else:
        doc = None
    return SimpleNamespace(
        id=msg_id,
        document=doc,
        message=caption,
        date=sent_at or datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
    )


class FakeTelegramClient:
    """In-memory fake matching the TelegramClient interface used by collector."""

    def __init__(self) -> None:
        self.new_messages: list[Any] = []          # for iter_messages_after_id / since_date
        self.failed_lookups: dict[int, Any] = {}   # for get_message_by_id
        self.download_results: dict[int, bytes] = {}  # msg_id -> bytes
        self.download_errors: dict[int, Exception] = {}  # msg_id -> exception
        self.calls: list[tuple] = []               # records (method_name, args)

    async def iter_messages_after_id(self, channel: str, min_id: int):
        self.calls.append(('iter_after_id', channel, min_id))
        for m in self.new_messages:
            yield m

    async def iter_messages_since_date(self, channel: str, days_ago: int):
        self.calls.append(('iter_since_date', channel, days_ago))
        for m in self.new_messages:
            yield m

    async def get_message_by_id(self, channel: str, message_id: int):
        self.calls.append(('get_by_id', channel, message_id))
        return self.failed_lookups.get(message_id)

    async def download_pdf_bytes(self, msg) -> bytes:
        self.calls.append(('download', msg.id))
        if msg.id in self.download_errors:
            raise self.download_errors[msg.id]
        return self.download_results.get(msg.id, b'fake pdf bytes')


class FakeStorage:
    """In-memory fake matching the Storage interface used by collector."""

    def __init__(self, base_dir: Path, max_seen: int = 0,
                 failed_ids: list[int] | None = None) -> None:
        self.base_dir = base_dir
        self._max_seen = max_seen
        self._failed_ids = list(failed_ids or [])
        self.inserted: list[dict] = []
        self.failed_upserts: list[tuple[str, int, str]] = []
        self.failed_removes: list[tuple[str, int]] = []
        self.saved_files: list[tuple[str, bytes]] = []

    def get_max_seen_message_id(self, chat_username: str) -> int:
        return self._max_seen

    def get_failed_message_ids(self, chat_username: str) -> list[int]:
        return list(self._failed_ids)

    def insert_report_metadata(self, meta: dict) -> None:
        self.inserted.append(meta)

    def upsert_failed_attempt(self, chat_username: str, message_id: int,
                              error_message: str) -> int:
        self.failed_upserts.append((chat_username, message_id, error_message))
        # Count occurrences of this (chat, msg_id) to mimic attempt_count
        return sum(1 for c, m, _ in self.failed_upserts if c == chat_username and m == message_id)

    def remove_failed_attempt(self, chat_username: str, message_id: int) -> None:
        self.failed_removes.append((chat_username, message_id))

    def save_pdf_atomically(self, content: bytes, filename: str) -> Path:
        self.saved_files.append((filename, content))
        path = self.base_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path


@pytest.fixture
def fake_client() -> FakeTelegramClient:
    return FakeTelegramClient()


@pytest.fixture
def fake_storage(tmp_path) -> FakeStorage:
    return FakeStorage(base_dir=tmp_path)
```

- [ ] **Step 2: Write failing tests**

`tests/test_collector.py`:

```python
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
    return SimpleNamespace(telegram_channel='sunstudy1004', initial_cutoff_days=30)


# === First-run behavior ===

@pytest.mark.asyncio
async def test_first_run_uses_iter_since_date(fake_client, fake_storage, cfg):
    fake_client.new_messages = [make_msg(101)]
    # max_seen=0 → first run path
    result = await run(fake_client, fake_storage, cfg)
    assert ('iter_since_date', 'sunstudy1004', 30) in fake_client.calls


@pytest.mark.asyncio
async def test_subsequent_run_uses_iter_after_id(fake_client, fake_storage, cfg):
    fake_storage._max_seen = 100
    fake_client.new_messages = [make_msg(101)]
    await run(fake_client, fake_storage, cfg)
    assert ('iter_after_id', 'sunstudy1004', 100) in fake_client.calls


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
    assert inserted['chat_username'] == 'sunstudy1004'
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
    assert chat == 'sunstudy1004'
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
    assert ('get_by_id', 'sunstudy1004', 100) in fake_client.calls
    # Insert happened for the retry
    assert any(m['message_id'] == 100 for m in fake_storage.inserted)
    # Failed_attempts row was removed
    assert ('sunstudy1004', 100) in fake_storage.failed_removes


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
    assert ('sunstudy1004', 100) not in fake_storage.failed_removes


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

    assert ('sunstudy1004', 100) in fake_storage.failed_removes
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

    assert ('sunstudy1004', 100) in fake_storage.failed_removes


# === RunResult shape ===

@pytest.mark.asyncio
async def test_run_returns_run_result_with_all_counters(fake_client, fake_storage, cfg):
    result = await run(fake_client, fake_storage, cfg)
    assert isinstance(result, RunResult)
    for attr in ('processed', 'skipped', 'failed', 'retried_success', 'retried_fail'):
        assert hasattr(result, attr)
        assert getattr(result, attr) == 0
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_collector.py -v
```

Expected: All ~10 tests FAIL with `ImportError` (no collector module yet).

- [ ] **Step 4: Implement `collector.py`**

```python
"""Two-phase orchestration: retry failures (A), then fetch new (B).

This module contains all the business rules described in spec §3.2 and §5.3.
It depends only on the abstract interfaces of TelegramClient and Storage,
not their concrete implementations — so it can be tested with simple fakes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from storage import compute_sha256, sanitize_filename
from telegram_client import _get_original_filename, has_pdf

log = logging.getLogger(__name__)

# Threshold above which we log a WARNING for a chronically-failing message
# (spec §5.3 — operations guidance, no automatic action in MVP)
ATTEMPT_WARN_THRESHOLD = 10


@dataclass(frozen=True)
class RunResult:
    """Counters returned by `run()`. Used by main.py to set the exit code."""
    processed: int = 0       # Stage B: PDF messages successfully downloaded + inserted
    skipped: int = 0         # Stage B: non-PDF messages
    failed: int = 0          # Stage B: PDF messages whose download/insert failed
    retried_success: int = 0  # Stage A: previously-failed messages now succeeded
    retried_fail: int = 0    # Stage A: still failing after retry


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
            # Message was deleted or its PDF attribute changed
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


async def _process_one_message(client: Any, storage: Any, channel: str, msg: Any) -> None:
    """Download a message's PDF and write metadata to storage. Idempotent enough that
    a re-run after partial failure converges (download to .partial → atomic rename →
    UNIQUE-constrained INSERT)."""
    original = _get_original_filename(msg) or 'unnamed.pdf'
    filename = f"{msg.id}_{sanitize_filename(original)}"

    pdf_bytes = await client.download_pdf_bytes(msg)
    target_path = storage.save_pdf_atomically(pdf_bytes, filename)

    file_hash = compute_sha256(target_path)
    file_size = target_path.stat().st_size

    storage.insert_report_metadata({
        'message_id': msg.id,
        'chat_username': channel,
        'sent_at': msg.date,
        'file_name': original,
        'file_path': filename,
        'file_size_bytes': file_size,
        'file_hash_sha256': file_hash,
        'caption': msg.message,
    })
```

- [ ] **Step 5: Configure pytest-asyncio**

Create `pytest.ini` at the project root:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_collector.py -v
```

Expected: All ~10 tests PASS.

- [ ] **Step 7: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests across all 5 test files PASS.

- [ ] **Step 8: Commit**

```bash
git add collector.py tests/test_collector.py tests/conftest.py pytest.ini
git commit -m "feat: add collector.run with two-phase retry + fetch logic"
```

---

### Task 10: main.py — CLI entry point

**Files:**
- Create: `main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

`tests/test_main.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main.py -v
```

Expected: All tests FAIL with `ImportError`.

- [ ] **Step 3: Implement `main.py`**

```python
"""CLI entry point.

Exit codes (spec §5.5):
  0 = complete success (no failures, possibly nothing to do)
  1 = total failure (config / auth / network / unhandled)
  2 = partial failure (some messages went to failed_attempts this run)
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import sys
from typing import Sequence

import collector
from collector import RunResult
from config import Config, load_config
from storage import build_storage
from telegram_client import TelegramClient

log = logging.getLogger('main')


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog='telegram_report',
        description='Collect PDF reports from a Telegram channel into Supabase + local FS.',
    )
    p.add_argument(
        '--cutoff-days',
        type=int,
        default=None,
        help='Override INITIAL_CUTOFF_DAYS for this run (only affects first run).',
    )
    p.add_argument(
        '--dry-run',
        action='store_true',
        help='Show which messages would be downloaded without saving anything.',
    )
    p.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Set log level to DEBUG.',
    )
    return p.parse_args(argv)


def setup_logging(verbose: bool, level_str: str = 'INFO') -> None:
    level = logging.DEBUG if verbose else getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)-8s %(name)-10s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stderr,
    )


def compute_exit_code(result: RunResult) -> int:
    """Map a RunResult to an exit code per spec §5.5."""
    if result.failed > 0 or result.retried_fail > 0:
        return 2
    return 0


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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config()
    except SystemExit as e:
        # load_config already prints; re-raise as exit code 1
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    setup_logging(args.verbose, level_str=config.log_level)

    # Apply CLI overrides on top of env config
    if args.cutoff_days is not None:
        config = dataclasses.replace(config, initial_cutoff_days=args.cutoff_days)

    try:
        return asyncio.run(_amain(args, config))
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        return 1
    except Exception:
        log.exception("Fatal error")
        return 1


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_main.py -v
```

Expected: All ~10 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: ALL tests across 6 test files PASS (config, storage_pure, storage_files, telegram_pdf, collector, main).

- [ ] **Step 6: Verify CLI help works**

```bash
python main.py --help
```

Expected: argparse-generated help text describing `--cutoff-days`, `--dry-run`, `-v`/`--verbose`.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: add main CLI entry point with exit codes 0/1/2"
```

---

### Task 11: README + end-to-end smoke test

**Files:**
- Create: `README.md`

This task documents setup and verifies the full pipeline against the real Telegram + Supabase. There's no automated test here — the verification is the user running the steps below.

- [ ] **Step 1: Create `README.md`**

```markdown
# Telegram Report Collector

PDF research-report collector for Korean securities. Listens to a single Telegram channel and downloads new PDF attachments to local disk + Supabase metadata.

See [design spec](docs/superpowers/specs/2026-05-05-telegram-report-collector-design.md) for full design rationale.

## Setup (one-time)

1. **Clone / download** this repo.

2. **Create venv and install dependencies:**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate            # Windows
   # source .venv/bin/activate       # Mac/Linux
   pip install -r requirements.txt
   ```

3. **Create Supabase tables.** Open your Supabase project → SQL Editor → paste the contents of `migrations/001_init.sql` → Run.

4. **Configure environment.** Copy the template and fill in your secrets:

   ```bash
   copy .env.example .env             # Windows
   # cp .env.example .env             # Mac/Linux
   ```

   Then edit `.env`:
   - `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`: from https://my.telegram.org
   - `TELEGRAM_CHANNEL`: channel username (default `sunstudy1004`)
   - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`: from Supabase dashboard → Settings → API → `service_role` key (⚠️ secret — never commit)

5. **First run** (will prompt for SMS verification once):

   ```bash
   python main.py
   ```

## Usage

| Command | Effect |
|---|---|
| `python main.py` | Normal run: collect new PDFs since last run |
| `python main.py --dry-run` | List what would be downloaded; write nothing |
| `python main.py --cutoff-days 7` | Override INITIAL_CUTOFF_DAYS for this run |
| `python main.py -v` | Verbose (DEBUG level) logging |

### Exit codes

- `0` Complete success
- `1` Total failure (config / auth / network)
- `2` Partial failure — some messages added to `failed_attempts` table; will be auto-retried next run

## Development

Run tests:

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Troubleshooting

- **"Missing required env var: X"** — Add the key to `.env`.
- **SMS code prompt every run** — The `sessions/samstudy.session` file is missing or got deleted. Telethon re-authenticates each time.
- **Persistent failures in `failed_attempts`** — Check the `error_message` and `attempt_count` columns. If `attempt_count > 10` for a row, the message is likely permanently broken; manually inspect or DELETE the row to stop retrying.

## Security

- `.env` and `*.session` files contain credentials and account access. They are in `.gitignore` — keep it that way.
- `SUPABASE_SERVICE_KEY` bypasses Row-Level Security. Treat it as a master password.
```

- [ ] **Step 2: End-to-end smoke test — first run (`--dry-run`)**

Make sure setup steps 2–4 above are done.

```bash
python main.py --dry-run -v
```

Expected:
- Logs show "Stage A: retrying 0 previously failed messages"
- Logs show "First run; using cutoff=30 days"
- "DRY RUN — would process the following: …" lists some messages
- Process exits with code 0
- **Nothing in Supabase, nothing in `./reports/`** (dry run did not write).

If it fails to connect to Telegram, you'll be prompted for a phone number + SMS code. Complete the prompt; the session file is then saved for future runs.

- [ ] **Step 3: End-to-end smoke test — full run with small cutoff**

Use a small cutoff to keep the smoke test quick (~1 day of history):

```bash
python main.py --cutoff-days 1 -v
```

Expected:
- Stage A says 0 to retry (first real run, table empty)
- Stage B downloads N PDFs (some number, possibly 0 if nothing posted in the last day — try `--cutoff-days 7` if so)
- Files appear in `./reports/` named `{message_id}_{original}.pdf`
- Rows appear in Supabase `reports` table (check via dashboard → Table Editor)
- Exit code is 0 (assuming no failures)

Verify in Supabase Table Editor:
- One row per downloaded PDF
- `file_path` is just the filename (no `reports/` prefix)
- `file_hash_sha256` is a 64-char lowercase hex string
- `sent_at` looks like a UTC timestamp matching the channel post time

- [ ] **Step 4: End-to-end smoke test — re-run is no-op**

Immediately after step 3:

```bash
python main.py -v
```

Expected:
- Stage A: 0 to retry
- Stage B: `last_seen_message_id=` (the max from step 3); iter_messages_after_id returns 0 new messages
- Result: processed=0, skipped=0, failed=0
- Exit code 0
- No new rows or files

This proves idempotency: nothing was re-downloaded.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup, usage, troubleshooting"
```

- [ ] **Step 6: Final summary**

After all 11 tasks:

```bash
pytest tests/ -v   # all tests pass
git log --oneline   # 11 commits with feat:/docs:/chore: prefixes
ls *.py             # main.py, config.py, telegram_client.py, storage.py, collector.py
```

The MVP is complete and the pipeline is verified end-to-end against the live channel + Supabase project.
