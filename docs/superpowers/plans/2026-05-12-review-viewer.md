# Review Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [Review Viewer Design](../specs/2026-05-12-review-viewer-design.md)대로, `tagging_status='review_needed'` 행을 한 화면씩 보고 verified / OOS / re-tag / skip 결정을 내릴 수 있는 로컬 Streamlit 웹 viewer를 구현.

**Architecture:** Streamlit single-page app. 좌측 PDF 페이지 이미지(PyMuPDF로 렌더), 우측 검수 패널(사유 → 분류 → 종목 매핑 → 섹터 → 메타 → 4-액션 버튼 → 진척/undo). DB 접근은 supabase-py REST (sync). 새 `langgraph_tagger/review_viewer/` 패키지에 격리된 `ReviewViewerConfig` + 6 DB 메서드 + 액션 payload 빌더 분리.

**Tech Stack:** Python 3.11+, Streamlit ~1.40 (신규), PyMuPDF (기존 재사용), supabase-py (기존 재사용), pytest, pytest-asyncio.

---

## File Structure

신규:

| 파일 | 책임 |
|---|---|
| `langgraph_tagger/review_viewer/__init__.py` | 빈 모듈 표시 |
| `langgraph_tagger/review_viewer/config.py` | `ReviewViewerConfig` dataclass + `load_review_viewer_config()` |
| `langgraph_tagger/review_viewer/pdf.py` | `resolve_path`, `render_pages`, `open_locally` |
| `langgraph_tagger/review_viewer/actions.py` | `SNAPSHOT_COLUMNS` allowlist, `capture_snapshot`, `build_verified_payload`, `build_oos_payload`, `build_pending_reset_payload` |
| `langgraph_tagger/review_viewer/db.py` | `ReviewDB` class — `count_review_queue`, `fetch_next_review`, `mark_verified`, `mark_oos`, `mark_pending`, `restore_snapshot` |
| `langgraph_tagger/review_viewer/app.py` | Streamlit entry — UI 렌더 + 액션 핸들러 + session_state |
| `langgraph_tagger/review_viewer/__main__.py` | `python -m langgraph_tagger.review_viewer` 진입점 (subprocess `streamlit run`) |
| `langgraph_tagger/review_viewer/tests/__init__.py` | 빈 파일 |
| `langgraph_tagger/review_viewer/tests/conftest.py` | sample PDF fixture, fake supabase client |
| `langgraph_tagger/review_viewer/tests/test_pdf.py` | pdf 모듈 단위 테스트 |
| `langgraph_tagger/review_viewer/tests/test_actions.py` | actions 모듈 단위 테스트 |
| `langgraph_tagger/review_viewer/tests/test_db.py` | db 모듈 단위 테스트 |
| `langgraph_tagger/review_viewer/tests/fixtures/sample_1page.pdf` | 최소 1페이지 PDF fixture (PyMuPDF로 생성) |
| `migrations/004_review_queue_index.sql` | review_needed 큐 partial index |

수정:

| 파일 | 변경 |
|---|---|
| `requirements.txt` | `streamlit>=1.40,<2.0` 줄 추가 |

---

## Task 1: Streamlit 의존성 추가

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1.1: requirements.txt에 streamlit 추가**

`requirements.txt`의 `pyyaml>=6.0` 줄 뒤에 추가:

```
streamlit>=1.40,<2.0
```

전체 파일 결과는 다음과 같아야 함:

```
telethon>=1.36,<2.0
supabase>=2.0,<3.0
python-dotenv>=1.0,<2.0
# langgraph_tagger (Phase 1: PDF metadata tagging via LangGraph + OpenAI)
langgraph>=1.0,<2.0
openai>=2.11
pymupdf>=1.24
pyyaml>=6.0
streamlit>=1.40,<2.0
asyncpg>=0.29
# Observability: LangSmith auto-traces LangGraph runs when LANGSMITH_TRACING=true.
# wrap_openai (langsmith.wrappers) nests OpenAI calls under graph spans.
langsmith>=0.4,<1.0
```

- [ ] **Step 1.2: 메인 레포 venv에 streamlit 설치**

```powershell
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pip install -r 'C:\Users\imyon\Projects\telegram_report\.claude\worktrees\sweet-dewdney-dc0ae1\requirements.txt'
```

Expected: streamlit 설치 메시지. 다른 패키지는 이미 만족된 상태.

- [ ] **Step 1.3: streamlit import 동작 확인**

```powershell
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -c "import streamlit; print(streamlit.__version__)"
```

Expected: `1.40.x` 또는 그 이상의 버전 문자열.

- [ ] **Step 1.4: Commit**

```bash
git add requirements.txt
git commit -m "$(cat <<'EOF'
chore(deps): add streamlit for review viewer

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Migration 004 — review_needed partial index

**Files:**
- Create: `migrations/004_review_queue_index.sql`

- [ ] **Step 2.1: SQL 파일 작성**

`migrations/004_review_queue_index.sql`:

```sql
-- migrations/004_review_queue_index.sql
--
-- Partial index for the review viewer's primary access pattern:
--   SELECT ... FROM reports
--    WHERE tagging_status='review_needed'
--    ORDER BY tagged_at ASC
--    LIMIT 1
--
-- The existing (tagging_status, downloaded_at) index from 002 is tuned for
-- pending fetch by the tagger; this one covers the manual review FIFO.

BEGIN;

CREATE INDEX IF NOT EXISTS ix_reports_review_needed_tagged
  ON reports(tagged_at)
  WHERE tagging_status='review_needed';

COMMIT;
```

- [ ] **Step 2.2: Supabase에 migration 적용 (사용자 수동)**

운영자 액션:
1. Supabase 대시보드 → SQL Editor 열기
2. 위 SQL 내용 그대로 붙여넣기
3. Run 클릭
4. 성공 시 "Success. No rows returned" 메시지

검증 query:

```sql
SELECT indexname, indexdef
  FROM pg_indexes
 WHERE indexname = 'ix_reports_review_needed_tagged';
```

Expected: 1 row with indexdef containing `WHERE (tagging_status = 'review_needed'::text)`.

- [ ] **Step 2.3: Commit migration 파일**

```bash
git add migrations/004_review_queue_index.sql
git commit -m "$(cat <<'EOF'
feat(migration): 004 — partial index on review_needed queue

Speeds up the review viewer's FIFO fetch (ORDER BY tagged_at ASC LIMIT 1)
as the queue grows. Apply manually via Supabase SQL Editor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `ReviewViewerConfig`

