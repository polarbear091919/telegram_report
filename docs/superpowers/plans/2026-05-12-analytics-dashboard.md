# Analytics Dashboard (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [Analytics Dashboard Phase 1 spec](../specs/2026-05-12-analytics-dashboard-design.md) — Streamlit single-page web app으로 macro (sector coverage + report type volume) + 종목 dashboard + 즐겨찾기 + 종목 검색 구현.

**Architecture:** Streamlit single-page app, sidebar에서 검색·즐겨찾기·매크로 진입, main 영역은 mode-driven 렌더. DB 접근은 supabase-py REST의 paginated raw fetch (1000-row loop) + `@st.cache_data(ttl=180)` + pandas client-side 집계 (group-by/explode/date_trunc). 차트는 Plotly.

**Tech Stack:** Python 3.11+, Streamlit ~1.40 (기존), Plotly (신규), pandas (신규 명시), supabase-py (기존), pytest.

---

## File Structure

신규 패키지 `langgraph_tagger/analytics/`:

| 파일 | 책임 |
|---|---|
| `__init__.py` | 패키지 marker + 짧은 docstring |
| `config.py` | `AnalyticsConfig` dataclass + `load_analytics_config()` |
| `krx.py` | KRX 마스터 CSV 로딩, `search_stocks(query)`, `lookup(code)` |
| `favorites.py` | `load()`, `add(code)`, `remove(code)` — atomic JSON file |
| `aggregate.py` | pandas 집계 5종 — sector timeseries/ranking, report_type timeseries, stock monthly, publisher dist |
| `charts.py` | Plotly figure builder 5종 |
| `db.py` | `AnalyticsDB` — supabase-py REST wrapper with pagination + `@st.cache_data` |
| `pages/__init__.py` | 빈 marker |
| `pages/macro.py` | 모드 1 — `render(session)` + 2 sub-tabs |
| `pages/stock.py` | 모드 2 — `render(session, code)` |
| `app.py` | Streamlit entry — sidebar + mode router |
| `__main__.py` | `python -m langgraph_tagger.analytics` launcher |
| `tests/__init__.py` | 빈 |
| `tests/conftest.py` | KRX CSV fixture + DataFrame fixture |
| `tests/test_config.py` | 5 tests |
| `tests/test_krx.py` | 7 tests |
| `tests/test_favorites.py` | 7 tests |
| `tests/test_aggregate.py` | 11 tests |
| `tests/test_db.py` | 8 tests |
| `tests/test_charts.py` | 6 tests |

수정:
- `requirements.txt` — `plotly` + `pandas` 줄 추가

---

## Task 1: requirements.txt에 plotly + pandas 추가

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1.1: 의존성 추가**

`requirements.txt`의 `streamlit>=1.40,<2.0` 줄 뒤에 추가:

```
plotly>=5.20,<6.0
pandas>=2.0,<3.0
```

전체 파일은:
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
plotly>=5.20,<6.0
pandas>=2.0,<3.0
asyncpg>=0.29
# Observability: LangSmith auto-traces LangGraph runs when LANGSMITH_TRACING=true.
# wrap_openai (langsmith.wrappers) nests OpenAI calls under graph spans.
langsmith>=0.4,<1.0
```

- [ ] **Step 1.2: pip install**

```powershell
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pip install -r 'C:\Users\imyon\Projects\telegram_report\.claude\worktrees\sweet-dewdney-dc0ae1\requirements.txt'
```

- [ ] **Step 1.3: import 확인**

```powershell
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -c "import plotly, pandas; print(plotly.__version__, pandas.__version__)"
```

Expected: 두 버전 출력 (예: `5.x.x 2.x.x`).

- [ ] **Step 1.4: Commit**

```bash
git add requirements.txt
git commit -m "$(cat <<'EOF'
chore(deps): add plotly + pandas for analytics dashboard

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `AnalyticsConfig`

**Files:**
- Create: `langgraph_tagger/analytics/__init__.py`
- Create: `langgraph_tagger/analytics/config.py`
- Create: `langgraph_tagger/analytics/tests/__init__.py`
- Create: `langgraph_tagger/analytics/tests/test_config.py`

- [ ] **Step 2.1: 패키지 marker 파일들**

`langgraph_tagger/analytics/__init__.py`:
```python
"""Analytics dashboard: Streamlit web app for sector coverage + stock dashboards."""
```

`langgraph_tagger/analytics/tests/__init__.py`:
```python
```

- [ ] **Step 2.2: 실패 테스트**

`langgraph_tagger/analytics/tests/test_config.py`:
```python
from pathlib import Path

import pytest

from langgraph_tagger.analytics.config import AnalyticsConfig, load_analytics_config


def test_load_happy_path(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'eyJtest')
    monkeypatch.setenv('STORAGE_BASE_DIR', '/tmp/reports')
    monkeypatch.setenv('KRX_CSV_PATH', 'docs/stock_data/KRX_stocks_data.csv')

    cfg = load_analytics_config()

    assert isinstance(cfg, AnalyticsConfig)
    assert cfg.supabase_url == 'https://test.supabase.co'
    assert cfg.supabase_service_key == 'eyJtest'
    assert cfg.storage_base_dir == Path('/tmp/reports')
    assert cfg.krx_csv_path == Path('docs/stock_data/KRX_stocks_data.csv')


def test_load_defaults(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    for k in ('STORAGE_BASE_DIR', 'KRX_CSV_PATH'):
        monkeypatch.delenv(k, raising=False)

    cfg = load_analytics_config()
    assert cfg.storage_base_dir == Path('./reports')
    assert cfg.krx_csv_path == Path('docs/stock_data/KRX_stocks_data.csv')


def test_missing_supabase_url_exits(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    with pytest.raises(SystemExit) as e:
        load_analytics_config()
    assert 'SUPABASE_URL' in str(e.value)


def test_missing_supabase_key_exits(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.delenv('SUPABASE_SERVICE_KEY', raising=False)
    with pytest.raises(SystemExit) as e:
        load_analytics_config()
    assert 'SUPABASE_SERVICE_KEY' in str(e.value)


def test_does_not_require_openai_or_telegram(monkeypatch):
    """Analytics must run without OPENAI_API_KEY / TELEGRAM_* / SUPABASE_DB_URL."""
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    for k in ('OPENAI_API_KEY', 'TELEGRAM_API_ID', 'TELEGRAM_API_HASH',
              'TELEGRAM_CHANNEL', 'SUPABASE_DB_URL'):
        monkeypatch.delenv(k, raising=False)
    cfg = load_analytics_config()
    assert cfg.supabase_url == 'u'
```

- [ ] **Step 2.3: 실패 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_config.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 2.4: `config.py` 구현**

`langgraph_tagger/analytics/config.py`:
```python
"""Standalone config for the analytics dashboard.

Intentionally separate from langgraph_tagger.config so the dashboard can
run without OPENAI_API_KEY, SUPABASE_DB_URL, or TELEGRAM_* envs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AnalyticsConfig:
    supabase_url: str
    supabase_service_key: str
    storage_base_dir: Path
    krx_csv_path: Path


def load_analytics_config() -> AnalyticsConfig:
    load_dotenv()

    def required(key: str) -> str:
        v = os.getenv(key)
        if not v:
            raise SystemExit(f"Missing required env var: {key}")
        return v

    return AnalyticsConfig(
        supabase_url=required('SUPABASE_URL'),
        supabase_service_key=required('SUPABASE_SERVICE_KEY'),
        storage_base_dir=Path(os.getenv('STORAGE_BASE_DIR', './reports')),
        krx_csv_path=Path(os.getenv('KRX_CSV_PATH', 'docs/stock_data/KRX_stocks_data.csv')),
    )
```

- [ ] **Step 2.5: 통과 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_config.py -v
```
Expected: 5 passed.

- [ ] **Step 2.6: Commit**

```bash
git add langgraph_tagger/analytics/__init__.py langgraph_tagger/analytics/config.py langgraph_tagger/analytics/tests/__init__.py langgraph_tagger/analytics/tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(analytics): AnalyticsConfig — standalone env loader

Decouples analytics dashboard from tagger/collector envs (OPENAI_API_KEY,
TELEGRAM_*, SUPABASE_DB_URL).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `krx` 모듈 — KRX 마스터 검색

**Files:**
- Create: `langgraph_tagger/analytics/krx.py`
- Create: `langgraph_tagger/analytics/tests/conftest.py`
- Create: `langgraph_tagger/analytics/tests/test_krx.py`

- [ ] **Step 3.1: conftest.py에 KRX fixture 추가**

`langgraph_tagger/analytics/tests/conftest.py`:
```python
"""Shared fixtures for analytics tests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def krx_csv(tmp_path: Path) -> Path:
    """Minimal KRX master CSV for unit tests.

    Headers match the real docs/stock_data/KRX_stocks_data.csv:
    '종목\\n코드, 종목명, 시장, 산업명(대), 산업명(중), 주요제품'.
    """
    p = tmp_path / 'krx_test.csv'
    p.write_text(
        '"종목\n코드",종목명,시장,산업명(대),산업명(중),주요제품\n'
        '005930,삼성전자,KOSPI,반도체,메모리반도체,DRAM/NAND\n'
        '000660,SK하이닉스,KOSPI,반도체,메모리반도체,DRAM/NAND\n'
        '373220,LG에너지솔루션,KOSPI,2차전지,셀,리튬이온배터리\n'
        '035720,카카오,KOSPI,IT,플랫폼,메신저\n'
        '042660,한화오션,KOSPI,조선,상선,LNG선\n',
        encoding='utf-8',
    )
    return p
```