**Files:**
- Create: `langgraph_tagger/review_viewer/__init__.py`
- Create: `langgraph_tagger/review_viewer/config.py`
- Create: `langgraph_tagger/review_viewer/tests/__init__.py`
- Create: `langgraph_tagger/review_viewer/tests/test_config.py`

- [ ] **Step 3.1: 빈 패키지 파일 생성**

`langgraph_tagger/review_viewer/__init__.py`:

```python
"""Review viewer: Streamlit web app for manually verifying review_needed rows."""
```

`langgraph_tagger/review_viewer/tests/__init__.py`:

```python
```

(빈 파일.)

- [ ] **Step 3.2: 실패 테스트 작성**

`langgraph_tagger/review_viewer/tests/test_config.py`:

```python
from pathlib import Path

import pytest

from langgraph_tagger.review_viewer.config import ReviewViewerConfig, load_review_viewer_config


def test_load_happy_path(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'eyJtest')
    monkeypatch.setenv('STORAGE_BASE_DIR', '/tmp/reports')

    cfg = load_review_viewer_config()

    assert isinstance(cfg, ReviewViewerConfig)
    assert cfg.supabase_url == 'https://test.supabase.co'
    assert cfg.supabase_service_key == 'eyJtest'
    assert cfg.storage_base_dir == Path('/tmp/reports')


def test_load_storage_default(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.delenv('STORAGE_BASE_DIR', raising=False)

    cfg = load_review_viewer_config()
    assert cfg.storage_base_dir == Path('./reports')


def test_missing_supabase_url_exits(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')

    with pytest.raises(SystemExit) as exc_info:
        load_review_viewer_config()
    assert 'SUPABASE_URL' in str(exc_info.value)


def test_missing_supabase_key_exits(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.delenv('SUPABASE_SERVICE_KEY', raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_review_viewer_config()
    assert 'SUPABASE_SERVICE_KEY' in str(exc_info.value)


def test_does_not_require_openai_or_telegram_envs(monkeypatch):
    """Viewer must run without OPENAI_API_KEY / TELEGRAM_* — those belong to tagger / collector."""
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    for k in ('OPENAI_API_KEY', 'TELEGRAM_API_ID', 'TELEGRAM_API_HASH',
              'TELEGRAM_CHANNEL', 'SUPABASE_DB_URL'):
        monkeypatch.delenv(k, raising=False)

    cfg = load_review_viewer_config()
    assert cfg.supabase_url == 'u'
```

- [ ] **Step 3.3: 테스트 실패 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/tests/test_config.py -v
```

Expected: ImportError 또는 ModuleNotFoundError (`config.py` 없음).

- [ ] **Step 3.4: `config.py` 구현**

`langgraph_tagger/review_viewer/config.py`:

```python
"""Standalone config for the review viewer.

Intentionally separate from langgraph_tagger.config so the viewer can run
without OPENAI_API_KEY, SUPABASE_DB_URL, or TELEGRAM_* envs — those belong
to the tagger and collector.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ReviewViewerConfig:
    supabase_url: str
    supabase_service_key: str
    storage_base_dir: Path


def load_review_viewer_config() -> ReviewViewerConfig:
    load_dotenv()

    def required(key: str) -> str:
        v = os.getenv(key)
        if not v:
            raise SystemExit(f"Missing required env var: {key}")
        return v

    return ReviewViewerConfig(
        supabase_url=required('SUPABASE_URL'),
        supabase_service_key=required('SUPABASE_SERVICE_KEY'),
        storage_base_dir=Path(os.getenv('STORAGE_BASE_DIR', './reports')),
    )
```

- [ ] **Step 3.5: 테스트 통과 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/tests/test_config.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 3.6: Commit**

```bash
git add langgraph_tagger/review_viewer/__init__.py langgraph_tagger/review_viewer/config.py langgraph_tagger/review_viewer/tests/__init__.py langgraph_tagger/review_viewer/tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(review_viewer): ReviewViewerConfig — standalone env loader

Decouples viewer from tagger/collector envs (OPENAI_API_KEY, TELEGRAM_*,
SUPABASE_DB_URL) so it can run in isolation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `pdf` 모듈 — resolve_path, render_pages, open_locally

**Files:**
- Create: `langgraph_tagger/review_viewer/pdf.py`
- Create: `langgraph_tagger/review_viewer/tests/conftest.py`
- Create: `langgraph_tagger/review_viewer/tests/fixtures/sample_1page.pdf` (PyMuPDF로 생성하는 fixture 스크립트로 만들어둠)
- Create: `langgraph_tagger/review_viewer/tests/test_pdf.py`

- [ ] **Step 4.1: conftest.py 작성**

`langgraph_tagger/review_viewer/tests/conftest.py`:

```python
"""Shared fixtures for review viewer tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_pdf_path() -> Path:
    """Path to a tiny 1-page PDF used by pdf.py tests.

    Generated once and committed to fixtures/. If missing, run
    tools/generate_fixture_pdf.py (see Step 4.2).
    """
    p = Path(__file__).parent / 'fixtures' / 'sample_1page.pdf'
    if not p.exists():
        # Auto-generate so first-time runners don't get stuck
        import pymupdf
        p.parent.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 80), "Sample fixture PDF", fontsize=20)
        page.insert_text((50, 120), "Used by review_viewer tests.", fontsize=12)
        doc.save(str(p))
        doc.close()
    return p
```

- [ ] **Step 4.2: 실패 테스트 작성**

`langgraph_tagger/review_viewer/tests/test_pdf.py`:

```python
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from langgraph_tagger.review_viewer.pdf import (
    resolve_path,
    render_pages,
    open_locally,
)


# === resolve_path ===

def test_resolve_path_joins_relative(tmp_path):
    storage = tmp_path
    (storage / 'foo.pdf').write_bytes(b'%PDF-1.4\n')
    result = resolve_path(storage, 'foo.pdf')
    assert result == storage / 'foo.pdf'
    assert result.is_file()


def test_resolve_path_absolute_in_file_path(tmp_path):
    """file_path can be absolute (legacy rows); resolve_path should respect it."""
    abs_path = tmp_path / 'abs.pdf'
    abs_path.write_bytes(b'%PDF-1.4\n')
    result = resolve_path(Path('/other/storage'), str(abs_path))
    assert result == abs_path


def test_resolve_path_missing_returns_path_anyway(tmp_path):
    """Caller (UI) decides how to render missing-file placeholder."""
    result = resolve_path(tmp_path, 'does_not_exist.pdf')
    assert result == tmp_path / 'does_not_exist.pdf'
    assert not result.exists()


# === render_pages ===

def test_render_pages_returns_n_png_bytes(sample_pdf_path):
    pages = render_pages(sample_pdf_path, n=1)
    assert len(pages) == 1
    assert pages[0][:8] == b'\x89PNG\r\n\x1a\n'   # PNG magic header


def test_render_pages_caps_at_doc_page_count(sample_pdf_path):
    """Asking for more pages than the PDF has should not raise."""
    pages = render_pages(sample_pdf_path, n=10)
    assert 1 <= len(pages) <= 10


def test_render_pages_dpi_changes_size(sample_pdf_path):
    low = render_pages(sample_pdf_path, n=1, dpi=72)
    high = render_pages(sample_pdf_path, n=1, dpi=200)
    assert len(high[0]) > len(low[0]), "Higher DPI should yield a larger PNG"


def test_render_pages_missing_file_raises(tmp_path):
    bad = tmp_path / 'nope.pdf'
    with pytest.raises(FileNotFoundError):
        render_pages(bad, n=1)


# === open_locally ===

@patch('langgraph_tagger.review_viewer.pdf.sys')
@patch('langgraph_tagger.review_viewer.pdf.os')
def test_open_locally_windows_uses_startfile(mock_os, mock_sys, tmp_path):
    pdf = tmp_path / 'a.pdf'
    pdf.write_bytes(b'%PDF-1.4\n')
    mock_sys.platform = 'win32'
    open_locally(pdf)
    mock_os.startfile.assert_called_once_with(str(pdf))


@patch('langgraph_tagger.review_viewer.pdf.subprocess')
@patch('langgraph_tagger.review_viewer.pdf.sys')
def test_open_locally_macos_uses_open(mock_sys, mock_subprocess, tmp_path):
    pdf = tmp_path / 'a.pdf'
    pdf.write_bytes(b'%PDF-1.4\n')
    mock_sys.platform = 'darwin'
    open_locally(pdf)
    mock_subprocess.run.assert_called_once_with(['open', str(pdf)], check=False)


@patch('langgraph_tagger.review_viewer.pdf.subprocess')
@patch('langgraph_tagger.review_viewer.pdf.sys')
def test_open_locally_linux_uses_xdg_open(mock_sys, mock_subprocess, tmp_path):
    pdf = tmp_path / 'a.pdf'
    pdf.write_bytes(b'%PDF-1.4\n')
    mock_sys.platform = 'linux'
    open_locally(pdf)
    mock_subprocess.run.assert_called_once_with(['xdg-open', str(pdf)], check=False)
```

- [ ] **Step 4.3: 테스트 실패 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/tests/test_pdf.py -v
```

Expected: ImportError (pdf.py not present).

- [ ] **Step 4.4: `pdf.py` 구현**

`langgraph_tagger/review_viewer/pdf.py`:

```python
"""PDF I/O for the review viewer.

- resolve_path: turn (storage_base_dir, file_path) into an absolute Path
- render_pages: render the first N pages as PNG bytes via PyMuPDF
- open_locally: hand the file to the OS default viewer (Windows/macOS/Linux)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pymupdf


def resolve_path(storage_base_dir: Path, file_path: str) -> Path:
    """Combine storage base + relative file_path. Absolute file_path wins.

    Does NOT check existence — caller decides how to render a missing-file
    placeholder.
    """
    p = Path(file_path)
    if p.is_absolute():
        return p
    return Path(storage_base_dir) / p


def render_pages(pdf_path: Path, n: int = 3, dpi: int = 120) -> list[bytes]:
    """Render the first n pages of pdf_path to PNG bytes via PyMuPDF.

    Caps at the actual page count when the document has fewer pages.
    Raises FileNotFoundError if pdf_path does not exist.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))
    doc = pymupdf.open(str(pdf_path))
    try:
        out: list[bytes] = []
        zoom = dpi / 72  # PyMuPDF default is 72 DPI
        matrix = pymupdf.Matrix(zoom, zoom)
        for i in range(min(n, doc.page_count)):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out.append(pix.tobytes('png'))
        return out
    finally:
        doc.close()


def open_locally(pdf_path: Path) -> None:
    """Open pdf_path in the OS default PDF viewer.

    Server-side dispatch avoids the http→file:// browser block.
    """
    path_str = str(pdf_path)
    if sys.platform == 'win32':
        os.startfile(path_str)   # type: ignore[attr-defined]
    elif sys.platform == 'darwin':
        subprocess.run(['open', path_str], check=False)
    else:
        subprocess.run(['xdg-open', path_str], check=False)
```

- [ ] **Step 4.5: 테스트 통과 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/tests/test_pdf.py -v
```

Expected: 9 tests PASS. fixture PDF가 자동 생성됨 (`fixtures/sample_1page.pdf`).

- [ ] **Step 4.6: Commit**

```bash
git add langgraph_tagger/review_viewer/pdf.py langgraph_tagger/review_viewer/tests/conftest.py langgraph_tagger/review_viewer/tests/test_pdf.py langgraph_tagger/review_viewer/tests/fixtures/sample_1page.pdf
git commit -m "$(cat <<'EOF'
feat(review_viewer): pdf module — resolve_path, render_pages, open_locally