- [ ] **Step 3.2: 실패 테스트**

`langgraph_tagger/analytics/tests/test_krx.py`:
```python
import pytest

from langgraph_tagger.analytics.krx import load_krx, search_stocks, lookup


def test_load_krx_returns_dataframe_with_known_columns(krx_csv):
    df = load_krx(krx_csv)
    assert 'code' in df.columns
    assert 'name' in df.columns
    assert 'sector_major' in df.columns
    assert 'sector_minor' in df.columns
    assert len(df) == 5


def test_search_by_code_prefix(krx_csv):
    df = load_krx(krx_csv)
    result = search_stocks(df, '005')
    codes = result['code'].tolist()
    assert '005930' in codes
    assert '000660' not in codes


def test_search_by_name_substring(krx_csv):
    df = load_krx(krx_csv)
    result = search_stocks(df, '삼성')
    codes = result['code'].tolist()
    assert '005930' in codes


def test_search_empty_query_returns_all(krx_csv):
    df = load_krx(krx_csv)
    result = search_stocks(df, '')
    assert len(result) == 5


def test_lookup_returns_tuple(krx_csv):
    df = load_krx(krx_csv)
    info = lookup(df, '005930')
    assert info == ('005930', '삼성전자', '반도체', '메모리반도체')


def test_lookup_missing_returns_none(krx_csv):
    df = load_krx(krx_csv)
    assert lookup(df, '999999') is None


def test_load_krx_missing_file(tmp_path):
    missing = tmp_path / 'nope.csv'
    with pytest.raises(FileNotFoundError):
        load_krx(missing)
```

- [ ] **Step 3.3: 실패 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_krx.py -v
```
Expected: ImportError.

- [ ] **Step 3.4: `krx.py` 구현**

`langgraph_tagger/analytics/krx.py`:
```python
"""KRX master CSV loader + search/lookup helpers.

Reads the project's KRX_stocks_data.csv into a DataFrame with
normalized columns: code, name, sector_major, sector_minor.

Real CSV headers: '종목\\n코드', '종목명', '시장', '산업명(대)',
'산업명(중)', '주요제품'. We use the first 5 (주요제품 is too granular
for the analytics dashboard).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_CODE_COL = '종목\n코드'   # literal newline inside the header — same as real CSV


def load_krx(csv_path: Path) -> pd.DataFrame:
    """Load KRX master CSV into a DataFrame.

    Normalizes Korean source columns to (code, name, sector_major, sector_minor).
    Raises FileNotFoundError if path missing.
    """
    if not csv_path.exists():
        raise FileNotFoundError(str(csv_path))
    raw = pd.read_csv(csv_path, dtype={_CODE_COL: str})
    df = pd.DataFrame({
        'code': raw[_CODE_COL].astype(str).str.zfill(6),
        'name': raw['종목명'].astype(str),
        'sector_major': raw.get('산업명(대)', pd.Series([''] * len(raw))).astype(str),
        'sector_minor': raw.get('산업명(중)', pd.Series([''] * len(raw))).astype(str),
    })
    return df


def search_stocks(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Filter df by code-prefix or name-substring (case-insensitive).

    Empty query returns all rows.
    """
    q = (query or '').strip()
    if not q:
        return df
    mask = (
        df['code'].str.startswith(q)
        | df['name'].str.contains(q, case=False, na=False, regex=False)
    )
    return df[mask].reset_index(drop=True)


def lookup(df: pd.DataFrame, code: str) -> tuple[str, str, str, str] | None:
    """Return (code, name, sector_major, sector_minor) for the row matching code, or None."""
    rows = df[df['code'] == str(code).zfill(6)]
    if len(rows) == 0:
        return None
    r = rows.iloc[0]
    return (r['code'], r['name'], r['sector_major'], r['sector_minor'])
```

- [ ] **Step 3.5: 통과 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_krx.py -v
```
Expected: 7 passed.

- [ ] **Step 3.6: Commit**

```bash
git add langgraph_tagger/analytics/krx.py langgraph_tagger/analytics/tests/conftest.py langgraph_tagger/analytics/tests/test_krx.py
git commit -m "$(cat <<'EOF'
feat(analytics): krx module — master CSV load + search + lookup

Normalizes (단축코드, 한글 종목명, 산업) to (code, name, sector).
search_stocks supports code-prefix and name-substring matching.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `favorites` 모듈 — 종목 즐겨찾기 JSON 파일

**Files:**
- Create: `langgraph_tagger/analytics/favorites.py`
- Create: `langgraph_tagger/analytics/tests/test_favorites.py`

- [ ] **Step 4.1: 실패 테스트**

`langgraph_tagger/analytics/tests/test_favorites.py`:
```python
import json
from pathlib import Path

import pytest

from langgraph_tagger.analytics import favorites


def test_load_missing_file_returns_empty(tmp_path: Path):
    path = tmp_path / 'favs.json'
    result = favorites.load(path)
    assert result == []
    assert not path.exists()


def test_load_creates_parent_dir_on_add(tmp_path: Path):
    path = tmp_path / 'sub' / 'favs.json'
    favorites.add(path, '005930')
    assert path.exists()
    assert json.loads(path.read_text(encoding='utf-8')) == {'stocks': ['005930']}


def test_add_is_idempotent(tmp_path: Path):
    path = tmp_path / 'favs.json'
    favorites.add(path, '005930')
    favorites.add(path, '005930')
    favorites.add(path, '005930')
    assert favorites.load(path) == ['005930']


def test_add_preserves_order(tmp_path: Path):
    path = tmp_path / 'favs.json'
    favorites.add(path, '005930')
    favorites.add(path, '000660')
    favorites.add(path, '373220')
    assert favorites.load(path) == ['005930', '000660', '373220']


def test_remove_existing(tmp_path: Path):
    path = tmp_path / 'favs.json'
    favorites.add(path, '005930')
    favorites.add(path, '000660')
    favorites.remove(path, '005930')
    assert favorites.load(path) == ['000660']


def test_remove_absent_is_noop(tmp_path: Path):
    path = tmp_path / 'favs.json'
    favorites.add(path, '005930')
    favorites.remove(path, '999999')
    assert favorites.load(path) == ['005930']


def test_corrupted_json_backs_up_and_returns_empty(tmp_path: Path):
    path = tmp_path / 'favs.json'
    path.write_text('not valid json {', encoding='utf-8')
    result = favorites.load(path)
    assert result == []
    bak = path.with_suffix('.json.bak')
    assert bak.exists()
    assert bak.read_text(encoding='utf-8') == 'not valid json {'
```

- [ ] **Step 4.2: 실패 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_favorites.py -v
```
Expected: ImportError.

- [ ] **Step 4.3: `favorites.py` 구현**

`langgraph_tagger/analytics/favorites.py`:
```python
"""Stock favorites persisted in a JSON file.

Atomic writes via tempfile + os.replace. Corrupted JSON is moved to a
.bak sibling and the file is treated as empty (graceful recovery).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _read(path: Path) -> list[str]:
    """Read favorites list. Returns [] if file missing.

    On JSON corruption: move file to .bak and return [].
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return list(data.get('stocks', []))
    except (json.JSONDecodeError, ValueError):
        bak = path.with_suffix('.json.bak')
        path.rename(bak)
        return []


def _write_atomic(path: Path, stocks: list[str]) -> None:
    """Atomic JSON write — tempfile in same dir, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'stocks': stocks}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load(path: Path) -> list[str]:
    """Public: return list of stock codes from the favorites file."""
    return _read(path)


def add(path: Path, code: str) -> None:
    """Idempotent — duplicate adds are no-ops; insertion order preserved."""
    stocks = _read(path)
    if code in stocks:
        return
    stocks.append(code)
    _write_atomic(path, stocks)


def remove(path: Path, code: str) -> None:
    """No-op if code absent."""
    stocks = _read(path)
    if code not in stocks:
        return
    stocks.remove(code)
    _write_atomic(path, stocks)
```

- [ ] **Step 4.4: 통과 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_favorites.py -v
```
Expected: 7 passed.

- [ ] **Step 4.5: Commit**

```bash
git add langgraph_tagger/analytics/favorites.py langgraph_tagger/analytics/tests/test_favorites.py
git commit -m "$(cat <<'EOF'
feat(analytics): favorites — atomic JSON file for stock favorites

Idempotent add, no-op remove, JSON corruption recovers via .bak.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `aggregate` 모듈 — pandas 집계 5종

**Files:**
- Create: `langgraph_tagger/analytics/aggregate.py`
- Modify: `langgraph_tagger/analytics/tests/conftest.py` (DataFrame fixture 추가)
- Create: `langgraph_tagger/analytics/tests/test_aggregate.py`

- [ ] **Step 5.1: conftest.py에 in-scope rows fixture 추가**