PyMuPDF renders first N pages to PNG bytes (avoids http→file:// block).
open_locally dispatches to OS default viewer per platform.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `actions` 모듈 — snapshot + payload builders

**Files:**
- Create: `langgraph_tagger/review_viewer/actions.py`
- Create: `langgraph_tagger/review_viewer/tests/test_actions.py`

- [ ] **Step 5.1: 실패 테스트 작성**

`langgraph_tagger/review_viewer/tests/test_actions.py`:

```python
from langgraph_tagger.review_viewer.actions import (
    SNAPSHOT_COLUMNS,
    capture_snapshot,
    build_verified_payload,
    build_oos_payload,
    build_pending_reset_payload,
)


def make_row(**overrides):
    """Factory for a representative review_needed row dict (supabase-py response shape)."""
    base = {
        # original meta — must NEVER appear in snapshot or payload
        'id': 1234,
        'message_id': 124784,
        'chat_username': 'sunstudy1004',
        'file_path': '124784_some.pdf',
        'file_name': 'some.pdf',
        'file_size_bytes': 12345,
        'file_hash_sha256': 'a' * 64,
        'caption': 'Sample',
        'downloaded_at': '2026-05-07T08:04:14+00:00',
        'sent_at': '2026-05-07T08:04:14+00:00',
        # analysis body
        'published_at': '2026-05-07',
        'report_type': '단일종목',
        'publisher': '삼성증권',
        'publisher_type': 'broker',
        'analysts': ['홍길동'],
        'title': '삼성전자 Q1',
        'stock_codes': ['005930'],
        'company_names': ['삼성전자'],
        'stock_codes_raw': ['005935'],
        'company_names_raw': ['삼성전자우'],
        'sectors_major': ['반도체'],
        'sectors_minor': ['메모리'],
        'products': ['DRAM'],
        'out_of_scope_reason': None,
        # tagging meta
        'tagging_status': 'review_needed',
        'tagging_confidence': 'medium',
        'tagging_notes': 'krx_unmatched_in_scope',
        'tagged_at': '2026-05-07T08:30:00+00:00',
        'tagger_version': 'langgraph-tagger@2.0',
        'taxonomy_version': 'KRX@2026-05-08',
        'tagging_locked_at': None,
        'tagging_worker_id': None,
    }
    base.update(overrides)
    return base


# === SNAPSHOT_COLUMNS ===

def test_snapshot_columns_excludes_original_meta():
    """Original / message / file meta must never be in the allowlist —
    undo restores tagging state only, not the row's identity."""
    forbidden = {
        'id', 'message_id', 'chat_username', 'file_path', 'file_name',
        'file_size_bytes', 'file_hash_sha256', 'caption',
        'downloaded_at', 'sent_at',
    }
    assert forbidden.isdisjoint(set(SNAPSHOT_COLUMNS))


def test_snapshot_columns_covers_all_action_writes():
    """All columns that any action writes must be in the allowlist —
    otherwise undo can't restore them."""
    expected = {
        # analysis
        'published_at', 'report_type', 'publisher', 'publisher_type',
        'analysts', 'title', 'stock_codes', 'company_names',
        'stock_codes_raw', 'company_names_raw',
        'sectors_major', 'sectors_minor', 'products',
        'out_of_scope_reason',
        # tagging meta
        'tagging_status', 'tagging_confidence', 'tagging_notes',
        'tagged_at', 'tagger_version', 'taxonomy_version',
        'tagging_locked_at', 'tagging_worker_id',
    }
    assert set(SNAPSHOT_COLUMNS) == expected


# === capture_snapshot ===

def test_capture_snapshot_picks_only_allowlist():
    row = make_row()
    snap = capture_snapshot(row)
    assert set(snap.keys()) == set(SNAPSHOT_COLUMNS)
    assert snap['tagging_status'] == 'review_needed'
    assert snap['tagging_notes'] == 'krx_unmatched_in_scope'
    # original meta must not leak
    assert 'message_id' not in snap
    assert 'file_path' not in snap


# === build_verified_payload ===

def test_build_verified_payload_only_changes_status():
    row = make_row()
    payload = build_verified_payload(row)
    assert payload == {'tagging_status': 'verified'}


# === build_oos_payload ===

def test_build_oos_payload_matches_write_node_semantics():
    """OOS payload must mirror langgraph_tagger/nodes/write.py OOS branch:
    - tagging_status='verified' (manual review concluded)
    - out_of_scope_reason=<reason>
    - analysis-body fields cleared (stock_codes/names/sectors/products, published_at)
    - LLM classification preserved (report_type, publisher, title, analysts, *_raw)
    """
    row = make_row()
    payload = build_oos_payload(row, reason='foreign')

    assert payload['tagging_status'] == 'verified'
    assert payload['out_of_scope_reason'] == 'foreign'
    # cleared:
    assert payload['published_at'] is None
    assert payload['stock_codes'] == []
    assert payload['company_names'] == []
    assert payload['sectors_major'] == []
    assert payload['sectors_minor'] == []
    assert payload['products'] == []
    # preserved (from row):
    assert payload['report_type'] == '단일종목'
    assert payload['publisher'] == '삼성증권'
    assert payload['publisher_type'] == 'broker'
    assert payload['title'] == '삼성전자 Q1'
    assert payload['analysts'] == ['홍길동']
    assert payload['stock_codes_raw'] == ['005935']
    assert payload['company_names_raw'] == ['삼성전자우']


def test_build_oos_payload_rejects_unknown_reason():
    import pytest
    row = make_row()
    with pytest.raises(ValueError):
        build_oos_payload(row, reason='not_a_real_reason')


def test_build_oos_payload_accepts_all_v2_reasons():
    row = make_row()
    for reason in ('foreign', 'fund', 'digital', 'private', 'ir_self'):
        p = build_oos_payload(row, reason=reason)
        assert p['out_of_scope_reason'] == reason


# === build_pending_reset_payload ===

def test_build_pending_reset_clears_analysis_and_meta():
    """Re-tag must mirror migration 003's reset: every analysis column +
    every tagging-meta column gets emptied/nulled."""
    payload = build_pending_reset_payload()
    # status / meta
    assert payload['tagging_status'] == 'pending'
    assert payload['tagging_locked_at'] is None
    assert payload['tagging_worker_id'] is None
    assert payload['tagged_at'] is None
    assert payload['tagging_notes'] is None
    assert payload['tagging_confidence'] is None
    assert payload['tagger_version'] is None
    assert payload['taxonomy_version'] is None
    # analysis
    assert payload['published_at'] is None
    assert payload['report_type'] is None
    assert payload['publisher'] is None
    assert payload['publisher_type'] is None
    assert payload['analysts'] == []
    assert payload['title'] is None
    assert payload['stock_codes'] == []
    assert payload['company_names'] == []
    assert payload['stock_codes_raw'] == []
    assert payload['company_names_raw'] == []
    assert payload['sectors_major'] == []
    assert payload['sectors_minor'] == []
    assert payload['products'] == []
    assert payload['out_of_scope_reason'] is None


def test_build_pending_reset_does_not_touch_original_meta():
    payload = build_pending_reset_payload()
    forbidden = {
        'id', 'message_id', 'chat_username', 'file_path', 'file_name',
        'file_size_bytes', 'file_hash_sha256', 'caption',
        'downloaded_at', 'sent_at',
    }
    assert forbidden.isdisjoint(set(payload.keys()))


# === snapshot round-trip ===

def test_snapshot_restore_round_trip():
    """The snapshot returned by capture_snapshot must be applicable as an
    UPDATE payload that restores the row state."""
    row = make_row()
    snap = capture_snapshot(row)
    # Sanity: applying snap as payload would set every allowlist field back
    # to its original. Field-by-field equality.
    for col in SNAPSHOT_COLUMNS:
        assert snap[col] == row[col], f"round-trip failed for {col}"
```

- [ ] **Step 5.2: 테스트 실패 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/tests/test_actions.py -v
```

Expected: ImportError.

- [ ] **Step 5.3: `actions.py` 구현**

`langgraph_tagger/review_viewer/actions.py`:

```python
"""Payload builders for the 4 review actions, plus snapshot allowlist.

Semantics mirror langgraph_tagger/nodes/write.py and migrations/003_v2_redesign.sql
so manual review decisions land the row in exactly the same shape the tagger
would have produced.
"""
from __future__ import annotations

from typing import Any

V2_OOS_REASONS = ('foreign', 'fund', 'digital', 'private', 'ir_self')

# Columns the viewer may write. Used both by capture_snapshot (for undo) and
# restore_snapshot in db.py. Original / message / file meta NEVER appear here.
SNAPSHOT_COLUMNS: tuple[str, ...] = (
    # analysis body
    'published_at',
    'report_type',
    'publisher',
    'publisher_type',
    'analysts',
    'title',
    'stock_codes',
    'company_names',
    'stock_codes_raw',
    'company_names_raw',
    'sectors_major',
    'sectors_minor',
    'products',
    'out_of_scope_reason',
    # tagging meta
    'tagging_status',
    'tagging_confidence',
    'tagging_notes',
    'tagged_at',
    'tagger_version',
    'taxonomy_version',
    'tagging_locked_at',
    'tagging_worker_id',
)


def capture_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Pick the allowlist columns out of a fetched row for later undo."""
    return {col: row.get(col) for col in SNAPSHOT_COLUMNS}


def build_verified_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Manual verified: keep LLM extraction, only flip status."""
    return {'tagging_status': 'verified'}


def build_oos_payload(row: dict[str, Any], reason: str) -> dict[str, Any]:
    """Manual OOS: mirror write.py's OOS branch — clear analysis body,
    preserve LLM classification + raw audit, set reason + verified.
    """
    if reason not in V2_OOS_REASONS:
        raise ValueError(
            f"reason must be one of {V2_OOS_REASONS}, got: {reason!r}"
        )
    return {
        'tagging_status': 'verified',
        'out_of_scope_reason': reason,
        'published_at': None,
        # analysis body cleared
        'stock_codes': [],
        'company_names': [],
        'sectors_major': [],
        'sectors_minor': [],
        'products': [],
        # LLM classification + raw audit preserved
        'report_type': row.get('report_type'),
        'publisher': row.get('publisher'),
        'publisher_type': row.get('publisher_type'),
        'analysts': list(row.get('analysts') or []),
        'title': row.get('title'),
        'stock_codes_raw': list(row.get('stock_codes_raw') or []),
        'company_names_raw': list(row.get('company_names_raw') or []),
    }


def build_pending_reset_payload() -> dict[str, Any]:
    """Re-tag: mirror migration 003 reset — clear every analysis + tagging-meta
    column so the next tagger batch produces a fresh result.
    """
    return {
        # tagging meta
        'tagging_status': 'pending',
        'tagging_locked_at': None,
        'tagging_worker_id': None,
        'tagged_at': None,
        'tagging_notes': None,
        'tagging_confidence': None,
        'tagger_version': None,
        'taxonomy_version': None,
        # analysis body
        'published_at': None,
        'report_type': None,
        'publisher': None,
        'publisher_type': None,
        'analysts': [],
        'title': None,
        'stock_codes': [],
        'company_names': [],
        'stock_codes_raw': [],
        'company_names_raw': [],
        'sectors_major': [],
        'sectors_minor': [],
        'products': [],
        'out_of_scope_reason': None,
    }
```

- [ ] **Step 5.4: 테스트 통과 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/tests/test_actions.py -v
```

Expected: 11 tests PASS.

- [ ] **Step 5.5: Commit**

```bash
git add langgraph_tagger/review_viewer/actions.py langgraph_tagger/review_viewer/tests/test_actions.py
git commit -m "$(cat <<'EOF'
feat(review_viewer): actions module — snapshot allowlist + payload builders

Payload semantics mirror write.py OOS branch + migration 003 reset.
SNAPSHOT_COLUMNS is the explicit 22-column allowlist for undo —
original meta (message_id/file_path/sent_at/...) is never restored.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `db` 모듈 — supabase-py 쿼리 래퍼

**Files:**
- Create: `langgraph_tagger/review_viewer/db.py`
- Modify: `langgraph_tagger/review_viewer/tests/conftest.py`
- Create: `langgraph_tagger/review_viewer/tests/test_db.py`

- [ ] **Step 6.1: conftest.py에 fake supabase fixture 추가**

`langgraph_tagger/review_viewer/tests/conftest.py` 끝에 추가:

```python


class FakeQueryBuilder:
    """Tracks calls and lets a test assert on the chain."""

    def __init__(self, sink: list[dict]):
        self._sink = sink
        self._spec: dict = {'eqs': []}

    def select(self, cols, count=None):
        self._spec['select'] = cols
        if count is not None:
            self._spec['count_mode'] = count
        return self

    def eq(self, col, val):
        self._spec['eqs'].append((col, val))
        return self

    def order(self, col, desc=False):
        self._spec['order'] = (col, desc)
        return self

    def limit(self, n):
        self._spec['limit'] = n
        return self

    def not_(self):
        self._spec.setdefault('not_', []).append(True)
        return self

    def in_(self, col, values):
        self._spec.setdefault('not_in', []).append((col, list(values)))
        return self

    def update(self, payload):
        self._spec['update'] = dict(payload)
        return self

    def execute(self):
        self._sink.append(self._spec)
        return type('R', (), {
            'data': self._spec.get('_canned_data', []),
            'count': self._spec.get('_canned_count', None),
        })()


class FakeSupabase:
    def __init__(self):
        self.calls: list[dict] = []
        self._canned: dict[str, list | int] = {}

    def table(self, name):
        qb = FakeQueryBuilder(self.calls)
        qb._spec['table'] = name
        return qb

    def set_canned(self, key, value):
        self._canned[key] = value


@pytest.fixture
def fake_sb():
    return FakeSupabase()
```

- [ ] **Step 6.2: 실패 테스트 작성**

`langgraph_tagger/review_viewer/tests/test_db.py`:

```python
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
```

- [ ] **Step 6.3: 테스트 실패 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/tests/test_db.py -v
```

Expected: ImportError.

- [ ] **Step 6.4: `db.py` 구현**

`langgraph_tagger/review_viewer/db.py`:

```python
"""supabase-py REST wrapper for review viewer queries.

Sync (Streamlit-friendly), unlike the async asyncpg adapter in
langgraph_tagger/supabase_io.py used by the tagger pipeline.
"""
from __future__ import annotations

from typing import Any, Iterable

from langgraph_tagger.review_viewer.actions import (
    SNAPSHOT_COLUMNS,
    build_pending_reset_payload,
)


class ReviewDB:
    """Thin facade over a supabase-py client.

    The client argument is intentionally typed `Any` so tests can pass
    MagicMock without dragging supabase-py imports into the test path.
    """

    def __init__(self, client: Any) -> None:
        self._sb = client

    def count_review_queue(self) -> int:
        result = (
            self._sb.table('reports')
            .select('id', count='exact')
            .eq('tagging_status', 'review_needed')
            .execute()
        )
        return int(result.count or 0)

    def fetch_next_review(self, skipped_ids: Iterable[int]) -> dict[str, Any] | None:
        skipped_list = list(skipped_ids)
        q = (
            self._sb.table('reports')
            .select('*')
            .eq('tagging_status', 'review_needed')
        )
        if skipped_list:
            q = q.not_().in_('id', skipped_list)
        q = q.order('tagged_at', desc=False).limit(1)
        result = q.execute()
        data = result.data or []
        return data[0] if data else None

    def mark_verified(self, row_id: int, payload: dict[str, Any]) -> None:
        self._sb.table('reports').update(payload).eq('id', row_id).execute()

    def mark_oos(self, row_id: int, payload: dict[str, Any]) -> None:
        self._sb.table('reports').update(payload).eq('id', row_id).execute()

    def mark_pending(self, row_id: int) -> None:
        payload = build_pending_reset_payload()
        self._sb.table('reports').update(payload).eq('id', row_id).execute()

    def restore_snapshot(self, row_id: int, snapshot: dict[str, Any]) -> None:
        """Apply only allowlisted columns from snapshot, ignoring any leakage."""
        filtered = {col: snapshot[col] for col in SNAPSHOT_COLUMNS if col in snapshot}
        self._sb.table('reports').update(filtered).eq('id', row_id).execute()
```

- [ ] **Step 6.5: 테스트 통과 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/tests/test_db.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 6.6: 전체 review_viewer 테스트 회귀**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/review_viewer/ -v
```

Expected: 모든 테스트 (config 5 + pdf 9 + actions 11 + db 8 = 33개) PASS.

- [ ] **Step 6.7: Commit**

```bash
git add langgraph_tagger/review_viewer/db.py langgraph_tagger/review_viewer/tests/conftest.py langgraph_tagger/review_viewer/tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(review_viewer): db module — supabase-py REST wrapper for 6 queries

count/fetch_next/mark_verified/mark_oos/mark_pending/restore_snapshot.
Sync API to match Streamlit's single-thread rerun model.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `app.py` — Streamlit UI

**Files:**
- Create: `langgraph_tagger/review_viewer/app.py`

UI 코드는 단위 테스트 어렵고 (Streamlit runtime 의존) 운영 1인용이라 manual smoke로 검증. 다만 코드 구조는 모듈화해서 logic은 위 task들에서 이미 테스트 완료.

- [ ] **Step 7.1: `app.py` 작성**

`langgraph_tagger/review_viewer/app.py`:

```python
"""Streamlit entry for the review viewer.

Run via: python -m langgraph_tagger.review_viewer
(which subprocess-launches `streamlit run` on this file)
"""
from __future__ import annotations

import streamlit as st
from supabase import create_client

from langgraph_tagger.review_viewer.actions import (
    V2_OOS_REASONS,
    capture_snapshot,
    build_verified_payload,
    build_oos_payload,
)
from langgraph_tagger.review_viewer.config import load_review_viewer_config
from langgraph_tagger.review_viewer.db import ReviewDB
from langgraph_tagger.review_viewer.pdf import (
    resolve_path,
    render_pages,
    open_locally,
)


# ── Bootstrap ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Review Viewer", layout="wide")


@st.cache_resource
def _bootstrap():
    cfg = load_review_viewer_config()
    client = create_client(cfg.supabase_url, cfg.supabase_service_key)
    return cfg, ReviewDB(client)


cfg, db = _bootstrap()


# ── Session state init ───────────────────────────────────────────────────────

if 'skipped_ids' not in st.session_state:
    st.session_state.skipped_ids = set()
if 'last_snapshot' not in st.session_state:
    st.session_state.last_snapshot = None  # (row_id, snapshot_dict)
if 'total_at_start' not in st.session_state:
    st.session_state.total_at_start = db.count_review_queue()
if 'counts' not in st.session_state:
    st.session_state.counts = {'verified': 0, 'oos': 0, 'retag': 0, 'skip': 0}


# ── Fetch next row ───────────────────────────────────────────────────────────

row = db.fetch_next_review(st.session_state.skipped_ids)

if row is None:
    st.success("🎉 Review queue empty.")
    c = st.session_state.counts
    st.write(
        f"Session totals — verified: {c['verified']}, oos: {c['oos']}, "
        f"re-tag: {c['retag']}, skip: {c['skip']}"
    )
    st.stop()


# ── Layout ───────────────────────────────────────────────────────────────────

left, right = st.columns([2, 1])


# ── Left: PDF page images ────────────────────────────────────────────────────

with left:
    pdf_path = resolve_path(cfg.storage_base_dir, row['file_path'])
    if not pdf_path.exists():
        st.warning(f"PDF not found at {pdf_path}. Decide using metadata + LLM result only.")
    else:
        try:
            pages = render_pages(pdf_path, n=3, dpi=120)
            for png in pages:
                st.image(png, use_container_width=True)
        except Exception as e:
            st.error(f"PyMuPDF render failed: {e}")

        if st.button("📄 Open in OS viewer"):
            open_locally(pdf_path)


# ── Right: review panel ──────────────────────────────────────────────────────

def _highlight_reason(notes: str | None) -> None:
    if not notes:
        return
    color = '#fff3cd'
    border = '#f0ad4e'
    if 'first_page_unreadable' in (notes or ''):
        color, border = '#fde2e2', '#d9534f'
    st.markdown(
        f"<div style='background:{color};border-left:4px solid {border};"
        f"padding:8px 10px;font-size:13px'>"
        f"<strong>왜 review 큐?</strong><br/>"
        f"<code>{notes}</code></div>",
        unsafe_allow_html=True,
    )


with right:
    # Progress header
    c = st.session_state.counts
    n = c['verified'] + c['oos'] + c['retag'] + c['skip']
    N = st.session_state.total_at_start
    st.markdown(f"**{n} / {N}** &nbsp; ✓{c['verified']} ✗{c['oos']} ↺{c['retag']} ↻{c['skip']}")
    st.divider()

    _highlight_reason(row.get('tagging_notes'))

    st.markdown("**분류**")
    st.text(f"report_type:     {row.get('report_type')}")
    st.text(f"publisher:       {row.get('publisher')}")
    st.text(f"publisher_type:  {row.get('publisher_type')}")
    st.text(f"confidence:      {row.get('tagging_confidence')}")

    st.markdown("**종목 매핑**")
    st.text(f"codes (LLM raw):  {row.get('stock_codes_raw')}")
    st.text(f"codes (KRX):      {row.get('stock_codes')}")
    st.text(f"names (LLM raw):  {row.get('company_names_raw')}")
    st.text(f"names (KRX):      {row.get('company_names')}")

    st.markdown("**섹터 / 제품**")
    st.text(f"sectors_major: {row.get('sectors_major')}")
    st.text(f"sectors_minor: {row.get('sectors_minor')}")
    st.text(f"products:      {row.get('products')}")

    with st.expander("메시지 메타"):
        st.text(f"file_name: {row.get('file_name')}")
        st.text(f"sent_at:   {row.get('sent_at')}")
        st.text(f"caption:   {row.get('caption')}")

    st.divider()

    # Action buttons
    snapshot = capture_snapshot(row)
    rid = int(row['id'])

    bv, bo, br, bs = st.columns([1, 1, 1, 1])

    if bv.button("✓ verified", type="primary", use_container_width=True):
        db.mark_verified(rid, payload=build_verified_payload(row))
        st.session_state.last_snapshot = (rid, snapshot)
        st.session_state.counts['verified'] += 1
        st.rerun()

    with bo:
        reason = st.selectbox(
            "OOS reason", V2_OOS_REASONS, key=f"oos_reason_{rid}",
            label_visibility='collapsed',
        )
        if st.button("✗ OOS", use_container_width=True, key=f"oos_btn_{rid}"):
            db.mark_oos(rid, payload=build_oos_payload(row, reason=reason))
            st.session_state.last_snapshot = (rid, snapshot)
            st.session_state.counts['oos'] += 1
            st.rerun()

    if br.button("↺ re-tag", use_container_width=True):
        db.mark_pending(rid)
        st.session_state.last_snapshot = (rid, snapshot)
        st.session_state.counts['retag'] += 1
        st.rerun()

    if bs.button("↻ skip", use_container_width=True):
        st.session_state.skipped_ids.add(rid)
        st.session_state.counts['skip'] += 1
        st.rerun()

    # Undo
    if st.session_state.last_snapshot is not None:
        last_id, last_snap = st.session_state.last_snapshot
        if st.button(f"↶ undo last (id={last_id})"):
            db.restore_snapshot(last_id, snapshot=last_snap)
            st.session_state.last_snapshot = None
            # If the undone id was in skipped, take it back out so it reappears
            st.session_state.skipped_ids.discard(last_id)
            st.rerun()
```

- [ ] **Step 7.2: Streamlit lint — import 동작 확인**

Run:
```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -c "import langgraph_tagger.review_viewer.app; print('import OK')"
```

Expected: `import OK`. (Streamlit script은 import만으로는 UI 렌더 안 함 — `st` 명령들이 no-op으로 처리되거나 경고만 뜸. import 실패 = 코드 오류.)

- [ ] **Step 7.3: Commit**

```bash
git add langgraph_tagger/review_viewer/app.py
git commit -m "$(cat <<'EOF'
feat(review_viewer): app.py — Streamlit UI for verified/OOS/re-tag/skip + undo

Composes config + db + actions + pdf. Session state holds total_at_start,
counts, skipped_ids, last_snapshot. PDF rendered as PNG pages (PyMuPDF),
"Open in OS viewer" button dispatches to platform default viewer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `__main__.py` launcher

**Files:**
- Create: `langgraph_tagger/review_viewer/__main__.py`

- [ ] **Step 8.1: `__main__.py` 작성**

`langgraph_tagger/review_viewer/__main__.py`:

```python
"""Entry point: `python -m langgraph_tagger.review_viewer`.

Spawns `streamlit run` on app.py so the operator does not need to remember
the streamlit CLI syntax.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    app_path = Path(__file__).with_name('app.py')
    cmd = [sys.executable, '-m', 'streamlit', 'run', str(app_path)]
    return subprocess.call(cmd)


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 8.2: 호출 시 streamlit이 띄워지는지 dry-test**

```powershell
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -c "from langgraph_tagger.review_viewer.__main__ import main; print('callable')"
```

Expected: `callable` 출력. (`main()` 자체는 실행 안 함 — 그건 manual smoke에서.)

- [ ] **Step 8.3: Commit**

```bash
git add langgraph_tagger/review_viewer/__main__.py
git commit -m "$(cat <<'EOF'
feat(review_viewer): __main__.py — python -m launcher

Spawns 'streamlit run app.py' so operators do not need streamlit CLI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 운영 smoke test

(Manual — 코드 변경 없음.)

Pre-conditions:
- Task 1 dependency 설치 완료
- Task 2 migration 004가 Supabase에 적용 완료
- `tagging_status='review_needed'` 행이 최소 1건 이상 있어야 함 (현재 운영 큐 상태로 만족)

- [ ] **Step 9.1: viewer 띄우기**

```powershell
Push-Location 'C:\Users\imyon\Projects\telegram_report'
& .\.venv\Scripts\python.exe -m langgraph_tagger.review_viewer
Pop-Location
```

Expected:
- 콘솔에 `You can now view your Streamlit app in your browser. Local URL: http://localhost:8501` 비슷한 메시지
- 브라우저가 자동으로 그 URL을 열어줌 (또는 사용자가 직접 클릭)
- 화면에 좌 PDF / 우 검수 패널 + 4 버튼이 보임

- [ ] **Step 9.2: 1건 verified 시도**

화면에 보이는 첫 행에 대해 `✓ verified` 클릭.

검증 query (Supabase SQL Editor):

```sql
SELECT id, tagging_status, tagged_at
  FROM reports
 WHERE id = <방금 본 id>;
```

Expected: `tagging_status='verified'`, 다른 분석 필드 그대로.

- [ ] **Step 9.3: 1건 OOS 시도**

다음 행에서 OOS dropdown으로 `foreign` 선택 후 `✗ OOS` 클릭.

검증 query:

```sql
SELECT id, tagging_status, out_of_scope_reason,
       stock_codes, company_names, sectors_major, products,
       report_type, publisher
  FROM reports
 WHERE id = <방금 본 id>;
```

Expected:
- `tagging_status='verified'`
- `out_of_scope_reason='foreign'`
- `stock_codes`, `company_names`, `sectors_major`, `products` 모두 `{}` (빈 배열)
- `report_type`, `publisher`는 LLM 원본 그대로 (NULL 아님)

- [ ] **Step 9.4: 1건 re-tag 시도**

`↺ re-tag` 클릭.

검증 query:

```sql
SELECT id, tagging_status, tagged_at, tagging_notes, report_type, stock_codes
  FROM reports
 WHERE id = <방금 본 id>;
```

Expected:
- `tagging_status='pending'`
- `tagged_at IS NULL`, `tagging_notes IS NULL`
- `report_type IS NULL`, `stock_codes='{}'`

- [ ] **Step 9.5: 1건 skip 시도**

`↻ skip` 클릭. 다음 행이 자동 로드.

같은 세션에서 한 번 더 fetch가 그 skip된 id를 안 가져오는지 확인 (방금 본 id가 다시 안 떠야 함).

브라우저 새로고침(F5)으로 세션 초기화 후 viewer 다시 실행하면 그 skip된 id가 다시 큐에 나타나야 함 (DB 무변화 의미).

- [ ] **Step 9.6: undo 시도**

직전 결정(어떤 액션이든 마지막) 직후 `↶ undo last` 클릭.

검증 query (직전 액션의 id):

```sql
SELECT id, tagging_status, tagging_notes, out_of_scope_reason
  FROM reports
 WHERE id = <undo한 id>;
```

Expected:
- `tagging_status='review_needed'` (원래 상태로 복원)
- `tagging_notes`도 원래대로

- [ ] **Step 9.7: PDF 없는 row 시도**

만약 화면에 떠 있는 row의 PDF 파일이 storage 디렉터리에 없으면(드물지만 발생 가능), 좌측에 경고 메시지가 보이고 우측 패널·버튼은 그대로 동작해야 함.

이 케이스를 인위적으로 만들고 싶으면:
```powershell
# 어떤 file_path 한 건 가져와서 그 file을 임시 백업 후 재시도
$row = & python -c "from langgraph_tagger.review_viewer.config import load_review_viewer_config; from supabase import create_client; cfg = load_review_viewer_config(); c = create_client(cfg.supabase_url, cfg.supabase_service_key); r = c.table('reports').select('id, file_path').eq('tagging_status','review_needed').limit(1).execute().data[0]; print(r['file_path'])"
$src = Join-Path 'C:\Users\imyon\Projects\telegram_report\reports' $row.Trim()
$dst = "$src.bak"
Move-Item $src $dst
# viewer 다시 띄우고 그 row에서 경고 확인
# 끝나면 Move-Item $dst $src 로 원복
```

이 테스트 안 해도 큰 문제 없음 — 다른 검증으로 충분.

- [ ] **Step 9.8: Open in OS viewer 시도**

화면 좌측 하단의 `📄 Open in OS viewer` 클릭. Windows 기본 PDF 뷰어(Edge/Acrobat 등)가 새 창으로 그 PDF를 열어야 함.

- [ ] **Step 9.9: 큐 비었음 화면 검증**

(시간 여유 있으면) review_needed 큐를 다 처리하고 마지막 화면을 확인.

또는 인위적으로 빈 큐 시뮬레이션:

```sql
-- 임시로 모든 review_needed 행을 auto로 옮긴 후 viewer 재실행
-- (실제 운영에서는 절대 실행 금지! 검증용 dry idea)
```

이 단계는 굳이 실행 안 해도 됨. 운영하다 자연스럽게 만나는 상태.

- [ ] **Step 9.10: 운영 1차 결과 보고**

`python -m langgraph_tagger inspect`로 전체 분포 한 번 더 확인. verified 카운터 증가, review_needed 감소 확인.

---

## Self-Review

**Spec 커버리지:**
- Section 2 Goals — 4 액션(verified/OOS/re-tag/skip): Task 5 + 7 ✓
- Section 2.3 PDF 미리보기: Task 4 + 7 ✓
- Section 2.4 자동 다음 행: Task 7 (`st.rerun()`) ✓
- Section 2.5 undo 스냅샷: Task 5 (`capture_snapshot`, `SNAPSHOT_COLUMNS`) + Task 6 (`restore_snapshot`) + Task 7 ✓
- Section 5 Components — 6 파일 + 3 테스트: Task 3~8 ✓
- Section 7 DB semantics + migration 004: Task 2, Task 5 (payload builders), Task 6 (DB methods) ✓
- Section 8 UI 위계 7 단계: Task 7 ✓
- Section 9 큐 순서 FIFO + skip NOT IN: Task 6 (`fetch_next_review`) ✓
- Section 10 Error handling: Task 7 (PDF 없음 / render 실패 분기) ✓
- Section 11 Testing — pdf/db/actions 자동 + manual smoke: Task 4, 5, 6, 9 ✓
- Section 12 의존성 — streamlit 추가: Task 1 ✓

**Placeholder 스캔:** "TBD" / "implement later" / "Similar to Task N" 없음. 모든 step에 actual code/command.

**Type 일관성:**
- `SNAPSHOT_COLUMNS`: Task 5에서 22 컬럼 tuple. Task 6 `restore_snapshot`에서 filter 키로 사용. consistent.
- `ReviewViewerConfig`: Task 3에서 정의 (3 필드). Task 7에서 `load_review_viewer_config()` 호출. consistent.
- `ReviewDB`: Task 6에서 6 메서드 정의. Task 7에서 정확히 그 6 메서드 호출. consistent.
- `V2_OOS_REASONS`: Task 5에서 tuple. Task 7에서 selectbox options로 사용. consistent.
- `build_verified_payload(row)` / `build_oos_payload(row, reason)` / `build_pending_reset_payload()`: Task 5에서 시그니처. Task 7에서 동일 호출 패턴. consistent.

OK. 실행으로 넘어가도 됨.