`langgraph_tagger/analytics/tests/conftest.py` 끝에 추가:
```python


@pytest.fixture
def inscope_df() -> pd.DataFrame:
    """Small DataFrame representing in-scope rows for aggregate tests.

    Every row has both published_at and sent_at. effective_date will be
    derived from these by db.py / aggregate._ensure_effective_date.
    """
    return pd.DataFrame([
        # 단일종목 + 단일 stock_code
        {'published_at': '2026-05-01', 'sent_at': '2026-05-01T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': '메리츠',
         'stock_codes': ['005930'], 'sectors_major': ['반도체'],
         'sectors_minor': ['메모리반도체'], 'products': ['DRAM'],
         'out_of_scope_reason': None},
        # 단일종목 + 같은 종목, 다른 발행처
        {'published_at': '2026-05-02', 'sent_at': '2026-05-02T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': '키움',
         'stock_codes': ['005930'], 'sectors_major': ['반도체'],
         'sectors_minor': ['메모리반도체'], 'products': ['DRAM', 'NAND'],
         'out_of_scope_reason': None},
        # 단일종목 — 다른 종목
        {'published_at': '2026-05-03', 'sent_at': '2026-05-03T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': '키움',
         'stock_codes': ['000660'], 'sectors_major': ['반도체'],
         'sectors_minor': ['메모리반도체'], 'products': ['DRAM'],
         'out_of_scope_reason': None},
        # 섹터 — multi-stock
        {'published_at': '2026-05-04', 'sent_at': '2026-05-04T08:00:00+00:00',
         'report_type': '섹터', 'publisher': 'NH',
         'stock_codes': ['005930', '000660'], 'sectors_major': ['반도체'],
         'sectors_minor': ['메모리반도체'], 'products': ['DRAM'],
         'out_of_scope_reason': None},
        # 산업 — 빈 stock_codes/sectors
        {'published_at': '2026-05-05', 'sent_at': '2026-05-05T08:00:00+00:00',
         'report_type': '산업', 'publisher': '메리츠',
         'stock_codes': [], 'sectors_major': [],
         'sectors_minor': [], 'products': [],
         'out_of_scope_reason': None},
        # 2차전지 — 다른 sector
        {'published_at': '2026-05-06', 'sent_at': '2026-05-06T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': 'NH',
         'stock_codes': ['373220'], 'sectors_major': ['2차전지'],
         'sectors_minor': ['셀'], 'products': ['리튬이온배터리'],
         'out_of_scope_reason': None},
    ])


@pytest.fixture
def with_oos_df(inscope_df: pd.DataFrame) -> pd.DataFrame:
    """inscope + 2 OOS rows. OOS rows mirror writer semantics: published_at
    is None (writer sets it NULL for OOS), so effective_date must fall back
    to sent_at. This is the test case that exercises the fallback path."""
    extra = pd.DataFrame([
        {'published_at': None, 'sent_at': '2026-05-07T08:00:00+00:00',
         'report_type': 'IR자료', 'publisher': '한국기업평가',
         'stock_codes': ['005930'], 'sectors_major': [],
         'sectors_minor': [], 'products': [],
         'out_of_scope_reason': 'ir_self'},
        {'published_at': None, 'sent_at': '2026-05-08T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': 'Reuters',
         'stock_codes': ['005930'], 'sectors_major': [],
         'sectors_minor': [], 'products': [],
         'out_of_scope_reason': 'foreign'},
    ])
    return pd.concat([inscope_df, extra], ignore_index=True)
```

- [ ] **Step 5.2: 실패 테스트**

`langgraph_tagger/analytics/tests/test_aggregate.py`:
```python
import pandas as pd
import pytest

from langgraph_tagger.analytics.aggregate import (
    sector_timeseries,
    sector_ranking,
    report_type_timeseries,
    stock_monthly,
    publisher_dist,
)


# === sector_timeseries ===

def test_sector_timeseries_groups_by_unit_and_level(inscope_df):
    result = sector_timeseries(inscope_df, level='sectors_major', items=['반도체'], unit='D')
    # 4 inscope rows have '반도체' in sectors_major (rows 0,1,2,3)
    assert result['count'].sum() == 4
    assert '반도체' in result.columns or '반도체' in result['sector'].values


def test_sector_timeseries_overlap_not_contains(inscope_df):
    """multi-select returns rows with ANY of the selected sectors — overlap."""
    result = sector_timeseries(inscope_df,
                                level='sectors_major',
                                items=['반도체', '2차전지'],
                                unit='D')
    # 5 inscope rows have either 반도체 or 2차전지
    assert result['count'].sum() == 5


def test_sector_timeseries_empty_items_uses_top_n(inscope_df):
    """When items is empty, returns top N sectors by volume."""
    result = sector_timeseries(inscope_df, level='sectors_major', items=[], unit='D', top_n=3)
    # All non-empty sectors_major rows (5 rows: 4 반도체 + 1 2차전지)
    assert result['count'].sum() == 5


def test_sector_timeseries_excludes_empty_sectors(inscope_df):
    """Row 4 (산업 type, empty sectors_major) must not appear."""
    result = sector_timeseries(inscope_df, level='sectors_major', items=['반도체'], unit='D')
    assert result['count'].sum() == 4  # not 5 — the 산업 row has empty sectors


# === sector_ranking ===

def test_sector_ranking_counts_unnested_stock_codes(inscope_df):
    """When 반도체 selected, count stock_codes occurrences across matching rows.
    Rows 0,1: ['005930']. Row 2: ['000660']. Row 3: ['005930','000660'].
    Total: 005930 appears 3 times, 000660 appears 2 times.
    """
    result = sector_ranking(inscope_df,
                             level='sectors_major',
                             items=['반도체'],
                             limit=10)
    by_code = dict(zip(result['code'], result['count']))
    assert by_code['005930'] == 3
    assert by_code['000660'] == 2


def test_sector_ranking_empty_items_uses_full_scope(inscope_df):
    """No filter: count over all rows with non-empty stock_codes."""
    result = sector_ranking(inscope_df, level='sectors_major', items=[], limit=10)
    by_code = dict(zip(result['code'], result['count']))
    assert by_code['005930'] == 3
    assert by_code['000660'] == 2
    assert by_code['373220'] == 1


# === report_type_timeseries ===

def test_report_type_timeseries_groups_by_type_and_unit(inscope_df):
    result = report_type_timeseries(inscope_df, unit='D')
    types = result['report_type'].unique().tolist()
    assert '단일종목' in types
    assert '섹터' in types
    assert '산업' in types
    # 단일종목 inscope rows: indices 0,1,2,5 → 4 rows
    type_counts = result.groupby('report_type')['count'].sum()
    assert type_counts['단일종목'] == 4
    assert type_counts['섹터'] == 1
    assert type_counts['산업'] == 1


def test_report_type_timeseries_oos_off_excludes_oos(with_oos_df):
    """Default (no OOS) — IR자료 OOS and foreign OOS not counted."""
    result = report_type_timeseries(with_oos_df, unit='D')
    types = result['report_type'].unique().tolist()
    assert 'IR자료' not in types
    # The foreign-tagged 단일종목 row (out_of_scope_reason='foreign') must also be excluded
    type_counts = result.groupby('report_type')['count'].sum()
    assert type_counts['단일종목'] == 4   # excludes the foreign OOS one


def test_report_type_timeseries_oos_on_includes_all(with_oos_df):
    """include_oos=True — IR자료 + foreign OOS rows counted.

    Regression: OOS rows have published_at=None and only sent_at set.
    The aggregator must derive effective_date from sent_at, otherwise
    these rows silently drop out of the count.
    """
    result = report_type_timeseries(with_oos_df, unit='D', include_oos=True)
    types = result['report_type'].unique().tolist()
    assert 'IR자료' in types
    type_counts = result.groupby('report_type')['count'].sum()
    assert type_counts['IR자료'] == 1
    assert type_counts['단일종목'] == 5   # includes the foreign OOS 단일종목 row


def test_report_type_timeseries_uses_sent_at_when_published_at_null():
    """Explicit regression: a row with only sent_at (no published_at) must
    appear in include_oos=True buckets, using sent_at KST date."""
    df = pd.DataFrame([
        {'published_at': None,
         'sent_at': '2026-05-07T22:00:00+00:00',   # 2026-05-08 KST
         'report_type': 'IR자료', 'publisher': 'X',
         'stock_codes': [], 'sectors_major': [], 'sectors_minor': [],
         'products': [], 'out_of_scope_reason': 'ir_self'},
    ])
    result = report_type_timeseries(df, unit='D', include_oos=True)
    assert len(result) == 1
    # The bucket date is the sent_at KST date (2026-05-08), not UTC (2026-05-07)
    assert result.iloc[0]['bucket'].strftime('%Y-%m-%d') == '2026-05-08'
    assert result.iloc[0]['report_type'] == 'IR자료'


# === stock_monthly ===

def test_stock_monthly_filters_by_code(inscope_df):
    result = stock_monthly(inscope_df, code='005930', unit='D')
    # Rows 0,1,3 have 005930 (in_df rows 0,1,3 — row 3 is the 섹터 multi-stock)
    assert result['count'].sum() == 3


def test_stock_monthly_unknown_code_returns_empty(inscope_df):
    result = stock_monthly(inscope_df, code='999999', unit='D')
    assert result['count'].sum() == 0


# === publisher_dist ===

def test_publisher_dist_counts_by_publisher(inscope_df):
    """For 005930 rows: 메리츠(1), 키움(1), NH(1)."""
    df_stock = inscope_df[inscope_df['stock_codes'].apply(lambda lst: '005930' in lst)]
    result = publisher_dist(df_stock, top_k=10)
    by_pub = dict(zip(result['publisher'], result['count']))
    assert by_pub['메리츠'] == 1
    assert by_pub['키움'] == 1
    assert by_pub['NH'] == 1


def test_publisher_dist_top_k_groups_into_other(inscope_df):
    """If top_k < unique publishers, the rest go to '기타'."""
    result = publisher_dist(inscope_df, top_k=2)
    pubs = result['publisher'].tolist()
    assert '기타' in pubs
    # All rows accounted for
    assert result['count'].sum() == len(inscope_df)
```

- [ ] **Step 5.3: 실패 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_aggregate.py -v
```
Expected: ImportError.

- [ ] **Step 5.4: `aggregate.py` 구현**

`langgraph_tagger/analytics/aggregate.py`:
```python
"""Pandas client-side aggregation for the analytics dashboard.

All functions take a DataFrame (raw rows from supabase) and return a
DataFrame ready to feed a chart. No DB calls, no Streamlit calls — pure.

effective_date: every time-bucketed aggregator uses an effective_date
column = published_at OR (sent_at converted to KST date). Required
because OOS rows have published_at=NULL (writer sets it NULL for OOS),
so without the fallback Report type volume's OOS toggle would silently
drop those rows.
"""
from __future__ import annotations

import pandas as pd


def _ensure_effective_date(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with an 'effective_date' column derived as:
       published_at  if not null,
       else sent_at converted to KST (UTC+9) and floored to the date.
    """
    out = df.copy()
    pub = pd.to_datetime(out['published_at'], errors='coerce')
    sent = pd.to_datetime(out['sent_at'], errors='coerce', utc=True)
    sent_kst = (sent.dt.tz_convert('Asia/Seoul')
                    .dt.tz_localize(None)
                    .dt.normalize())
    out['effective_date'] = pub.fillna(sent_kst)
    return out


def _floor_to_unit(s: pd.Series, unit: str) -> pd.Series:
    """Floor a datetime series to the unit: D (day), W (week), M (month).

    Uses period alias (not frequency alias). 'MS' is a frequency alias
    (Month Start offset) and is NOT a valid argument to Series.dt.to_period;
    use 'M' and let .dt.start_time give the first day of that month.
    """
    mapping = {'D': 'D', 'W': 'W', 'M': 'M'}
    freq = mapping.get(unit, 'D')
    return s.dt.to_period(freq).dt.start_time


def sector_timeseries(df: pd.DataFrame,
                       level: str,
                       items: list[str],
                       unit: str,
                       top_n: int = 10) -> pd.DataFrame:
    """For each (bucket, sector), return count.

    - level: one of 'sectors_major', 'sectors_minor', 'products'
    - items: selected sector names (overlap match). Empty → top N by volume.
    - unit: 'D', 'W', 'M'
    Output columns: ['bucket', 'sector', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['bucket', 'sector', 'count'])
    d = _ensure_effective_date(df)
    d = d[d[level].apply(lambda lst: isinstance(lst, list) and len(lst) > 0)]
    if d.empty:
        return pd.DataFrame(columns=['bucket', 'sector', 'count'])
    if items:
        d = d[d[level].apply(lambda lst: any(s in items for s in lst))]
    exploded = d.assign(sector=d[level]).explode('sector')
    if items:
        exploded = exploded[exploded['sector'].isin(items)]
    else:
        top = (exploded.groupby('sector').size()
                       .nlargest(top_n).index.tolist())
        exploded = exploded[exploded['sector'].isin(top)]
    exploded['bucket'] = _floor_to_unit(exploded['effective_date'], unit)
    return (exploded.groupby(['bucket', 'sector']).size()
                    .reset_index(name='count'))


def sector_ranking(df: pd.DataFrame,
                    level: str,
                    items: list[str],
                    limit: int = 20) -> pd.DataFrame:
    """For rows matching the sector filter, unnest stock_codes and count desc.

    Output columns: ['code', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['code', 'count'])
    d = df[df['stock_codes'].apply(lambda lst: isinstance(lst, list) and len(lst) > 0)]
    if items:
        d = d[d[level].apply(lambda lst: any(s in items for s in (lst or [])))]
    if d.empty:
        return pd.DataFrame(columns=['code', 'count'])
    codes = d['stock_codes'].explode()
    return (codes.value_counts()
                  .head(limit)
                  .rename_axis('code')
                  .reset_index(name='count'))


def report_type_timeseries(df: pd.DataFrame,
                            unit: str,
                            include_oos: bool = False) -> pd.DataFrame:
    """For each (bucket, report_type), return count.

    If include_oos is False, exclude rows with out_of_scope_reason set.
    Output columns: ['bucket', 'report_type', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['bucket', 'report_type', 'count'])
    d = _ensure_effective_date(df)
    if not include_oos:
        d = d[d['out_of_scope_reason'].isna()]
    if d.empty:
        return pd.DataFrame(columns=['bucket', 'report_type', 'count'])
    d['bucket'] = _floor_to_unit(d['effective_date'], unit)
    return (d.groupby(['bucket', 'report_type']).size()
             .reset_index(name='count'))


def stock_monthly(df: pd.DataFrame, code: str, unit: str) -> pd.DataFrame:
    """For a single stock, time-bucketed count.

    Output columns: ['bucket', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['bucket', 'count'])
    d = df[df['stock_codes'].apply(lambda lst: isinstance(lst, list) and code in lst)]
    if d.empty:
        return pd.DataFrame(columns=['bucket', 'count'])
    d = _ensure_effective_date(d)
    d['bucket'] = _floor_to_unit(d['effective_date'], unit)
    return d.groupby('bucket').size().reset_index(name='count')


def publisher_dist(df: pd.DataFrame, top_k: int = 5) -> pd.DataFrame:
    """Top K publishers by row count; rest grouped into '기타'.

    Output columns: ['publisher', 'count']
    """
    if df.empty:
        return pd.DataFrame(columns=['publisher', 'count'])
    counts = df['publisher'].value_counts()
    if len(counts) <= top_k:
        return counts.rename_axis('publisher').reset_index(name='count')
    top = counts.head(top_k).rename_axis('publisher').reset_index(name='count')
    others = pd.DataFrame([{
        'publisher': '기타',
        'count': int(counts.iloc[top_k:].sum()),
    }])
    return pd.concat([top, others], ignore_index=True)
```

- [ ] **Step 5.5: 통과 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_aggregate.py -v
```
Expected: 11 passed.

- [ ] **Step 5.6: Commit**

```bash
git add langgraph_tagger/analytics/aggregate.py langgraph_tagger/analytics/tests/conftest.py langgraph_tagger/analytics/tests/test_aggregate.py
git commit -m "$(cat <<'EOF'
feat(analytics): aggregate module — 5 pandas aggregators

sector_timeseries (overlap match), sector_ranking (unnest stock_codes),
report_type_timeseries (with OOS toggle), stock_monthly, publisher_dist
(top K + 기타).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `db` 모듈 — paginated raw fetch + cache

**Files:**
- Create: `langgraph_tagger/analytics/db.py`
- Create: `langgraph_tagger/analytics/tests/test_db.py`

- [ ] **Step 6.1: 실패 테스트**

`langgraph_tagger/analytics/tests/test_db.py`:
```python
from unittest.mock import MagicMock

import pandas as pd
import pytest

from langgraph_tagger.analytics.db import AnalyticsDB


def _make_supabase_with_pages(pages: list[list[dict]]) -> MagicMock:
    """Build a supabase-py client mock whose .range().execute() returns
    pages[i] for the i-th call. Subsequent calls return empty."""
    sb = MagicMock()
    # Build the chainable mock
    table = sb.table.return_value
    chain = (table.select.return_value
                       .in_.return_value
                       .is_.return_value
                       .gte.return_value)
    # The .range(...).execute() must yield pages in sequence
    range_mock = MagicMock()
    chain.range.return_value = range_mock

    page_iter = iter(pages + [[]])  # trailing empty for loop termination
    def _exec():
        return MagicMock(data=next(page_iter, []))
    range_mock.execute.side_effect = _exec
    return sb


def test_fetch_inscope_rows_paginates_until_short_page():
    sb = _make_supabase_with_pages([
        [{'id': i} for i in range(1000)],
        [{'id': 1000}],   # short page → stops
    ])
    db = AnalyticsDB(sb)
    df = db.fetch_inscope_rows(period_start_iso='2026-01-01')
    assert len(df) == 1001


def test_fetch_inscope_rows_applies_in_scope_filter():
    sb = _make_supabase_with_pages([[]])
    db = AnalyticsDB(sb)
    _ = db.fetch_inscope_rows(period_start_iso='2026-01-01')
    # Confirm .in_('tagging_status', ['auto', 'verified']) and is_('out_of_scope_reason', 'null')
    table_select = sb.table.return_value.select.return_value
    table_select.in_.assert_called_with('tagging_status', ['auto', 'verified'])
    table_select.in_.return_value.is_.assert_called_with('out_of_scope_reason', 'null')


def test_fetch_inscope_rows_applies_period_filter():
    sb = _make_supabase_with_pages([[]])
    db = AnalyticsDB(sb)
    _ = db.fetch_inscope_rows(period_start_iso='2026-01-15')
    chain = (sb.table.return_value.select.return_value
                       .in_.return_value
                       .is_.return_value)
    chain.gte.assert_called_with('published_at', '2026-01-15')


def test_fetch_inscope_or_oos_rows_off_applies_isnull_and_period():
    sb = _make_supabase_with_pages([[]])
    db = AnalyticsDB(sb)
    _ = db.fetch_inscope_or_oos_rows(period_start_iso='2026-01-01', include_oos=False)
    select = sb.table.return_value.select.return_value
    select.in_.assert_called_with('tagging_status', ['auto', 'verified'])
    select.in_.return_value.is_.assert_called_with('out_of_scope_reason', 'null')
    select.in_.return_value.is_.return_value.gte.assert_called_with(
        'published_at', '2026-01-01'
    )


def test_fetch_inscope_or_oos_rows_on_skips_isnull_and_period_server_side():
    """OOS-on: server-side filter is tagging_status only.
    Period filter is client-side via effective_date."""
    sb = MagicMock()
    select = sb.table.return_value.select.return_value
    chain = select.in_.return_value.range.return_value
    chain.execute.return_value = MagicMock(data=[])
    db = AnalyticsDB(sb)
    _ = db.fetch_inscope_or_oos_rows(period_start_iso='2026-01-01', include_oos=True)
    # is_('out_of_scope_reason', 'null') must NOT have been chained
    select.in_.return_value.is_.assert_not_called()
    # gte('published_at', ...) must NOT have been chained at the server side
    select.in_.return_value.gte.assert_not_called()


def test_fetch_inscope_or_oos_rows_on_applies_client_side_period_filter():
    """OOS-on: row with published_at=NULL and sent_at < period_start must
    be filtered out client-side via effective_date."""
    sb = _make_supabase_with_pages([[
        # Falls inside period (sent_at KST 2026-05-08)
        {'id': 1, 'published_at': None, 'sent_at': '2026-05-07T22:00:00+00:00',
         'report_type': 'IR자료', 'publisher': 'X',
         'stock_codes': ['005930'], 'company_names': ['삼성전자'],
         'sectors_major': [], 'sectors_minor': [], 'products': [],
         'tagging_status': 'verified', 'out_of_scope_reason': 'ir_self',
         'file_path': '1.pdf', 'file_name': '1.pdf', 'title': ''},
        # Falls outside period (sent_at KST 2026-04-30)
        {'id': 2, 'published_at': None, 'sent_at': '2026-04-29T22:00:00+00:00',
         'report_type': 'IR자료', 'publisher': 'Y',
         'stock_codes': [], 'company_names': [],
         'sectors_major': [], 'sectors_minor': [], 'products': [],
         'tagging_status': 'verified', 'out_of_scope_reason': 'ir_self',
         'file_path': '2.pdf', 'file_name': '2.pdf', 'title': ''},
    ]])
    db = AnalyticsDB(sb)
    df = db.fetch_inscope_or_oos_rows(period_start_iso='2026-05-01', include_oos=True)
    assert len(df) == 1
    assert df.iloc[0]['id'] == 1


def test_empty_result_returns_dataframe_with_expected_columns():
    """Regression: empty fetches must still expose EXPECTED_COLS so the
    downstream aggregators don't KeyError when indexing by column."""
    sb = _make_supabase_with_pages([[]])
    db = AnalyticsDB(sb)
    df = db.fetch_inscope_rows(period_start_iso='2026-01-01')
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
    for col in ('id', 'published_at', 'report_type', 'publisher',
                'stock_codes', 'sectors_major', 'sectors_minor', 'products',
                'sent_at', 'out_of_scope_reason'):
        assert col in df.columns


def test_fetch_returns_dataframe_with_expected_columns():
    sb = _make_supabase_with_pages([[
        {'id': 1, 'published_at': '2026-05-01', 'report_type': '단일종목',
         'publisher': 'NH', 'stock_codes': ['005930'], 'company_names': ['삼성전자'],
         'sectors_major': ['반도체'], 'sectors_minor': ['메모리반도체'],
         'products': ['DRAM'], 'tagging_status': 'auto',
         'out_of_scope_reason': None, 'file_path': '1.pdf', 'file_name': '1.pdf',
         'title': 't', 'sent_at': '2026-05-01T08:00:00+00:00'},
    ]])
    db = AnalyticsDB(sb)
    df = db.fetch_inscope_rows(period_start_iso='2026-01-01')
    assert isinstance(df, pd.DataFrame)
    for col in ('id', 'published_at', 'report_type', 'publisher', 'stock_codes',
                'sectors_major', 'sectors_minor', 'products'):
        assert col in df.columns
```

- [ ] **Step 6.2: 실패 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_db.py -v
```
Expected: ImportError.

- [ ] **Step 6.3: `db.py` 구현**

`langgraph_tagger/analytics/db.py`:
```python
"""supabase-py REST wrapper with paginated fetch.

Fetcher pattern:
  - in-scope only: server-side published_at filter is safe (writer
    always sets published_at for in-scope rows).
  - OOS included: writer sets published_at=NULL for OOS rows, so the
    server-side published_at filter would silently drop them. Instead,
    skip the server-side period filter and let aggregate.py filter by
    effective_date (published_at or sent_at KST) client-side.

All group-by / unnest / bucket happens client-side in aggregate.py.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

PAGE = 1000

EXPECTED_COLS: tuple[str, ...] = (
    'id', 'published_at', 'sent_at', 'report_type', 'publisher',
    'stock_codes', 'company_names', 'sectors_major', 'sectors_minor',
    'products', 'tagging_status', 'out_of_scope_reason', 'file_path',
    'file_name', 'title',
)

SELECT_COLS = ', '.join(EXPECTED_COLS)


def _paged_fetch(chain) -> list[dict]:
    """Loop .range(offset, offset+PAGE-1).execute() until a short page."""
    rows: list[dict] = []
    offset = 0
    while True:
        result = chain.range(offset, offset + PAGE - 1).execute()
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return rows


def _to_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame that always has the expected columns, even for
    empty results — downstream aggregators index columns by name."""
    df = pd.DataFrame(rows, columns=list(EXPECTED_COLS))
    return df


class AnalyticsDB:
    """Read-only DB wrapper for analytics dashboard."""

    def __init__(self, client: Any) -> None:
        self._sb = client

    def fetch_inscope_rows(self, period_start_iso: str) -> pd.DataFrame:
        """In-scope rows only. tagging_status IN ('auto','verified') AND
        out_of_scope_reason IS NULL AND published_at >= period_start.
        """
        chain = (
            self._sb.table('reports')
            .select(SELECT_COLS)
            .in_('tagging_status', ['auto', 'verified'])
            .is_('out_of_scope_reason', 'null')
            .gte('published_at', period_start_iso)
        )
        rows = _paged_fetch(chain)
        return _to_frame(rows)

    def fetch_inscope_or_oos_rows(self,
                                    period_start_iso: str,
                                    include_oos: bool) -> pd.DataFrame:
        """For Report type volume sub-tab.

        - include_oos=False: in-scope only, server-side published_at filter.
        - include_oos=True: OOS rows have published_at=NULL. Skip the
          server-side period filter and let the caller (aggregate.py) drop
          rows whose effective_date < period_start via _ensure_effective_date.
        """
        chain = (
            self._sb.table('reports')
            .select(SELECT_COLS)
            .in_('tagging_status', ['auto', 'verified'])
        )
        if not include_oos:
            chain = (chain
                     .is_('out_of_scope_reason', 'null')
                     .gte('published_at', period_start_iso))
        rows = _paged_fetch(chain)
        df = _to_frame(rows)
        if include_oos:
            # Client-side period filter using effective_date semantics:
            # published_at OR (sent_at as KST date).
            pub = pd.to_datetime(df['published_at'], errors='coerce')
            sent = pd.to_datetime(df['sent_at'], errors='coerce', utc=True)
            sent_kst = (sent.dt.tz_convert('Asia/Seoul')
                            .dt.tz_localize(None)
                            .dt.normalize())
            eff = pub.fillna(sent_kst)
            cutoff = pd.Timestamp(period_start_iso)
            df = df[eff >= cutoff].reset_index(drop=True)
        return df

    def fetch_stock_rows(self, code: str, period_start_iso: str) -> pd.DataFrame:
        """All in-scope rows where stock_codes contains the given code.

        Uses Postgres array contains: .cs('stock_codes', '{<code>}').
        """
        chain = (
            self._sb.table('reports')
            .select(SELECT_COLS)
            .in_('tagging_status', ['auto', 'verified'])
            .is_('out_of_scope_reason', 'null')
            .cs('stock_codes', f'{{{code}}}')
            .gte('published_at', period_start_iso)
        )
        rows = _paged_fetch(chain)
        return _to_frame(rows)
```

- [ ] **Step 6.4: 통과 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_db.py -v
```
Expected: 8 passed.

- [ ] **Step 6.5: Commit**

```bash
git add langgraph_tagger/analytics/db.py langgraph_tagger/analytics/tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(analytics): db module — paginated fetch + 3 raw-row fetchers

1000-row .range() pagination loop. fetch_inscope_rows (sector/macro),
fetch_inscope_or_oos_rows (Report type volume with OOS toggle),
fetch_stock_rows (stock dashboard via Postgres array contains).

Caching is layered on at the @st.cache_data decorator level in app.py
(kept out of this module so it stays testable without Streamlit runtime).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `charts` 모듈 — Plotly figure builders

**Files:**
- Create: `langgraph_tagger/analytics/charts.py`
- Create: `langgraph_tagger/analytics/tests/test_charts.py`

- [ ] **Step 7.1: 실패 테스트**

`langgraph_tagger/analytics/tests/test_charts.py`:
```python
import pandas as pd
import plotly.graph_objects as go

from langgraph_tagger.analytics.charts import (
    timeseries_line,
    report_type_lines,
    monthly_bar,
    publisher_pie,
    ranking_bar,
)


def test_timeseries_line_returns_figure():
    df = pd.DataFrame({
        'bucket': pd.to_datetime(['2026-05-01', '2026-05-02', '2026-05-01']),
        'sector': ['반도체', '반도체', '2차전지'],
        'count': [1, 2, 1],
    })
    fig = timeseries_line(df, title='Test')
    assert isinstance(fig, go.Figure)
    # One trace per sector
    assert len(fig.data) == 2


def test_report_type_lines_returns_figure():
    df = pd.DataFrame({
        'bucket': pd.to_datetime(['2026-05-01', '2026-05-02']),
        'report_type': ['단일종목', '산업'],
        'count': [3, 1],
    })
    fig = report_type_lines(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


def test_monthly_bar_returns_figure():
    df = pd.DataFrame({
        'bucket': pd.to_datetime(['2026-05-01', '2026-05-02']),
        'count': [3, 5],
    })
    fig = monthly_bar(df, title='월별')
    assert isinstance(fig, go.Figure)


def test_publisher_pie_returns_figure():
    df = pd.DataFrame({
        'publisher': ['NH', '키움', '기타'],
        'count': [10, 5, 3],
    })
    fig = publisher_pie(df)
    assert isinstance(fig, go.Figure)


def test_ranking_bar_returns_figure():
    df = pd.DataFrame({
        'code': ['005930', '000660'],
        'count': [42, 38],
    })
    fig = ranking_bar(df)
    assert isinstance(fig, go.Figure)


def test_empty_df_still_returns_figure():
    df = pd.DataFrame(columns=['bucket', 'sector', 'count'])
    fig = timeseries_line(df, title='Empty')
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0
```

- [ ] **Step 7.2: 실패 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_charts.py -v
```
Expected: ImportError.

- [ ] **Step 7.3: `charts.py` 구현**

`langgraph_tagger/analytics/charts.py`:
```python
"""Plotly figure builders for the analytics dashboard.

All functions take a DataFrame and return a plotly.graph_objects.Figure.
No DB calls, no Streamlit calls — pure.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def timeseries_line(df: pd.DataFrame, title: str = '') -> go.Figure:
    """One line per sector. Columns: bucket, sector, count."""
    if df.empty:
        return go.Figure(layout={'title': title})
    fig = px.line(df, x='bucket', y='count', color='sector', title=title, markers=True)
    fig.update_layout(legend_title_text='산업', xaxis_title='', yaxis_title='발행 건수')
    return fig


def report_type_lines(df: pd.DataFrame) -> go.Figure:
    """One line per report_type. Columns: bucket, report_type, count."""
    if df.empty:
        return go.Figure(layout={'title': 'Report type volume'})
    fig = px.line(df, x='bucket', y='count', color='report_type',
                   title='Report type volume', markers=True)
    fig.update_layout(legend_title_text='유형', xaxis_title='', yaxis_title='발행 건수')
    return fig


def monthly_bar(df: pd.DataFrame, title: str = '') -> go.Figure:
    """Bar chart per bucket. Columns: bucket, count."""
    if df.empty:
        return go.Figure(layout={'title': title})
    fig = px.bar(df, x='bucket', y='count', title=title)
    fig.update_layout(xaxis_title='', yaxis_title='발행 건수')
    return fig


def publisher_pie(df: pd.DataFrame) -> go.Figure:
    """Pie chart. Columns: publisher, count."""
    if df.empty:
        return go.Figure(layout={'title': '발행처 분포'})
    fig = px.pie(df, names='publisher', values='count', title='발행처 분포')
    return fig


def ranking_bar(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar of stock ranking. Columns: code, count.

    Caller may join name before passing for nicer labels (label='code name').
    """
    if df.empty:
        return go.Figure(layout={'title': 'Coverage volume'})
    label_col = 'label' if 'label' in df.columns else 'code'
    fig = px.bar(df, y=label_col, x='count', orientation='h',
                  title='Coverage volume')
    fig.update_layout(yaxis={'categoryorder': 'total ascending'},
                       xaxis_title='건수', yaxis_title='')
    return fig
```

- [ ] **Step 7.4: 통과 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m pytest langgraph_tagger/analytics/tests/test_charts.py -v
```
Expected: 6 passed.

- [ ] **Step 7.5: Commit**

```bash
git add langgraph_tagger/analytics/charts.py langgraph_tagger/analytics/tests/test_charts.py
git commit -m "$(cat <<'EOF'
feat(analytics): charts module — 5 plotly figure builders

timeseries_line (sector coverage), report_type_lines, monthly_bar
(stock dashboard), publisher_pie, ranking_bar. Empty DataFrame returns
an empty Figure (no exception).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `pages/macro.py` — sector coverage + report type volume sub-tabs

**Files:**
- Create: `langgraph_tagger/analytics/pages/__init__.py`
- Create: `langgraph_tagger/analytics/pages/macro.py`

UI 코드. 단위 테스트 없음 — manual smoke로 검증 (Task 12). 코드 구조 모듈화로 logic은 aggregate/db/charts에서 이미 테스트됨.

- [ ] **Step 8.1: pages 폴더 marker**

`langgraph_tagger/analytics/pages/__init__.py`:
```python
```

- [ ] **Step 8.2: `macro.py` 작성**

`langgraph_tagger/analytics/pages/macro.py`:
```python
"""Macro page — two sub-tabs: Sector coverage + Report type volume."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from langgraph_tagger.analytics import aggregate, charts


PERIODS = {
    '최근 30일': 30,
    '최근 90일': 90,
    '최근 180일': 180,
    '최근 1년': 365,
    '전체': 36500,
}
UNITS = {'일별': 'D', '주별': 'W', '월별': 'M'}


def _period_start_iso(label: str) -> str:
    days = PERIODS[label]
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.date().isoformat()


def render(db, krx_df, session) -> None:
    """Render macro page with two sub-tabs."""
    tab_coverage, tab_report_type = st.tabs(['Sector coverage', 'Report type volume'])

    with tab_coverage:
        _render_sector_coverage(db, krx_df, session)

    with tab_report_type:
        _render_report_type_volume(db, session)


def _render_sector_coverage(db, krx_df, session) -> None:
    col_level, col_period, col_unit = st.columns([2, 1, 1])
    with col_level:
        level_label = st.segmented_control(
            'level',
            options=['산업(대)', '산업(중)', '제품'],
            default='산업(대)',
            label_visibility='collapsed',
        ) or '산업(대)'
    level_map = {'산업(대)': 'sectors_major', '산업(중)': 'sectors_minor', '제품': 'products'}
    level_col = level_map[level_label]

    with col_period:
        period_label = st.selectbox('기간', list(PERIODS.keys()), index=1, key='cov_period')
    with col_unit:
        unit_label = st.selectbox('단위', list(UNITS.keys()), index=1, key='cov_unit')

    df_raw = _fetch_inscope_cached(db, _period_start_iso(period_label))

    # Distinct values for the chosen level — for the multiselect
    distinct = sorted({s for lst in df_raw[level_col].dropna()
                        for s in (lst or []) if s})
    items = st.multiselect(
        f'{level_label} 선택 (비워두면 발행량 top 10 자동)',
        options=distinct,
        key='cov_items',
    )

    chart_df = aggregate.sector_timeseries(df_raw, level=level_col, items=items,
                                            unit=UNITS[unit_label])
    col_chart, col_rank = st.columns([2, 1])
    with col_chart:
        st.plotly_chart(charts.timeseries_line(chart_df, title='Sector coverage'),
                         use_container_width=True)
    with col_rank:
        ranking_df = aggregate.sector_ranking(df_raw, level=level_col, items=items, limit=20)
        # Join name from KRX master for nicer labels — degrade gracefully if KRX missing
        if krx_df is not None and not ranking_df.empty:
            ranking_df = ranking_df.merge(krx_df[['code', 'name']], on='code', how='left')
            ranking_df['label'] = ranking_df['code'] + ' ' + ranking_df['name'].fillna('')
        else:
            ranking_df['label'] = ranking_df['code'] if not ranking_df.empty else []
        st.caption('coverage volume — 이 채널에서 다뤄진 횟수 (시장 hot 지표 아님)')
        st.plotly_chart(charts.ranking_bar(ranking_df), use_container_width=True)
        for _, row in ranking_df.iterrows():
            if st.button(row['label'], key=f"rank_{row['code']}"):
                session['current_stock'] = row['code']
                session['current_mode'] = 'stock'
                st.rerun()


def _render_report_type_volume(db, session) -> None:
    col_period, col_unit, col_toggle = st.columns([1, 1, 2])
    with col_period:
        period_label = st.selectbox('기간', list(PERIODS.keys()), index=1, key='rt_period')
    with col_unit:
        unit_label = st.selectbox('단위', list(UNITS.keys()), index=1, key='rt_unit')
    with col_toggle:
        include_oos = st.toggle('OOS 포함 (IR자료 / foreign 등)', value=False, key='rt_oos')

    df_raw = _fetch_inscope_or_oos_cached(db,
                                            _period_start_iso(period_label),
                                            include_oos)
    chart_df = aggregate.report_type_timeseries(df_raw,
                                                  unit=UNITS[unit_label],
                                                  include_oos=include_oos)
    st.plotly_chart(charts.report_type_lines(chart_df), use_container_width=True)
    st.caption('Default: in-scope only (OOS verified 행 제외). toggle 켜면 IR자료/foreign/private/digital 포함.')


@st.cache_data(ttl=180)
def _fetch_inscope_cached(_db, period_start_iso: str):
    return _db.fetch_inscope_rows(period_start_iso)


@st.cache_data(ttl=180)
def _fetch_inscope_or_oos_cached(_db, period_start_iso: str, include_oos: bool):
    return _db.fetch_inscope_or_oos_rows(period_start_iso, include_oos)
```

- [ ] **Step 8.3: import 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -c "import langgraph_tagger.analytics.pages.macro; print('OK')"
```
Expected: `OK` 출력 (Streamlit "no ScriptRunContext" warnings 무시).

- [ ] **Step 8.4: Commit**

```bash
git add langgraph_tagger/analytics/pages/__init__.py langgraph_tagger/analytics/pages/macro.py
git commit -m "$(cat <<'EOF'
feat(analytics): macro page — sector coverage + report type volume

Two sub-tabs via st.tabs. Selectors: level / period / unit / multi-select
items (sector coverage); period / unit / OOS toggle (report type volume).
Caches paginated raw fetches with @st.cache_data(ttl=180).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `pages/stock.py` — 종목 dashboard

**Files:**
- Create: `langgraph_tagger/analytics/pages/stock.py`

- [ ] **Step 9.1: `stock.py` 작성**

`langgraph_tagger/analytics/pages/stock.py`:
```python
"""Stock dashboard page — header + timeseries + publisher dist + report list."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from langgraph_tagger.analytics import aggregate, charts, favorites, krx


PERIODS = {
    '최근 30일': 30,
    '최근 90일': 90,
    '최근 180일': 180,
    '최근 1년': 365,
    '전체': 36500,
}
UNITS = {'일별': 'D', '주별': 'W', '월별': 'M'}


def _period_start_iso(label: str) -> str:
    days = PERIODS[label]
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.date().isoformat()


def _open_locally(pdf_path: Path) -> None:
    path_str = str(pdf_path)
    if sys.platform == 'win32':
        os.startfile(path_str)   # type: ignore[attr-defined]
    elif sys.platform == 'darwin':
        subprocess.run(['open', path_str], check=False)
    else:
        subprocess.run(['xdg-open', path_str], check=False)


def render(db, krx_df, storage_base_dir: Path, favorites_path: Path, session) -> None:
    code = session.get('current_stock')
    if not code:
        st.warning('종목이 선택되지 않았습니다. sidebar의 검색 또는 즐겨찾기에서 선택해주세요.')
        return

    info = krx.lookup(krx_df, code) if krx_df is not None else None
    name = info[1] if info else '(unknown)'
    sector_major = info[2] if info else ''
    sector_minor = info[3] if info else ''

    # Header
    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.subheader(f'{code} {name}')
        sector_caption = ' · '.join(s for s in (sector_major, sector_minor) if s)
        prefix = f'{sector_caption} · ' if sector_caption else ''
        st.caption(f'{prefix}explicit KRX-mapped coverage only — 본문 mention 미포함')
    with col_right:
        col_p, col_fav = st.columns([1, 1])
        with col_p:
            period_label = st.selectbox('기간', list(PERIODS.keys()),
                                          index=3, key=f'stock_period_{code}')
        with col_fav:
            favs = favorites.load(favorites_path)
            if code in favs:
                if st.button('★ 즐겨찾기 해제', key=f'fav_off_{code}'):
                    favorites.remove(favorites_path, code)
                    st.rerun()
            else:
                if st.button('☆ 즐겨찾기 추가', key=f'fav_on_{code}'):
                    favorites.add(favorites_path, code)
                    st.rerun()

    period_iso = _period_start_iso(period_label)
    df_raw = _fetch_stock_cached(db, code, period_iso)

    if df_raw.empty:
        st.info('이 종목 다룬 in-scope 리서치가 아직 없습니다.')
        return

    # Total count
    st.caption(f'총 발행수 {len(df_raw)}건')

    # Top: timeseries + publisher pie
    col_ts, col_pie = st.columns([2, 1])
    with col_ts:
        ts_df = aggregate.stock_monthly(df_raw, code=code, unit='W')
        st.plotly_chart(charts.monthly_bar(ts_df, title='발행 시계열'),
                         use_container_width=True)
    with col_pie:
        pub_df = aggregate.publisher_dist(df_raw, top_k=5)
        st.plotly_chart(charts.publisher_pie(pub_df), use_container_width=True)

    # Bottom: report list
    st.markdown('**발행 리스트**')
    list_df = df_raw[['published_at', 'publisher', 'title', 'report_type', 'file_path']].copy()
    list_df = list_df.sort_values('published_at', ascending=False).reset_index(drop=True)

    page_size = 20
    if f'stock_page_{code}' not in st.session_state:
        st.session_state[f'stock_page_{code}'] = 1
    page = st.session_state[f'stock_page_{code}']
    display = list_df.head(page * page_size)

    for i, row in display.iterrows():
        c1, c2, c3, c4, c5 = st.columns([1, 1, 4, 1, 1])
        with c1:
            st.text(str(row['published_at'])[:10])
        with c2:
            st.text(row['publisher'] or '')
        with c3:
            st.text((row['title'] or '')[:80])
        with c4:
            st.text(row['report_type'] or '')
        with c5:
            file_path = Path(row['file_path']) if row['file_path'] else None
            full_path = (storage_base_dir / file_path) if file_path and not file_path.is_absolute() else file_path
            if full_path and full_path.exists():
                if st.button('📄', key=f'pdf_{code}_{i}'):
                    _open_locally(full_path)
            else:
                st.text('—')

    if len(list_df) > page * page_size:
        if st.button('더 보기', key=f'more_{code}'):
            st.session_state[f'stock_page_{code}'] += 1
            st.rerun()


@st.cache_data(ttl=180)
def _fetch_stock_cached(_db, code: str, period_start_iso: str):
    return _db.fetch_stock_rows(code, period_start_iso)
```

- [ ] **Step 9.2: import 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -c "import langgraph_tagger.analytics.pages.stock; print('OK')"
```
Expected: `OK`.

- [ ] **Step 9.3: Commit**

```bash
git add langgraph_tagger/analytics/pages/stock.py
git commit -m "$(cat <<'EOF'
feat(analytics): stock dashboard page

Header (code · name · sector · explicit-coverage notice · ★ toggle · 기간),
top: weekly timeseries bar + publisher pie, bottom: paginated report list
with OS-viewer PDF open. cached fetch per (code, period).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `app.py` — Streamlit entry + sidebar + mode router

**Files:**
- Create: `langgraph_tagger/analytics/app.py`

- [ ] **Step 10.1: `app.py` 작성**

`langgraph_tagger/analytics/app.py`:
```python
"""Streamlit entry for the analytics dashboard.

Run via: python -m langgraph_tagger.analytics
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
from supabase import create_client

from langgraph_tagger.analytics import favorites, krx
from langgraph_tagger.analytics.config import load_analytics_config
from langgraph_tagger.analytics.db import AnalyticsDB
from langgraph_tagger.analytics.pages import macro, stock


st.set_page_config(page_title='Analytics Dashboard', layout='wide')

FAVORITES_PATH = Path.home() / '.review_viewer' / 'favorites.json'


@st.cache_resource
def _bootstrap():
    cfg = load_analytics_config()
    sb = create_client(cfg.supabase_url, cfg.supabase_service_key)
    db = AnalyticsDB(sb)
    krx_df = krx.load_krx(cfg.krx_csv_path) if cfg.krx_csv_path.exists() else None
    return cfg, db, krx_df


cfg, db, krx_df = _bootstrap()


# session_state init
if 'current_mode' not in st.session_state:
    st.session_state.current_mode = 'macro'
if 'current_stock' not in st.session_state:
    st.session_state.current_stock = None


# ── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('### 🔍 종목 검색')
    if krx_df is not None:
        options = (krx_df['code'] + ' ' + krx_df['name']).tolist()
        selected = st.selectbox(
            '종목 (code 또는 회사명)',
            options=[''] + options,
            index=0,
            label_visibility='collapsed',
            key='search_box',
        )
        if selected:
            picked_code = selected.split(' ', 1)[0]
            if picked_code != st.session_state.current_stock:
                st.session_state.current_stock = picked_code
                st.session_state.current_mode = 'stock'
                st.rerun()
    else:
        st.warning(
            f'KRX 마스터 CSV가 없습니다: {cfg.krx_csv_path}\n\n'
            '검색·종목명 표시가 비활성화됩니다. 매크로는 정상 동작.'
        )

    st.markdown('### ⭐ 즐겨찾기')
    favs = favorites.load(FAVORITES_PATH)
    if not favs:
        st.caption('★ 즐겨찾기는 종목 dashboard의 ★ 버튼으로 추가')
    else:
        for code in favs:
            info = krx.lookup(krx_df, code) if krx_df is not None else None
            label = f'{code} {info[1]}' if info else code
            is_current = (st.session_state.current_mode == 'stock'
                            and st.session_state.current_stock == code)
            if st.button(('▶ ' if is_current else '') + label, key=f'fav_{code}'):
                st.session_state.current_stock = code
                st.session_state.current_mode = 'stock'
                st.rerun()

    st.divider()
    if st.button('📊 매크로'):
        st.session_state.current_mode = 'macro'
        st.rerun()


# ── Main ────────────────────────────────────────────────────────────────────

session = {
    'current_mode': st.session_state.current_mode,
    'current_stock': st.session_state.current_stock,
}

# Macro and stock both gracefully degrade when krx_df is None — pages handle
# absent KRX (ranking shows code only, stock header shows '(unknown)').
if st.session_state.current_mode == 'macro':
    macro.render(db, krx_df, session)
elif st.session_state.current_mode == 'stock':
    stock.render(db, krx_df, cfg.storage_base_dir, FAVORITES_PATH, session)
else:
    st.error(f'Unknown mode: {st.session_state.current_mode}')

# Sync session changes back to st.session_state (in case page handlers mutated)
for k in ('current_mode', 'current_stock'):
    if k in session and session[k] != st.session_state.get(k):
        st.session_state[k] = session[k]
        st.rerun()
```

- [ ] **Step 10.2: import 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -c "import langgraph_tagger.analytics.app; print('OK')"
```
Expected: `OK` (Streamlit "no ScriptRunContext" warnings는 무시).

- [ ] **Step 10.3: Commit**

```bash
git add langgraph_tagger/analytics/app.py
git commit -m "$(cat <<'EOF'
feat(analytics): app.py — Streamlit entry + sidebar + mode router

Composes config + db + krx + favorites + pages. Sidebar has search,
favorites (with row highlight for current), and 매크로 button.
Mode (macro/stock) drives main pane render.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `__main__.py` — python -m launcher

**Files:**
- Create: `langgraph_tagger/analytics/__main__.py`

- [ ] **Step 11.1: 작성**

`langgraph_tagger/analytics/__main__.py`:
```python
"""Entry point: `python -m langgraph_tagger.analytics`.

Spawns `streamlit run` on app.py with headless mode + usage stats disabled
to bypass Streamlit's first-run prompt. Operator opens
http://localhost:8501 manually.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    app_path = Path(__file__).with_name('app.py')
    cmd = [
        sys.executable, '-m', 'streamlit', 'run', str(app_path),
        '--server.headless=true',
        '--browser.gatherUsageStats=false',
    ]
    return subprocess.call(cmd)


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 11.2: 호출 가능 확인**

```bash
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -c "from langgraph_tagger.analytics.__main__ import main; print('callable')"
```
Expected: `callable`.

- [ ] **Step 11.3: Commit**

```bash
git add langgraph_tagger/analytics/__main__.py
git commit -m "$(cat <<'EOF'
feat(analytics): __main__.py — python -m launcher

Same pattern as review_viewer: --server.headless=true and
--browser.gatherUsageStats=false bypass first-run prompts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: 운영 smoke test (manual)

(코드 변경 없음.)

Pre-conditions:
- Task 1 의존성 설치 완료
- KRX_stocks_data.csv가 `docs/stock_data/`에 존재
- 메인 레포 `.env`에 `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `STORAGE_BASE_DIR` 설정됨

- [ ] **Step 12.1: viewer 띄우기**

```powershell
Push-Location 'C:\Users\imyon\Projects\telegram_report\.claude\worktrees\sweet-dewdney-dc0ae1'
& 'C:\Users\imyon\Projects\telegram_report\.venv\Scripts\python.exe' -m langgraph_tagger.analytics
Pop-Location
```

Expected: 콘솔에 `Local URL: http://localhost:8501`. 브라우저 직접 열어 확인.

- [ ] **Step 12.2: 매크로 페이지 — Sector coverage**

기본 진입 화면. 다음 확인:
- 좌측 sidebar에 검색 박스, 즐겨찾기 안내, 매크로 버튼 표시.
- 메인에 두 sub-tab (Sector coverage, Report type volume) 보임.
- Sector coverage 진입 시 level/period/unit selector + multi-select chip 영역 표시.
- multi-select 비워두면 시계열 차트에 자동 top 10 산업 line 보임.
- "반도체" 한 개 선택 후 차트가 그 라인만 표시.
- 우측 ranking에 종목 코드+이름 리스트 표시. 한 행 클릭 시 모드 전환되어 종목 dashboard로 이동.

- [ ] **Step 12.3: 매크로 페이지 — Report type volume**

- sub-tab 전환.
- toggle "OOS 포함" OFF 상태에서 단일종목·산업·섹터·전략·시황·기타가 line으로 보임. IR자료 line은 사실상 0 또는 매우 낮음.
- toggle ON 시 IR자료 line 솟구침. foreign·private 같은 OOS도 포함되어 카운트 증가.

- [ ] **Step 12.4: 종목 검색**

- sidebar 검색 박스에서 `005930` 입력 → 자동완성에 "005930 삼성전자" 표시 → 선택.
- 메인이 종목 dashboard로 전환. 헤더 "005930 삼성전자 / 반도체 · explicit KRX-mapped coverage only" + 기간 dropdown + ★ 토글 버튼.
- 시계열 막대 + 발행처 pie + 발행 리스트 표시.
- "더 보기" 클릭 시 20행 더 로드.
- PDF 버튼 클릭 → OS 기본 뷰어 띄움. 파일 없으면 회색 `—` 표시.

- [ ] **Step 12.5: 즐겨찾기**

- 종목 dashboard에서 ★ 버튼 클릭 → 추가.
- sidebar 새로고침 없이 그 종목이 즐겨찾기 리스트에 노출. 현재 모드가 그 종목이면 highlight.
- 매크로 페이지로 전환 후 sidebar의 즐겨찾기 클릭 → 그 종목 dashboard로 점프.
- ★ 해제 후 dashboard 새로고침 → 즐겨찾기 리스트에서 사라짐.
- 브라우저 종료 후 viewer 재실행 → 즐겨찾기 persist 확인 (`~/.review_viewer/favorites.json` 내용 확인).

- [ ] **Step 12.6: 캐시 동작 확인**

- 같은 기간 같은 산업 multi-select 반복 클릭 → 두 번째 클릭부터 fetch가 즉시 응답(콘솔에 supabase 쿼리 로그 없음, 또는 매우 적음). 3분 후 다시 시도 시 fetch 다시 발생.

- [ ] **Step 12.7: 빈 상태**

- 데이터 없는 종목 검색 (예: 매우 최근 상장 종목) → "이 종목 다룬 in-scope 리서치가 아직 없습니다" 메시지.
- 매크로에서 존재 안 하는 산업 multi-select (자동완성에 없는 값 강제로 입력 못 함 — 통과).

- [ ] **Step 12.8: viewer 종료**

콘솔에서 Ctrl+C 또는 background process stop.

---

## Self-Review

**Spec coverage:**
- Spec §2 Goals 5개 모두 task로 분해됨 (Goal 1 → Task 8, Goal 2 → Task 8, Goal 3 → Task 9, Goal 4 → Task 4 + 10, Goal 5 → Task 10).
- Spec §5 Components (12 파일) 모두 Task 2~11에서 생성.
- Spec §6 Pages: macro Task 8, stock Task 9.
- Spec §7 Sidebar: Task 10.
- Spec §8 Data semantics (in-scope 필터, OOS toggle 정책, 발간일, 종목/산업 매칭, coverage volume, raw fetch + pagination + cache): Task 5 (집계), Task 6 (DB), Task 8 (cache 데코레이터).
- Spec §9 Favorites: Task 4.
- Spec §10 Error handling: Task 8/9/10 (UI 처리), Task 6 (pagination 중단).
- Spec §11 Testing: Task 2-7에서 단위 테스트, Task 12에서 manual smoke.
- Spec §12 Dependencies: Task 1.

**Placeholder 스캔:** "TBD"/"implement later"/"Similar to Task N" 없음. 모든 step에 실제 코드/명령. 검증 명령마다 expected output 명시.

**Type 일관성:**
- `AnalyticsConfig` 필드 4개 (Task 2) — Task 10 `_bootstrap()`에서 동일 사용.
- `AnalyticsDB` 3 메서드 (Task 6) — `fetch_inscope_rows`, `fetch_inscope_or_oos_rows`, `fetch_stock_rows`. Task 8/9의 cached wrapper에서 동일 호출.
- `aggregate` 5 함수 시그니처 (Task 5) — Task 8/9에서 동일 인자명으로 호출.
- `charts` 5 함수 (Task 7) — Task 8/9에서 동일 사용.
- `favorites.load/add/remove(path, code)` (Task 4) — Task 9/10에서 동일 사용. `FAVORITES_PATH = ~/.review_viewer/favorites.json` (Task 10).
- KRX DataFrame 컬럼 `code, name, sector` (Task 3) — Task 8 ranking에서 `merge(on='code')`, Task 9 헤더에서 `name, sector`.

OK. 모든 task 일관성 확보. 실행으로 넘어가도 됨.
