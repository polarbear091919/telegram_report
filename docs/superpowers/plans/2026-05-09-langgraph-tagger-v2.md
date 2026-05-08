# LangGraph Tagger v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v1 LangGraph tagger를 v2(KRX-driven 단순화 + 6종 report_type + IR자료 OOS + LLM raw audit)로 incremental rev하고, 기존 v1 태깅 데이터를 reset해서 v2로 재태깅한다.

**Architecture:** v1 in-scope 흐름 `canonicalize → validate → enrich → decide_status → write` (4 노드)를 `resolve_krx → decide_status → write` (2 노드)로 단순화. LLM은 stock_codes_raw / company_names_raw / publisher_canon / publisher_type / report_type 등을 한 번에 추출. KRX entry가 sectors/products의 단일 진실 공급원. report_type별로 KRX lookup 정책 분리(단일종목 1, 섹터 N, 산업·전략·시황 skip).

**Tech Stack:** Python 3.11+, LangGraph 1.0+, OpenAI Python v2.x (`client.chat.completions.parse`), Pydantic v2, asyncpg, PyMuPDF, pytest + pytest-asyncio, Supabase Postgres (transaction pooler).

**Spec:** [docs/superpowers/specs/2026-05-09-langgraph-tagger-v2-design.md](../specs/2026-05-09-langgraph-tagger-v2-design.md) (rev-7).

---

## File Structure (v2 변경 대상)

| 파일 | 변경 |
|---|---|
| `migrations/003_v2_redesign.sql` | **신규** — DROP CHECK / 모든 row reset → pending / ADD raw 컬럼·DROP topics / ADD 새 CHECK / GIN 인덱스 |
| `langgraph_tagger/vocabulary/taxonomy.yaml` | report_types 6종, oos 5종, publisher_types 4종, sector_major_aliases 삭제, precedence_rules 갱신 |
| `langgraph_tagger/vocabulary/publishers.yaml` | `해당기업: publisher_type_override: company` 라인 제거 |
| `langgraph_tagger/vocabulary/topics.yaml` | **삭제** |
| `langgraph_tagger/vocabulary/__init__.py` | `lookup_publisher`, `map_topics`, `_publishers_table`, `_topics_table` 제거 — `taxonomy()`만 유지 |
| `langgraph_tagger/vocabulary/krx.py` | `lookup_by_name` 신규, `has_product`/`rows_with_product`/`rows_with_sector_minor`/`fuzzy_sector_match`/`_build_sector_aliases` 제거 |
| `langgraph_tagger/llm_schemas.py` | LLMExtraction 축소 — stock_codes_raw, company_names_raw, publisher_canon, publisher_type, report_type(6), title, published_at, analysts, oos_signals, self_confidence, notes |
| `langgraph_tagger/state.py` | RowState 키 재정의 |
| `langgraph_tagger/prompts.py` | 6종 enum, 1~3p, publishers.yaml 본문 import-time 주입, IPO 단일종목 명시 |
| `langgraph_tagger/nodes/extract_pdf.py` | `max_pages: int = 3` (기존 5) |
| `langgraph_tagger/nodes/llm_extract.py` | 변경 없음 (스키마는 재정의된 LLMExtraction 사용) |
| `langgraph_tagger/nodes/oos_gate.py` | IR자료 → mark_oos_reason 분기 추가, "canonicalize" → "resolve_krx" 라벨 |
| `langgraph_tagger/nodes/mark_oos_reason.py` | `ir_self` 분기 추가 |
| `langgraph_tagger/nodes/status_oos.py` | high tier에 `ir_self` 추가 |
| `langgraph_tagger/nodes/canonicalize.py` | **삭제** |
| `langgraph_tagger/nodes/validate.py` | **삭제** |
| `langgraph_tagger/nodes/enrich.py` | **삭제** |
| `langgraph_tagger/nodes/resolve_krx.py` | **신규** — type-aware lookup + `_finalize`(krx 인자) |
| `langgraph_tagger/nodes/decide_status.py` | 단순화 — 단일종목+krx_unmatched / type_indeterminate / pdf_unreadable / llm_refusal 4종만 review_needed. mismatch는 medium |
| `langgraph_tagger/nodes/write.py` | 19-arg payload, OOS도 LLM의 report_type/publisher/title/analysts 보존 |
| `langgraph_tagger/supabase_io.py` | UPDATE_SQL 19개 placeholder, topics 제거, raw 추가 |
| `langgraph_tagger/graph.py` | 8 노드 wiring (canonicalize/validate/enrich 제거, resolve_krx 추가) |
| `langgraph_tagger/orchestrator.py` | review_reasons set 갱신, oos_counter에 ir_self 추가, _empty_report 갱신 |
| `langgraph_tagger/tests/conftest.py` | `make_llm_extraction` factory를 v2 schema로 갱신 |
| `langgraph_tagger/tests/test_*.py` | 변경된 노드 단위 테스트 갱신, 삭제된 노드 테스트 삭제 |
| `langgraph_tagger/tests/parity/fixtures.json` | 6종 × 5 OOS + mismatch 1개로 재작성 |

---

## Task 1: migration 003 작성 (reset + v2 schema)

**Files:**
- Create: `migrations/003_v2_redesign.sql`

- [ ] **Step 1: SQL 파일 작성**

`migrations/003_v2_redesign.sql`:

```sql
-- migrations/003_v2_redesign.sql
--
-- v2 redesign: reset all v1-tagged data and apply v2 schema (6 report_types,
-- 5 OOS reasons, 4 publisher_types, raw audit columns, topics drop).
-- See docs/superpowers/specs/2026-05-09-langgraph-tagger-v2-design.md §11.

BEGIN;

-- ============================================================
-- 1. 기존 CHECK 제약 DROP (reset에서 NULL 허용 + 새 enum value 도입에 필요)
-- ============================================================
ALTER TABLE reports DROP CONSTRAINT IF EXISTS chk_report_type;
ALTER TABLE reports DROP CONSTRAINT IF EXISTS chk_out_of_scope_reason;
ALTER TABLE reports DROP CONSTRAINT IF EXISTS chk_publisher_type;

-- ============================================================
-- 2. 모든 태깅 메타데이터를 비우고 pending 상태로 reset.
--    PDF 파일·메시지 메타(file_path, sent_at, caption 등)는 그대로 보존.
-- ============================================================
UPDATE reports SET
    published_at        = NULL,
    report_type         = NULL,
    publisher           = NULL,
    publisher_type      = NULL,
    analysts            = '{}',
    title               = NULL,
    stock_codes         = '{}',
    company_names       = '{}',
    sectors_major       = '{}',
    sectors_minor       = '{}',
    products            = '{}',
    -- topics는 step 3에서 DROP COLUMN
    out_of_scope_reason = NULL,
    tagging_status      = 'pending',
    tagging_locked_at   = NULL,
    tagging_worker_id   = NULL,
    tagger_version      = NULL,
    taxonomy_version    = NULL,
    tagging_confidence  = NULL,
    tagging_notes       = NULL,
    tagged_at           = NULL;

-- ============================================================
-- 3. 컬럼 ADD/DROP
-- ============================================================
ALTER TABLE reports
  ADD COLUMN IF NOT EXISTS stock_codes_raw   text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS company_names_raw text[] NOT NULL DEFAULT '{}';

DROP INDEX IF EXISTS ix_reports_topics_gin;
ALTER TABLE reports DROP COLUMN IF EXISTS topics;

-- ============================================================
-- 4. 새 CHECK 제약 ADD (v2 enum)
-- ============================================================
ALTER TABLE reports ADD CONSTRAINT chk_report_type CHECK (
  report_type IS NULL OR report_type IN
  ('단일종목','산업','섹터','IR자료','전략·시황','기타')
);

ALTER TABLE reports ADD CONSTRAINT chk_out_of_scope_reason CHECK (
  out_of_scope_reason IS NULL OR out_of_scope_reason IN
  ('foreign','fund','digital','private','ir_self')
);

ALTER TABLE reports ADD CONSTRAINT chk_publisher_type CHECK (
  publisher_type IS NULL OR publisher_type IN
  ('broker','data_provider','ir_agency','other')
);

-- ============================================================
-- 5. audit raw 컬럼 GIN 인덱스 (시나리오 G — KRX 미매칭 분석)
-- ============================================================
CREATE INDEX IF NOT EXISTS ix_reports_stocks_raw_gin
  ON reports USING gin (stock_codes_raw);
CREATE INDEX IF NOT EXISTS ix_reports_companies_raw_gin
  ON reports USING gin (company_names_raw);

COMMIT;
```

- [ ] **Step 2: SQL 구문 검증 (postgres syntax-only)**

Run: `python -c "import re; sql = open('migrations/003_v2_redesign.sql', encoding='utf-8').read(); assert sql.count('BEGIN;') == 1 and sql.count('COMMIT;') == 1; assert 'DROP CONSTRAINT IF EXISTS chk_report_type' in sql; print('SQL structure OK')"`
Expected: `SQL structure OK`

- [ ] **Step 3: Commit**

```bash
git add migrations/003_v2_redesign.sql
git commit -m "feat(migration): 003 v2 redesign — reset all rows, swap CHECK enums, add raw audit columns"
```

---

## Task 2: taxonomy.yaml / publishers.yaml / topics.yaml 정리

**Files:**
- Modify: `langgraph_tagger/vocabulary/taxonomy.yaml`
- Modify: `langgraph_tagger/vocabulary/publishers.yaml`
- Delete: `langgraph_tagger/vocabulary/topics.yaml`

- [ ] **Step 1: taxonomy.yaml 재작성**

`langgraph_tagger/vocabulary/taxonomy.yaml`:

```yaml
# Source-of-truth enums for langgraph_tagger v2.
# Mirrors migrations/003_v2_redesign.sql CHECK constraints
# (6 report_types, 5 oos_reasons, 4 publisher_types).

report_types:
  - 단일종목
  - 산업
  - 섹터
  - IR자료
  - 전략·시황
  - 기타

oos_reasons: [foreign, fund, digital, private, ir_self]
publisher_types: [broker, data_provider, ir_agency, other]
tagging_statuses: [pending, processing, auto, review_needed, verified]
tagging_confidences: [high, medium, low]

# Reference-only: precedence rules (codes implement these in oos_gate / decide_status / resolve_krx)
precedence_rules:
  - "OOS patterns override all other classification (foreign/fund/digital/private)"
  - "report_type='IR자료' → automatic OOS ir_self (separate branch in oos_gate)"
  - "단일종목 + KRX unmatched → review_needed (IPO pending or unknown)"
  - "산업/전략·시황 → KRX lookup skipped (entry == None is normal)"
  - "섹터 → KRX lookup over all stock_codes_raw + company_names_raw, union sectors/products"
  - "단일종목 stock_code matched but company name not in raw → krx_name_code_mismatch (auto/medium)"
```

- [ ] **Step 2: publishers.yaml의 `해당기업: publisher_type_override: company` 라인 제거**

`langgraph_tagger/vocabulary/publishers.yaml`의 `other:` 섹션에서 `해당기업` 항목을 다음과 같이 변경 (line 91-94):

```yaml
other:
  - canonical: 해당기업
    aliases: []
  - canonical: KRX
    aliases: ["한국거래소"]
```

(`publisher_type_override: company` 라인을 제거. `해당기업`은 'other' 섹션 안에 있으므로 자동으로 publisher_type='other'로 결정됨.)

- [ ] **Step 3: topics.yaml 삭제**

```bash
git rm langgraph_tagger/vocabulary/topics.yaml
```

- [ ] **Step 4: Commit**

```bash
git add langgraph_tagger/vocabulary/taxonomy.yaml langgraph_tagger/vocabulary/publishers.yaml
git commit -m "refactor(vocabulary): v2 — 6 report_types, 5 oos, 4 publisher_types, drop topics.yaml + 해당기업 override"
```

---

## Task 3: vocabulary/__init__.py 슬림화

**Files:**
- Modify: `langgraph_tagger/vocabulary/__init__.py`
- Modify: `langgraph_tagger/tests/test_vocabulary.py`

- [ ] **Step 1: 기존 테스트가 새 동작으로 실패하는지 확인하기 위해 테스트부터 갱신**

`langgraph_tagger/tests/test_vocabulary.py`:

```python
"""Test taxonomy() — only public API in v2."""
from langgraph_tagger.vocabulary import taxonomy


def test_taxonomy_has_six_report_types():
    tax = taxonomy()
    assert tax["report_types"] == [
        "단일종목", "산업", "섹터", "IR자료", "전략·시황", "기타",
    ]


def test_taxonomy_oos_reasons_includes_ir_self():
    assert "ir_self" in taxonomy()["oos_reasons"]
    assert taxonomy()["oos_reasons"] == [
        "foreign", "fund", "digital", "private", "ir_self",
    ]


def test_taxonomy_publisher_types_drops_company():
    pt = taxonomy()["publisher_types"]
    assert "company" not in pt
    assert pt == ["broker", "data_provider", "ir_agency", "other"]


def test_lookup_publisher_no_longer_exported():
    import langgraph_tagger.vocabulary as v
    assert not hasattr(v, "lookup_publisher")
    assert not hasattr(v, "map_topics")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest langgraph_tagger/tests/test_vocabulary.py -v`
Expected: 4 tests fail — `test_taxonomy_has_six_report_types` (현재 14종), `test_taxonomy_publisher_types_drops_company` (현재 5종), `test_lookup_publisher_no_longer_exported` (현재 import됨), `test_taxonomy_oos_reasons_includes_ir_self` (현재 4종).

- [ ] **Step 3: vocabulary/__init__.py 재작성**

`langgraph_tagger/vocabulary/__init__.py`:

```python
"""Vocabulary lookup (v2: taxonomy only — publisher canon은 LLM이 직접 출력).

topics.yaml은 삭제됨. publishers.yaml은 prompts.py가 본문 그대로 LLM에게 주입.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_VOCAB_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def _taxonomy() -> dict:
    return yaml.safe_load((_VOCAB_DIR / "taxonomy.yaml").read_text(encoding="utf-8"))


def taxonomy() -> dict:
    """Returns the loaded taxonomy.yaml content (used by prompts and tests)."""
    return _taxonomy()


__all__ = ["taxonomy"]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_vocabulary.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add langgraph_tagger/vocabulary/__init__.py langgraph_tagger/tests/test_vocabulary.py
git commit -m "refactor(vocabulary): v2 — drop lookup_publisher and map_topics, expose only taxonomy()"
```

---

## Task 4: vocabulary/krx.py — `lookup_by_name` 추가, 미사용 메서드 제거

**Files:**
- Modify: `langgraph_tagger/vocabulary/krx.py`
- Modify: `langgraph_tagger/tests/test_krx.py`

- [ ] **Step 1: 신규 메서드 테스트 추가**

`langgraph_tagger/tests/test_krx.py`에 다음 테스트 추가 (기존 테스트 중 `has_product`, `rows_with_product`, `rows_with_sector_minor`, `fuzzy_sector_match` 관련 테스트는 모두 삭제):

```python
def test_lookup_by_name_exact_match(krx):
    e = krx.lookup_by_name("삼성전자")
    assert e is not None
    assert e.code == "005930"


def test_lookup_by_name_whitespace_insensitive(krx):
    e = krx.lookup_by_name("삼성 전자")
    assert e is not None
    assert e.code == "005930"


def test_lookup_by_name_case_insensitive(krx):
    # KRX 영문 종목명이 있는 경우 — case-insensitive 매칭
    # 실제 KRX CSV에서 이름이 영문/한글 혼용인 case가 있다면 그걸 검증.
    # 없다면 한글 case로 only.
    e = krx.lookup_by_name("Samsung Electronics")  # KRX has 한글; should miss
    assert e is None  # KRX CSV는 한글 표기이므로 영문은 미매칭이 정상


def test_lookup_by_name_unknown_returns_none(krx):
    assert krx.lookup_by_name("존재하지않는회사") is None


def test_has_product_removed(krx):
    assert not hasattr(krx, "has_product")
    assert not hasattr(krx, "rows_with_product")
    assert not hasattr(krx, "rows_with_sector_minor")
    assert not hasattr(krx, "fuzzy_sector_match")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest langgraph_tagger/tests/test_krx.py -v`
Expected: 신규 테스트 5개 중 `test_lookup_by_name_*` 4개는 `AttributeError: 'KRXIndex' object has no attribute 'lookup_by_name'`로 fail. `test_has_product_removed`도 fail (현재 v1에 메서드들이 존재).

- [ ] **Step 3: krx.py 재작성**

`langgraph_tagger/vocabulary/krx.py`:

```python
"""KRX listed-stock index: loaded once from CSV, used for v2 resolve_krx node.

Headers (after normalization): 종목코드, 종목명, 시장, 산업명(대), 산업명(중), 주요제품
The first header cell is '종목\\n코드' in the file (multi-line). We strip newlines on load.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


@dataclass(frozen=True)
class KRXEntry:
    code: str
    name: str
    market: str           # KOSPI / KOSDAQ / KOSDAQ GLOBAL
    sector_major: str
    sector_minor: str
    products_text: str    # free text


def _normalize_name(s: str) -> str:
    """Whitespace+case insensitive key for company-name fuzzy match."""
    return "".join(s.split()).lower()


class KRXIndex:
    def __init__(self, entries: list[KRXEntry], csv_path: Path) -> None:
        self.by_code: dict[str, KRXEntry] = {e.code: e for e in entries}
        self.taxonomy_version: str = self._build_version(csv_path)
        # Pre-built name index for lookup_by_name
        self._by_name: dict[str, KRXEntry] = {}
        for e in entries:
            key = _normalize_name(e.name)
            # First-match wins on collision (rare; KRX names are unique)
            self._by_name.setdefault(key, e)

    @classmethod
    def load(cls, csv_path: Path) -> "KRXIndex":
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = [c.replace("\r", "").replace("\n", "").strip() for c in next(reader)]
            expected = ["종목코드", "종목명", "시장", "산업명(대)", "산업명(중)", "주요제품"]
            if header != expected:
                raise ValueError(f"unexpected KRX CSV header: {header} != {expected}")
            entries = []
            for row in reader:
                if len(row) < 6:
                    continue
                entries.append(KRXEntry(
                    code=row[0].strip(),
                    name=row[1].strip(),
                    market=row[2].strip(),
                    sector_major=row[3].strip(),
                    sector_minor=row[4].strip(),
                    products_text=row[5].strip(),
                ))
        return cls(entries, csv_path)

    def validate_code(self, code: str) -> bool:
        return bool(_CODE_RE.fullmatch(code)) and code in self.by_code

    def lookup(self, code: str) -> Optional[KRXEntry]:
        return self.by_code.get(code)

    def lookup_by_name(self, name: str) -> Optional[KRXEntry]:
        """Fuzzy company-name lookup (whitespace+case insensitive). None on miss."""
        if not name:
            return None
        return self._by_name.get(_normalize_name(name))

    def split_products(self, products_text: str) -> list[str]:
        """ "MLCC, 기판, 카메라 모듈 등" → ['MLCC', '기판', '카메라 모듈']
            "DRAM, NAND 등"           → ['DRAM', 'NAND']

        Trailing ' 등' 접미사도 제거해야 한다 — KRX CSV에서 마지막 토큰이
        "X 등" 형태인 경우가 빈번 (예: "DRAM, NAND 등").
        """
        out: list[str] = []
        for token in products_text.split(","):
            t = token.strip()
            if t.endswith(" 등"):
                t = t[:-2].strip()
            if not t or t == "등":
                continue
            out.append(t)
        return out

    @staticmethod
    def _build_version(csv_path: Path) -> str:
        ts = datetime.fromtimestamp(csv_path.stat().st_mtime)
        return f"KRX@{ts:%Y-%m-%d}"
```

- [ ] **Step 4: 테스트 통과 확인 + 다른 의존 테스트가 깨졌는지 확인**

Run: `pytest langgraph_tagger/tests/test_krx.py -v`
Expected: 모든 신규 테스트 통과.

Run: `pytest langgraph_tagger/tests/ -v --no-header 2>&1 | grep -E '(FAIL|ERROR)' | head -20`
Expected: `test_validate.py`, `test_enrich.py` 등이 `has_product`, `rows_with_product` 등 미존재로 fail. 이건 다음 task에서 해당 노드들을 삭제하면서 해결됨.

- [ ] **Step 5: Commit**

```bash
git add langgraph_tagger/vocabulary/krx.py langgraph_tagger/tests/test_krx.py
git commit -m "refactor(krx): v2 — add lookup_by_name, drop has_product/rows_with_product/fuzzy_sector_match"
```

---

## Task 5: llm_schemas.py + state.py 재정의

**Files:**
- Modify: `langgraph_tagger/llm_schemas.py`
- Modify: `langgraph_tagger/state.py`
- Modify: `langgraph_tagger/tests/conftest.py` (`make_llm_extraction` factory v2 schema)

- [ ] **Step 1: llm_schemas.py 재작성**

`langgraph_tagger/llm_schemas.py`:

```python
"""Pydantic schema for the OpenAI structured-output call (v2).

v2 변경 (rev-7):
- report_type 14종 → 6종
- sectors_major/minor, products, topics, company_names, publisher_raw 제거
- stock_codes_raw, company_names_raw 추가 (raw audit)
- publisher_canon, publisher_type 직접 출력 (LLM이 publishers.yaml 보고 매핑)
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from typing_extensions import Literal

REPORT_TYPES = Literal[
    "단일종목", "산업", "섹터", "IR자료", "전략·시황", "기타",
]

PUBLISHER_TYPES = Literal[
    "broker", "data_provider", "ir_agency", "other",
]


class OOSSignals(BaseModel):
    """LLM-observed primary-coverage signals."""
    foreign_primary_coverage: bool = Field(
        description="**리포트의 primary coverage가 해외 상장사**일 때만 true. "
                    "국내 종목/산업 리포트가 외국 티커를 peer/벨류체인/수요처로 "
                    "단순 언급하는 경우는 false."
    )
    etf_or_fund: bool = Field(
        description="ETF 라인업 / 펀드평가 / 펀드비교 (primary coverage가 펀드/ETF)"
    )
    digital_asset: bool = Field(
        description="가상자산·디지털자산·BTC·ETH·코인 (primary coverage가 디지털자산)"
    )
    private_company_likely: bool = Field(
        description="명백한 비상장/장외 컨텍스트 (000000 코드, '비상장 분석' 표기 등). "
                    "IR자료/IPO/KRX-매칭 케이스는 false (별도 분기 처리)."
    )
    # ir_self는 LLM signal로 안 둠 — report_type='IR자료'에서 자동 결정


class LLMExtraction(BaseModel):
    """All fields the LLM populates in one structured-output call (v2)."""
    report_type: REPORT_TYPES
    title: Optional[str] = Field(default=None, max_length=120)
    published_at: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD or null if not present on first page"
    )

    stock_codes_raw: list[str] = Field(
        default_factory=list,
        description="첫 페이지 헤더의 KRX 6자리 코드 (영문 포함). 본문 등장 종목은 추출 안 함."
    )
    company_names_raw: list[str] = Field(
        default_factory=list,
        description="회사명 후보 raw. 시스템이 KRX로 정규화 또는 audit으로 보존."
    )

    publisher_canon: Optional[str] = Field(
        default=None,
        description="publishers.yaml의 canonical 형태로 정규화한 발행 주체. 매칭 안 되면 null."
    )
    publisher_type: Optional[PUBLISHER_TYPES] = Field(
        default=None,
        description="publisher_canon이 set되면 함께 결정. 매칭 안 되면 null."
    )

    analysts: list[str] = Field(default_factory=list)

    oos_signals: OOSSignals
    self_confidence: Literal["high", "medium", "low"] = Field(
        description="LLM이 자체 판단한 추출 신뢰도"
    )
    notes: Optional[str] = Field(
        default=None, max_length=200,
        description="모호함·특이사항 메모 (한 줄)"
    )
```

- [ ] **Step 2: state.py 재작성**

`langgraph_tagger/state.py`:

```python
"""LangGraph row-graph state (v2).

TypedDict with all keys total=False — each node sets only the keys it owns.
v2 변경 (rev-7):
- canonicalize/validate 단계 키 제거 (해당 노드 삭제)
- enrich 출력 → resolve_krx로 통합 + krx_lookup_skipped/krx_entries/krx_name_code_mismatch 추가
- oos_reason Literal에 ir_self 추가
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from typing_extensions import Literal, TypedDict

from langgraph_tagger.llm_schemas import LLMExtraction
from langgraph_tagger.vocabulary.krx import KRXEntry


class RowState(TypedDict, total=False):
    # Input (populated at claim time)
    id: int
    file_path: str
    file_name: str
    sent_at: datetime
    caption: Optional[str]
    chat_username: str
    worker_id: str
    model: str

    # extract_pdf output
    pdf_text: str
    pages_used: list[int]
    pdf_unreadable: bool

    # llm_extract output
    llm_raw: Optional[LLMExtraction]
    llm_refusal: Optional[str]

    # oos_gate / mark_oos_reason output
    is_oos: bool
    oos_reason: Optional[Literal["foreign", "fund", "digital", "private", "ir_self"]]

    # resolve_krx output (v1 canonicalize+validate+enrich 통합)
    krx_lookup_skipped: bool       # 산업/전략·시황은 True
    krx_matched: bool              # 매칭 entry가 1개 이상 존재
    krx_entries: list[KRXEntry]    # 단일종목=0~1, 섹터=0~N, 산업/전략·시황=[]
    krx_name_code_mismatch: bool   # 단일종목 + stock_code 매칭이지만 entry.name이 raw에 없음
    stock_codes_final: list[str]
    company_names_final: list[str]
    sectors_major_final: list[str]
    sectors_minor_final: list[str]
    products_final: list[str]
    published_at_final: Optional[date]
    used_sent_at_fallback: bool

    # decide_status / status_oos / status_unreadable output
    tagging_status: Literal["auto", "review_needed"]
    tagging_confidence: Literal["high", "medium", "low"]
    tagging_notes: Optional[str]
```

- [ ] **Step 3: conftest.py의 `make_llm_extraction` factory를 v2 schema로 갱신**

`langgraph_tagger/tests/conftest.py`의 `make_llm_extraction` 함수를 다음으로 교체 (defaults 부분만):

```python
def make_llm_extraction(**overrides) -> LLMExtraction:
    """Factory for tests — v2 sane defaults overridable per test."""
    defaults = dict(
        report_type="단일종목",
        title="삼성전자 1Q26 Preview",
        published_at="2026-05-01",
        stock_codes_raw=["005930"],
        company_names_raw=["삼성전자"],
        publisher_canon="키움증권",
        publisher_type="broker",
        analysts=["홍길동"],
        oos_signals=OOSSignals(
            foreign_primary_coverage=False, etf_or_fund=False,
            digital_asset=False, private_company_likely=False,
        ),
        self_confidence="high",
        notes=None,
    )
    defaults.update(overrides)
    return LLMExtraction(**defaults)
```

- [ ] **Step 4: import 검증**

Run: `python -c "from langgraph_tagger.llm_schemas import LLMExtraction, OOSSignals, REPORT_TYPES; from langgraph_tagger.state import RowState; from langgraph_tagger.tests.conftest import make_llm_extraction; e = make_llm_extraction(); print(e.report_type, e.publisher_canon)"`
Expected: `단일종목 키움증권`

- [ ] **Step 5: Commit**

```bash
git add langgraph_tagger/llm_schemas.py langgraph_tagger/state.py langgraph_tagger/tests/conftest.py
git commit -m "refactor(schemas): v2 LLMExtraction (6 types, raw audit) + RowState (krx_entries, mismatch)"
```

---

## Task 6: prompts.py — 6종 enum + publishers.yaml 본문 주입

**Files:**
- Modify: `langgraph_tagger/prompts.py`

- [ ] **Step 1: prompts.py 재작성**

`langgraph_tagger/prompts.py`:

```python
"""SYSTEM_PROMPT for the llm_extract node (v2).

v2 변경 (rev-7):
- 6종 report_types
- publishers.yaml 본문 import-time 주입 → LLM이 직접 publisher_canon 매핑
- stock_codes_raw / company_names_raw raw 추출만
- sectors/products/topics 추출 폐기 (KRX entry가 답지)
- 단일종목 정의에 IPO 예정 명시 (KRX 미매칭 시 review_needed로 자연 분기)
"""
from __future__ import annotations

from pathlib import Path

from langgraph_tagger.vocabulary import taxonomy

_TAX = taxonomy()
_REPORT_TYPES = ", ".join(_TAX["report_types"])

# publishers.yaml 본문을 import-time 1회 read해서 prompt에 박는다.
_PUBLISHERS_YAML = (
    Path(__file__).parent / "vocabulary" / "publishers.yaml"
).read_text(encoding="utf-8")


SYSTEM_PROMPT = f"""너는 한국 주식 리서치 PDF의 첫 1~3페이지를 보고 메타데이터를 추출하는 전문가다.
출력은 정의된 JSON schema를 정확히 따른다.

## report_type (6종)

{_REPORT_TYPES}

각 type 정의:
- 단일종목: 한 KRX 상장사 개별 분석. stock_codes_raw에 6자리 코드, company_names_raw에 회사명 1개.
  → IPO 예정/상장예정 종목 분석도 단일종목으로 분류 (KRX에 코드 없을 수 있음. 시스템이 미매칭 시 review_needed로 분기). 비상장 분석이 명확하면 단일종목이 아닌 private_company_likely=true로 OOS 처리.
- 산업: 산업(대) 단위 분석. stock_codes_raw 비움, company_names_raw 비움.
- 섹터: 좁은 섹터/테마. stock_codes_raw/company_names_raw는 0~수개. 본문에 명시적으로 등장한 KRX 6자리 코드/회사명만 포함 (peer reference로 한두 개 흘리는 종목은 제외).
- IR자료: 발행 주체 = 해당기업 자체 (자체 IR 발표자료). 분석 타겟 외이므로 자동 OOS 처리됨.
  → stock_codes_raw/company_names_raw에 회사 정보를 추출 (audit용으로 보존됨).
  → publisher_canon은 publishers vocabulary의 'other' 섹션 `해당기업` 항목으로 매칭 (publisher_type='other').
- 전략·시황: 시황·데일리·매크로·퀀트·전략·테마를 모두 포함. 자산배분/톱다운 의견 포함. stock_codes_raw/company_names_raw는 비움 (회사 한두 개 peer 언급은 제외).
- 기타: 위에 안 들어가는 것 + OOS (해외/펀드/디지털/비상장 분석).

## OOS 신호 (oos_signals) — primary coverage 중심

**리포트의 primary coverage**(주된 분석 대상)가 무엇인지를 보고 판단.
국내 종목/산업 리포트가 외국 종목을 peer로 단순 언급하는 경우는 모두 false.

- foreign_primary_coverage: primary coverage가 해외 상장사 (DG/NFLX/AAPL/BABA 등)
- etf_or_fund: primary coverage가 ETF/펀드
- digital_asset: primary coverage가 디지털자산
- private_company_likely: 명백한 비상장/장외 컨텍스트 (000000 코드, "비상장 분석"). IR자료는 별도 처리되니 false.

(IR자료 OOS는 report_type='IR자료'로 자동 결정. LLM이 별도 boolean을 set할 필요 없음.)

## publisher 매핑 — 아래 vocabulary 보고 직접 정규화

다음 publishers vocabulary를 참고해서 publisher_canon과 publisher_type을 직접 출력.
PDF에서 발견한 발행 주체가 vocabulary 안에 있으면 (영문/한글/별칭 어떤 형태든):
  → canonical 표기로 publisher_canon 출력 + publisher_type도 함께
vocabulary 안에 없으면:
  → publisher_canon=null, publisher_type=null

publishers vocabulary:
{_PUBLISHERS_YAML}

## stock_codes / company_names — raw 추출만

- stock_codes_raw: 첫 페이지 헤더의 KRX 6자리 코드 (영문 포함, ^[0-9A-Z]{{6}}$). 본문 등장 종목은 추출 안 함 (보수).
- company_names_raw: 회사명 raw 그대로. 정규화 안 함 (시스템이 KRX로 통일).

## 그 외

- title: ≤120자.
- published_at: YYYY-MM-DD 또는 null.
- analysts: 첫 페이지 명시된 애널리스트만 (없으면 빈 배열).
- self_confidence: high/medium/low (분류 결정 자신도).
- notes: 한 줄 (200자 이내), 모호함·특이사항.

출력은 정의된 JSON schema를 정확히 따른다.
"""


def user_message(*, file_name: str, caption: str | None, sent_at_iso: str, pdf_text: str) -> str:
    """Build the user message for llm_extract."""
    cap = caption if caption else "(없음)"
    return (
        f"파일명: {file_name}\n"
        f"caption: {cap}\n"
        f"sent_at (UTC): {sent_at_iso}\n"
        f"PDF 첫 페이지(들):\n"
        f"---\n"
        f"{pdf_text}\n"
        f"---"
    )
```

- [ ] **Step 2: import 검증 + 본문 길이 sanity check**

Run: `python -c "from langgraph_tagger.prompts import SYSTEM_PROMPT; assert '6종' in SYSTEM_PROMPT; assert '해당기업' in SYSTEM_PROMPT; assert 'topics' not in SYSTEM_PROMPT; assert 'sectors_major' not in SYSTEM_PROMPT.split('publishers vocabulary:')[0]; print(f'prompt {len(SYSTEM_PROMPT)} chars')"`
Expected: `prompt N chars` (대략 4000~6000자).

- [ ] **Step 3: Commit**

```bash
git add langgraph_tagger/prompts.py
git commit -m "refactor(prompts): v2 — 6 report_types, publishers.yaml inlined, IPO pending classified as 단일종목"
```

---

## Task 7: extract_pdf.py — max_pages 5 → 3

**Files:**
- Modify: `langgraph_tagger/nodes/extract_pdf.py`
- Modify: `langgraph_tagger/tests/test_extract_pdf.py`

- [ ] **Step 1: 테스트 갱신 — max_pages=3 검증 추가**

`langgraph_tagger/tests/test_extract_pdf.py`에 다음 테스트 추가 (기존 max_pages=5 가정 테스트가 있다면 함께 갱신):

```python
def test_extract_pdf_max_pages_is_3(monkeypatch, tmp_path):
    """v2: max_pages는 3 (기존 v1의 5에서 축소)."""
    import fitz
    from langgraph_tagger.nodes.extract_pdf import _sync_extract

    pdf = tmp_path / "five_pages.pdf"
    doc = fitz.open()
    for i in range(5):
        # Insert non-meta text so _has_meta_signals() never triggers early stop
        doc.new_page().insert_text((72, 72), f"page-{i+1}-content", fontsize=11)
    doc.save(pdf)
    doc.close()

    out = _sync_extract(pdf)  # uses default max_pages
    # v2: should stop at 3
    assert out["pages_used"] == [1, 2, 3]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest langgraph_tagger/tests/test_extract_pdf.py::test_extract_pdf_max_pages_is_3 -v`
Expected: FAIL — `pages_used == [1,2,3,4,5]` (현재 default max_pages=5).

- [ ] **Step 3: extract_pdf.py 변경**

`langgraph_tagger/nodes/extract_pdf.py`의 `_sync_extract` 시그니처를 변경:

```python
def _sync_extract(path: Path, max_pages: int = 3) -> dict:
```

(v1: `max_pages: int = 5` → v2: `max_pages: int = 3`)

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_extract_pdf.py -v`
Expected: 모두 통과.

- [ ] **Step 5: Commit**

```bash
git add langgraph_tagger/nodes/extract_pdf.py langgraph_tagger/tests/test_extract_pdf.py
git commit -m "refactor(extract_pdf): v2 — max_pages 5 → 3 (per spec rev-7)"
```

---

## Task 8: oos_gate.py + mark_oos_reason.py — IR자료 분기 + ir_self

**Files:**
- Modify: `langgraph_tagger/nodes/oos_gate.py`
- Modify: `langgraph_tagger/nodes/mark_oos_reason.py`
- Modify: `langgraph_tagger/tests/test_oos_gate.py`
- Modify: `langgraph_tagger/tests/test_mark_oos_reason.py`

- [ ] **Step 1: oos_gate 테스트 갱신**

`langgraph_tagger/tests/test_oos_gate.py`의 기존 테스트를 다음 v2 정책에 맞춰 갱신:
- 모든 라벨 `"canonicalize"`를 `"resolve_krx"`로 교체
- IR자료 분기 테스트 추가:

```python
def test_ir_material_routes_to_mark_oos_reason(krx):
    from langgraph_tagger.nodes.oos_gate import oos_gate
    from langgraph_tagger.tests.conftest import make_llm_extraction

    raw = make_llm_extraction(
        report_type="IR자료",
        publisher_canon="해당기업",
        publisher_type="other",
        stock_codes_raw=[],
        company_names_raw=["비상장기업명"],
    )
    state = {"llm_raw": raw, "pdf_unreadable": False, "llm_refusal": None}
    assert oos_gate(state, krx=krx) == "mark_oos_reason"


def test_ipo_no_longer_in_enum_so_no_special_branch(krx):
    """v2: IPO는 enum에서 제거됨 (단일종목으로 통합). private_company_likely 분기에 IPO 예외 없음."""
    from langgraph_tagger.nodes.oos_gate import oos_gate
    from langgraph_tagger.tests.conftest import make_llm_extraction
    from langgraph_tagger.llm_schemas import OOSSignals

    raw = make_llm_extraction(
        report_type="단일종목",
        stock_codes_raw=[],  # KRX unmatched
        company_names_raw=["미상장IPO후보"],
        oos_signals=OOSSignals(
            foreign_primary_coverage=False, etf_or_fund=False,
            digital_asset=False, private_company_likely=True,
        ),
    )
    state = {"llm_raw": raw, "pdf_unreadable": False, "llm_refusal": None}
    # private + KRX unmatched + 단일종목 → OOS private (IPO 예외 없음)
    assert oos_gate(state, krx=krx) == "mark_oos_reason"
```

- [ ] **Step 2: oos_gate.py 재작성**

`langgraph_tagger/nodes/oos_gate.py`:

```python
"""oos_gate: 3-way LangGraph routing function (v2).

v2 변경 (rev-7):
- IR자료 분기 추가 → 자동 OOS ir_self
- "canonicalize" 라벨 → "resolve_krx"
- IPO 예외 제거 (IPO enum 자체가 사라짐 — 6종에 IPO 없음)

LangGraph 1.0 contract: routing functions for ``add_conditional_edges`` MUST
return a string label only and MUST NOT mutate state. State mutation for OOS
classification lives in ``mark_oos_reason``.
"""
from __future__ import annotations

from typing import Literal

from langgraph_tagger.state import RowState
from langgraph_tagger.vocabulary.krx import KRXIndex


def oos_gate(state: RowState, *, krx: KRXIndex) -> Literal[
    "mark_oos_reason", "status_unreadable", "resolve_krx"
]:
    if state.get("pdf_unreadable") or state.get("llm_refusal"):
        return "status_unreadable"

    raw = state.get("llm_raw")
    if raw is None:
        return "status_unreadable"

    # v2: IR자료 = 자동 OOS ir_self (mark_oos_reason에서 reason 결정)
    if raw.report_type == "IR자료":
        return "mark_oos_reason"

    sig = raw.oos_signals
    if sig.foreign_primary_coverage or sig.etf_or_fund or sig.digital_asset:
        return "mark_oos_reason"

    if sig.private_company_likely:
        # 명백한 비상장 컨텍스트: KRX 매칭 시 in-scope (예: 0008Z0 SPAC), 미매칭 시 OOS private.
        # IPO 예외는 v2에서 제거됨 (IPO enum 자체가 사라짐).
        if any(krx.validate_code(c) for c in raw.stock_codes_raw):
            return "resolve_krx"
        return "mark_oos_reason"

    return "resolve_krx"
```

- [ ] **Step 3: mark_oos_reason 테스트 갱신**

`langgraph_tagger/tests/test_mark_oos_reason.py`에 IR자료 → ir_self 케이스 추가:

```python
def test_ir_material_yields_ir_self_reason():
    from langgraph_tagger.nodes.mark_oos_reason import mark_oos_reason
    from langgraph_tagger.tests.conftest import make_llm_extraction

    raw = make_llm_extraction(
        report_type="IR자료",
        publisher_canon="해당기업",
        publisher_type="other",
    )
    out = mark_oos_reason({"llm_raw": raw})
    assert out == {"is_oos": True, "oos_reason": "ir_self"}
```

- [ ] **Step 4: mark_oos_reason.py 재작성**

`langgraph_tagger/nodes/mark_oos_reason.py`:

```python
"""mark_oos_reason node: sets is_oos + oos_reason from LLM signals + IR자료 (v2).

oos_gate (routing function) ensures we only enter this node when:
  - report_type == 'IR자료' (자동 OOS ir_self), or
  - one of foreign/fund/digital signals is true, or
  - private_company_likely + KRX-unmatched (no IPO exception in v2).
"""
from __future__ import annotations

from langgraph_tagger.state import RowState


def mark_oos_reason(state: RowState) -> dict:
    raw = state["llm_raw"]
    # IR자료 우선 — 사용자 의도 (분석 타겟 외)
    if raw.report_type == "IR자료":
        return {"is_oos": True, "oos_reason": "ir_self"}
    sig = raw.oos_signals
    if sig.foreign_primary_coverage:
        return {"is_oos": True, "oos_reason": "foreign"}
    if sig.etf_or_fund:
        return {"is_oos": True, "oos_reason": "fund"}
    if sig.digital_asset:
        return {"is_oos": True, "oos_reason": "digital"}
    return {"is_oos": True, "oos_reason": "private"}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_oos_gate.py langgraph_tagger/tests/test_mark_oos_reason.py -v`
Expected: 모두 통과.

- [ ] **Step 6: Commit**

```bash
git add langgraph_tagger/nodes/oos_gate.py langgraph_tagger/nodes/mark_oos_reason.py langgraph_tagger/tests/test_oos_gate.py langgraph_tagger/tests/test_mark_oos_reason.py
git commit -m "feat(oos): v2 — IR자료 → ir_self auto-OOS, drop IPO exception, rename canonicalize→resolve_krx label"
```

---

## Task 9: status_oos.py — high tier에 ir_self 추가

**Files:**
- Modify: `langgraph_tagger/nodes/status_oos.py`
- Modify: `langgraph_tagger/tests/test_status_oos.py`

- [ ] **Step 1: 테스트 추가**

`langgraph_tagger/tests/test_status_oos.py`에 추가:

```python
def test_ir_self_is_high_confidence():
    from langgraph_tagger.nodes.status_oos import status_oos

    out = status_oos({"oos_reason": "ir_self"})
    assert out == {
        "is_oos": True,
        "tagging_status": "auto",
        "tagging_confidence": "high",
        "tagging_notes": None,
    }


def test_private_remains_medium():
    from langgraph_tagger.nodes.status_oos import status_oos

    out = status_oos({"oos_reason": "private"})
    assert out["tagging_confidence"] == "medium"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest langgraph_tagger/tests/test_status_oos.py::test_ir_self_is_high_confidence -v`
Expected: FAIL — 현재 ir_self는 `else` 가지로 빠져 medium.

- [ ] **Step 3: status_oos.py 변경**

`langgraph_tagger/nodes/status_oos.py`:

```python
"""status_oos node: OOS rows get auto status + reason-derived confidence (v2)."""
from langgraph_tagger.state import RowState


def status_oos(state: RowState) -> dict:
    reason = state["oos_reason"]
    confidence = "high" if reason in ("foreign", "fund", "digital", "ir_self") else "medium"
    return {
        "is_oos": True,
        "tagging_status": "auto",
        "tagging_confidence": confidence,
        "tagging_notes": None,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_status_oos.py -v`
Expected: 모두 통과.

- [ ] **Step 5: Commit**

```bash
git add langgraph_tagger/nodes/status_oos.py langgraph_tagger/tests/test_status_oos.py
git commit -m "feat(status_oos): v2 — ir_self confidence=high (private only stays medium)"
```

---

## Task 10: resolve_krx.py 신규 + canonicalize/validate/enrich 삭제

**Files:**
- Create: `langgraph_tagger/nodes/resolve_krx.py`
- Create: `langgraph_tagger/tests/test_resolve_krx.py`
- Delete: `langgraph_tagger/nodes/canonicalize.py`
- Delete: `langgraph_tagger/nodes/validate.py`
- Delete: `langgraph_tagger/nodes/enrich.py`
- Delete: `langgraph_tagger/tests/test_canonicalize.py`
- Delete: `langgraph_tagger/tests/test_validate.py`
- Delete: `langgraph_tagger/tests/test_enrich.py`

- [ ] **Step 1: resolve_krx 테스트 작성**

`langgraph_tagger/tests/test_resolve_krx.py`:

```python
"""Test resolve_krx — v2 type-aware KRX lookup."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from langgraph_tagger.llm_schemas import OOSSignals
from langgraph_tagger.nodes.resolve_krx import resolve_krx
from langgraph_tagger.tests.conftest import make_llm_extraction


def _state(raw, sent_at_iso="2026-05-01T00:00:00+00:00"):
    return {"llm_raw": raw, "sent_at": datetime.fromisoformat(sent_at_iso)}


def test_단일종목_stock_code_match(krx):
    raw = make_llm_extraction(
        report_type="단일종목",
        stock_codes_raw=["005930"],
        company_names_raw=["삼성전자"],
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["krx_lookup_skipped"] is False
    assert out["krx_matched"] is True
    assert out["stock_codes_final"] == ["005930"]
    assert out["company_names_final"] == ["삼성전자"]
    assert out["sectors_major_final"]   # KRX entry has it
    assert out["krx_name_code_mismatch"] is False


def test_단일종목_name_fallback_when_code_missing(krx):
    raw = make_llm_extraction(
        report_type="단일종목",
        stock_codes_raw=[],
        company_names_raw=["삼성전자"],
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["krx_matched"] is True
    assert out["stock_codes_final"] == ["005930"]
    # name_code_mismatch는 stock_code 매칭이 성공한 케이스에만 검사 — 여기는 False
    assert out["krx_name_code_mismatch"] is False


def test_단일종목_unmatched_returns_raw_fallback(krx):
    raw = make_llm_extraction(
        report_type="단일종목",
        stock_codes_raw=["999999"],     # invalid
        company_names_raw=["미상장IPO후보"],
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["krx_matched"] is False
    assert out["stock_codes_final"] == []
    assert out["company_names_final"] == ["미상장IPO후보"]   # raw fallback
    assert out["sectors_major_final"] == []


def test_단일종목_name_code_mismatch_detected(krx):
    """stock_code → 삼성전자, 그러나 raw 회사명에 다른 회사가 있으면 mismatch."""
    raw = make_llm_extraction(
        report_type="단일종목",
        stock_codes_raw=["005930"],         # 삼성전자
        company_names_raw=["SK하이닉스"],     # mismatch
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["krx_matched"] is True
    assert out["company_names_final"] == ["삼성전자"]   # KRX 정식
    assert out["krx_name_code_mismatch"] is True


def test_산업_skips_lookup(krx):
    raw = make_llm_extraction(
        report_type="산업",
        stock_codes_raw=[],
        company_names_raw=[],
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["krx_lookup_skipped"] is True
    assert out["krx_matched"] is False
    assert out["krx_entries"] == []
    assert out["sectors_major_final"] == []


def test_전략시황_skips_lookup(krx):
    raw = make_llm_extraction(
        report_type="전략·시황",
        stock_codes_raw=[],
        company_names_raw=[],
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["krx_lookup_skipped"] is True
    assert out["krx_matched"] is False


def test_섹터_aggregates_n_entries(krx):
    raw = make_llm_extraction(
        report_type="섹터",
        stock_codes_raw=["005930", "000660"],   # 삼성전자, SK하이닉스
        company_names_raw=[],
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["krx_lookup_skipped"] is False
    assert out["krx_matched"] is True
    assert out["stock_codes_final"] == ["005930", "000660"]
    # 두 종목의 sectors_major union (둘 다 반도체일 수 있음 → 1개 또는 2개)
    assert len(out["sectors_major_final"]) >= 1


def test_섹터_zero_match_is_auto_ok(krx):
    """섹터에 stock_code/company_name이 없거나 모두 미매칭이어도 정상 (decide_status가 auto로 처리)."""
    raw = make_llm_extraction(
        report_type="섹터",
        stock_codes_raw=[],
        company_names_raw=[],
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["krx_lookup_skipped"] is False
    assert out["krx_matched"] is False
    assert out["stock_codes_final"] == []


def test_published_at_uses_llm_value_when_present(krx):
    raw = make_llm_extraction(
        report_type="단일종목",
        stock_codes_raw=["005930"],
        published_at="2026-04-30",
    )
    out = resolve_krx(_state(raw), krx=krx)
    assert out["published_at_final"].isoformat() == "2026-04-30"
    assert out["used_sent_at_fallback"] is False


def test_published_at_falls_back_to_sent_at_kst(krx):
    raw = make_llm_extraction(
        report_type="단일종목",
        stock_codes_raw=["005930"],
        published_at=None,
    )
    # sent_at = 2026-05-01 23:00 UTC → 2026-05-02 KST
    out = resolve_krx(_state(raw, "2026-05-01T23:00:00+00:00"), krx=krx)
    assert out["published_at_final"].isoformat() == "2026-05-02"
    assert out["used_sent_at_fallback"] is True
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest langgraph_tagger/tests/test_resolve_krx.py -v`
Expected: 모든 테스트 fail (`ModuleNotFoundError: No module named 'langgraph_tagger.nodes.resolve_krx'`).

- [ ] **Step 3: resolve_krx.py 작성**

`langgraph_tagger/nodes/resolve_krx.py`:

```python
"""resolve_krx node (v2): canonicalize+validate+enrich 통합.

report_type별 KRX lookup 정책 분기:
- 단일종목: 1 entry (stock_code 우선, 회사명 fallback)
- 섹터: N entry aggregate (stock_codes_raw + company_names_raw 모두 시도, dedupe)
- 산업 / 전략·시황: lookup skip
- 기타 (in-scope): 단일종목과 동일

published_at fallback (LLM published_at == None → sent_at KST date).
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional

from langgraph_tagger.state import RowState
from langgraph_tagger.vocabulary.krx import KRXEntry, KRXIndex

KST = timezone(timedelta(hours=9))


def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def resolve_krx(state: RowState, *, krx: KRXIndex) -> dict:
    raw = state["llm_raw"]
    rt = raw.report_type

    # 산업 / 전략·시황: KRX lookup 자체를 skip
    if rt in ("산업", "전략·시황"):
        return _finalize(state, raw, krx=krx, entries=[], skipped=True, mismatch=False)

    # 단일종목 / 섹터 / 기타: KRX 시도
    entries: list[KRXEntry] = []
    seen: set[str] = set()
    code_match_any = False

    # 1. stock_codes_raw 모두 lookup (모든 valid code dedupe)
    for code in raw.stock_codes_raw:
        if krx.validate_code(code):
            e = krx.lookup(code)
            if e and e.code not in seen:
                entries.append(e)
                seen.add(e.code)
                code_match_any = True

    # 2. 단일종목/기타에서 stock_code 미매칭이면 회사명 1개 fallback
    if rt in ("단일종목", "기타") and not entries:
        for name in raw.company_names_raw:
            e = krx.lookup_by_name(name)
            if e and e.code not in seen:
                entries.append(e)
                seen.add(e.code)
                break  # 단일종목/기타는 1개

    # 3. 섹터에서 회사명도 모두 추가 lookup (이미 stock_code로 잡힌 것은 dedupe)
    if rt == "섹터":
        for name in raw.company_names_raw:
            e = krx.lookup_by_name(name)
            if e and e.code not in seen:
                entries.append(e)
                seen.add(e.code)

    # 4. 단일종목/기타는 1개로 자른다
    if rt in ("단일종목", "기타") and len(entries) > 1:
        entries = entries[:1]

    # 5. name/code mismatch 감지 (단일종목 + stock_code 매칭 케이스만)
    mismatch = False
    if rt == "단일종목" and entries and code_match_any and raw.company_names_raw:
        norm_entry = "".join(entries[0].name.split()).lower()
        norm_raws = ["".join(n.split()).lower() for n in raw.company_names_raw]
        mismatch = norm_entry not in norm_raws

    return _finalize(state, raw, krx=krx, entries=entries, skipped=False, mismatch=mismatch)


def _finalize(state, raw, *, krx: KRXIndex, entries: list[KRXEntry], skipped: bool, mismatch: bool) -> dict:
    """entries → final 컬럼 + published_at fallback."""
    if entries:
        sm: list[str] = []
        smn: list[str] = []
        seen_sm: set[str] = set()
        seen_smn: set[str] = set()
        prods: list[str] = []
        seen_p: set[str] = set()
        for e in entries:
            if e.sector_major and e.sector_major not in seen_sm:
                sm.append(e.sector_major); seen_sm.add(e.sector_major)
            if e.sector_minor and e.sector_minor not in seen_smn:
                smn.append(e.sector_minor); seen_smn.add(e.sector_minor)
            for p in krx.split_products(e.products_text):
                if p not in seen_p:
                    prods.append(p); seen_p.add(p)
        result = {
            "krx_lookup_skipped": skipped,
            "krx_matched": True,
            "krx_entries": entries,
            "krx_name_code_mismatch": mismatch,
            "stock_codes_final": [e.code for e in entries],
            "company_names_final": [e.name for e in entries],
            "sectors_major_final": sm,
            "sectors_minor_final": smn,
            "products_final": prods,
        }
    else:
        # entries가 비어있는 경우: 산업/전략·시황(skipped=True), 또는 KRX 미매칭(skipped=False)
        if skipped:
            company_names_final: list[str] = []
        else:
            company_names_final = list(raw.company_names_raw)   # 미매칭 fallback
        result = {
            "krx_lookup_skipped": skipped,
            "krx_matched": False,
            "krx_entries": [],
            "krx_name_code_mismatch": False,
            "stock_codes_final": [],
            "company_names_final": company_names_final,
            "sectors_major_final": [],
            "sectors_minor_final": [],
            "products_final": [],
        }

    # published_at 폴백
    pub = _parse_iso_date(raw.published_at)
    used_fallback = False
    if pub is None:
        sent_at = state["sent_at"]
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        pub = sent_at.astimezone(KST).date()
        used_fallback = True
    result["published_at_final"] = pub
    result["used_sent_at_fallback"] = used_fallback
    return result
```

- [ ] **Step 4: 삭제**

```bash
git rm langgraph_tagger/nodes/canonicalize.py
git rm langgraph_tagger/nodes/validate.py
git rm langgraph_tagger/nodes/enrich.py
git rm langgraph_tagger/tests/test_canonicalize.py
git rm langgraph_tagger/tests/test_validate.py
git rm langgraph_tagger/tests/test_enrich.py
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_resolve_krx.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add langgraph_tagger/nodes/resolve_krx.py langgraph_tagger/tests/test_resolve_krx.py
git commit -m "feat(resolve_krx): v2 — type-aware KRX lookup, drops canonicalize/validate/enrich"
```

---

## Task 11: decide_status.py 단순화

**Files:**
- Modify: `langgraph_tagger/nodes/decide_status.py`
- Modify: `langgraph_tagger/tests/test_decide_status.py`

- [ ] **Step 1: 테스트 재작성**

`langgraph_tagger/tests/test_decide_status.py`:

```python
"""Test decide_status — v2 simplified policy."""
from langgraph_tagger.nodes.decide_status import decide_status
from langgraph_tagger.tests.conftest import make_llm_extraction


def test_pdf_unreadable_review_low():
    out = decide_status({"pdf_unreadable": True})
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert out["tagging_notes"] == "first_page_unreadable"


def test_llm_refusal_review_low():
    out = decide_status({"llm_refusal": "policy"})
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert out["tagging_notes"].startswith("llm_refusal:")


def test_단일종목_krx_unmatched_review_low():
    raw = make_llm_extraction(report_type="단일종목")
    out = decide_status({
        "llm_raw": raw,
        "krx_matched": False,
        "krx_lookup_skipped": False,
    })
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_confidence"] == "low"
    assert out["tagging_notes"] == "krx_unmatched_in_scope:ipo_pending_or_unknown"


def test_산업_krx_skipped_auto_high():
    raw = make_llm_extraction(report_type="산업")
    out = decide_status({
        "llm_raw": raw,
        "krx_matched": False,
        "krx_lookup_skipped": True,
        "pages_used": [1],
        "used_sent_at_fallback": False,
    })
    assert out["tagging_status"] == "auto"
    assert out["tagging_confidence"] == "high"
    assert out["tagging_notes"] is None


def test_섹터_zero_krx_match_auto_high():
    raw = make_llm_extraction(report_type="섹터")
    out = decide_status({
        "llm_raw": raw,
        "krx_matched": False,
        "krx_lookup_skipped": False,
        "pages_used": [1],
        "used_sent_at_fallback": False,
    })
    # 섹터는 0 매칭이어도 review_needed로 보내지 않음
    assert out["tagging_status"] == "auto"


def test_단일종목_krx_matched_auto_high():
    raw = make_llm_extraction(report_type="단일종목")
    out = decide_status({
        "llm_raw": raw,
        "krx_matched": True,
        "krx_lookup_skipped": False,
        "pages_used": [1],
        "used_sent_at_fallback": False,
        "krx_name_code_mismatch": False,
    })
    assert out["tagging_status"] == "auto"
    assert out["tagging_confidence"] == "high"


def test_name_code_mismatch_downgrades_to_medium():
    raw = make_llm_extraction(report_type="단일종목")
    out = decide_status({
        "llm_raw": raw,
        "krx_matched": True,
        "krx_lookup_skipped": False,
        "pages_used": [1],
        "used_sent_at_fallback": False,
        "krx_name_code_mismatch": True,
    })
    assert out["tagging_status"] == "auto"
    assert out["tagging_confidence"] == "medium"
    assert out["tagging_notes"] == "krx_name_code_mismatch"


def test_used_fallback_downgrades_to_medium():
    raw = make_llm_extraction(report_type="단일종목")
    out = decide_status({
        "llm_raw": raw,
        "krx_matched": True,
        "krx_lookup_skipped": False,
        "pages_used": [1, 2],   # multi-page → fallback
        "used_sent_at_fallback": False,
        "krx_name_code_mismatch": False,
    })
    assert out["tagging_status"] == "auto"
    assert out["tagging_confidence"] == "medium"


def test_type_indeterminate_review_low():
    raw = make_llm_extraction(report_type="기타", self_confidence="low")
    out = decide_status({
        "llm_raw": raw,
        "krx_matched": False,
        "krx_lookup_skipped": False,
    })
    assert out["tagging_status"] == "review_needed"
    assert out["tagging_notes"] == "type_indeterminate"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest langgraph_tagger/tests/test_decide_status.py -v`
Expected: 대부분의 테스트 fail (현재 v1 코드는 unknown_*, publisher_canon=None 등의 분기로 review로 보냄).

- [ ] **Step 3: decide_status.py 재작성**

`langgraph_tagger/nodes/decide_status.py`:

```python
"""decide_status node (v2 simplified).

review_needed 트리거 4종:
  - pdf_unreadable
  - llm_refusal
  - 단일종목 + KRX unmatched (IPO pending or unknown)
  - type_indeterminate (report_type='기타' + self_confidence='low')

auto/medium 신호 (high가 아닌 케이스):
  - used_fallback (sent_at fallback 또는 multi-page)
  - krx_name_code_mismatch (단일종목에서 stock_code 매칭이지만 raw 회사명 mismatch)
"""
from __future__ import annotations

from langgraph_tagger.state import RowState


def decide_status(state: RowState) -> dict:
    if state.get("pdf_unreadable"):
        return {"tagging_status": "review_needed", "tagging_confidence": "low",
                "tagging_notes": "first_page_unreadable"}
    if state.get("llm_refusal"):
        return {"tagging_status": "review_needed", "tagging_confidence": "low",
                "tagging_notes": f"llm_refusal:{state['llm_refusal']}"}

    raw = state.get("llm_raw")
    rt = raw.report_type if raw else None

    # 단일종목 + KRX 미매칭만 review_needed (IPO 예정/상장예정/오타 등)
    # 산업/전략·시황은 lookup_skipped=True로 매칭 의미 없음 → auto OK
    # 섹터는 0개 매칭이어도 정상 케이스 (peer reference 없는 산업·테마 리포트) → auto OK
    if rt == "단일종목" and not state.get("krx_matched"):
        return {"tagging_status": "review_needed", "tagging_confidence": "low",
                "tagging_notes": "krx_unmatched_in_scope:ipo_pending_or_unknown"}

    if rt == "기타" and raw is not None and raw.self_confidence == "low":
        return {"tagging_status": "review_needed", "tagging_confidence": "low",
                "tagging_notes": "type_indeterminate"}

    # in-scope auto. confidence는 폴백/mismatch 신호로 결정.
    used_fallback = (
        state.get("used_sent_at_fallback")
        or len(state.get("pages_used") or [1]) > 1
    )
    name_code_mismatch = bool(state.get("krx_name_code_mismatch"))
    confidence = "medium" if (used_fallback or name_code_mismatch) else "high"
    notes = "krx_name_code_mismatch" if name_code_mismatch else None
    return {
        "tagging_status": "auto",
        "tagging_confidence": confidence,
        "tagging_notes": notes,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_decide_status.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add langgraph_tagger/nodes/decide_status.py langgraph_tagger/tests/test_decide_status.py
git commit -m "refactor(decide_status): v2 — simplify to 4 review triggers, mismatch downgrades to medium"
```

---

## Task 12: write.py + supabase_io.py — UPDATE_SQL 19-arg, OOS report_type 보존

**Files:**
- Modify: `langgraph_tagger/supabase_io.py`
- Modify: `langgraph_tagger/nodes/write.py`
- Modify: `langgraph_tagger/tests/test_write.py`
- Modify: `langgraph_tagger/tests/test_supabase_io.py`

- [ ] **Step 1: supabase_io.py의 UPDATE_SQL 변경**

`langgraph_tagger/supabase_io.py`의 `UPDATE_SQL` 상수를 다음으로 교체:

```python
# Note: in-scope, OOS, unreadable rows all share this UPDATE; payload semantics differ.
UPDATE_SQL = """
UPDATE reports
   SET published_at=$2,
       report_type=$3,
       publisher=$4,
       publisher_type=$5,
       analysts=$6,
       title=$7,
       stock_codes=$8,
       company_names=$9,
       stock_codes_raw=$10,
       company_names_raw=$11,
       sectors_major=$12,
       sectors_minor=$13,
       products=$14,
       out_of_scope_reason=$15,
       tagging_status=$16,
       tagging_confidence=$17,
       tagging_notes=$18,
       tagging_locked_at=NULL,
       tagging_worker_id=NULL,
       tagged_at=now(),
       tagger_version='langgraph-tagger@2.0',
       taxonomy_version=$19
 WHERE id=$1
"""
```

(v1: 18 placeholders, `topics`=$13. v2: 19 placeholders, `stock_codes_raw`/`company_names_raw` 추가, `topics` 제거, 버전 `2.0`.)

- [ ] **Step 2: write.py 재작성**

`langgraph_tagger/nodes/write.py`:

```python
"""write node (v2): build UPDATE payload and persist via SupabaseSQL.

v2 변경 (rev-7):
- topics 제거, stock_codes_raw/company_names_raw 추가 → 19-arg payload
- OOS row도 LLM의 report_type/publisher/title/analysts 보존 ('기타' 강제 안 함)
"""
from __future__ import annotations

from langgraph_tagger.state import RowState
from langgraph_tagger.supabase_io import UPDATE_SQL


def _build_payload(state: RowState, taxonomy_version: str) -> tuple:
    """Return UPDATE_SQL bind-arg tuple matching $1..$19 in supabase_io.UPDATE_SQL."""
    raw = state.get("llm_raw")
    is_oos = bool(state.get("is_oos"))

    # OOS 케이스 — 분류 본체(stock_codes/company_names/sectors/products)는 비우되
    # report_type/publisher/title/analysts/raw audit는 LLM 출력 그대로 보존.
    if is_oos:
        return (
            state["id"],                                     # $1
            None,                                             # $2 published_at (OOS는 null)
            (raw.report_type if raw else None),               # $3 report_type — LLM 분류 그대로
            (raw.publisher_canon if raw else None),           # $4 publisher
            (raw.publisher_type if raw else None),            # $5 publisher_type
            list(raw.analysts) if raw else [],                # $6 analysts
            (raw.title if raw else None),                     # $7 title
            [],                                               # $8 stock_codes
            [],                                               # $9 company_names
            list(raw.stock_codes_raw) if raw else [],         # $10 stock_codes_raw (audit)
            list(raw.company_names_raw) if raw else [],       # $11 company_names_raw (audit)
            [],                                               # $12 sectors_major
            [],                                               # $13 sectors_minor
            [],                                               # $14 products
            state["oos_reason"],                              # $15 out_of_scope_reason
            state["tagging_status"],                          # $16
            state["tagging_confidence"],                      # $17
            state.get("tagging_notes"),                       # $18
            taxonomy_version,                                 # $19
        )

    # 가독 실패 (raw 없음)
    if raw is None:
        return (
            state["id"], None, None, None, None, [], None,
            [], [], [], [], [], [], [],
            None, state["tagging_status"], state["tagging_confidence"],
            state.get("tagging_notes"), taxonomy_version,
        )

    # in-scope
    return (
        state["id"],
        state["published_at_final"],
        raw.report_type,
        raw.publisher_canon,
        raw.publisher_type,
        list(raw.analysts),
        raw.title,
        list(state.get("stock_codes_final", [])),
        list(state.get("company_names_final", [])),
        list(raw.stock_codes_raw),                  # audit 항상 보존
        list(raw.company_names_raw),                # audit 항상 보존
        list(state.get("sectors_major_final", [])),
        list(state.get("sectors_minor_final", [])),
        list(state.get("products_final", [])),
        None,                                        # out_of_scope_reason NULL
        state["tagging_status"],
        state["tagging_confidence"],
        state.get("tagging_notes"),
        taxonomy_version,
    )


async def write(state: RowState, *, sb, dry_run: bool, taxonomy_version: str) -> dict:
    if dry_run:
        return {}
    args = _build_payload(state, taxonomy_version)
    await sb.execute(UPDATE_SQL, args)
    return {}
```

- [ ] **Step 3: test_write.py 갱신**

`langgraph_tagger/tests/test_write.py`의 모든 `_build_payload` 호출에 대한 expectation을 19개 위치 placeholder + v2 컬럼 순서로 갱신.

핵심 신규 테스트:

```python
def test_oos_payload_preserves_report_type():
    """v2: OOS는 LLM 분류 그대로 ('기타' 강제 안 함)."""
    from langgraph_tagger.nodes.write import _build_payload
    from langgraph_tagger.tests.conftest import make_llm_extraction

    raw = make_llm_extraction(
        report_type="단일종목",
        publisher_canon="키움증권",
        publisher_type="broker",
        stock_codes_raw=["TSLA01"],
        company_names_raw=["Tesla"],
    )
    state = {
        "id": 1, "is_oos": True, "oos_reason": "foreign",
        "llm_raw": raw,
        "tagging_status": "auto", "tagging_confidence": "high",
        "tagging_notes": None,
    }
    out = _build_payload(state, taxonomy_version="KRX@test")
    assert len(out) == 19
    # $3 report_type — LLM 분류 그대로
    assert out[2] == "단일종목"
    # $4 publisher — LLM 출력 그대로
    assert out[3] == "키움증권"
    # $10 stock_codes_raw (audit)
    assert out[9] == ["TSLA01"]
    # $11 company_names_raw (audit)
    assert out[10] == ["Tesla"]
    # $15 out_of_scope_reason
    assert out[14] == "foreign"


def test_in_scope_payload_19_args():
    """v2 in-scope payload는 19-arg, raw audit 항상 포함."""
    from datetime import date
    from langgraph_tagger.nodes.write import _build_payload
    from langgraph_tagger.tests.conftest import make_llm_extraction

    raw = make_llm_extraction(
        report_type="단일종목",
        publisher_canon="키움증권",
        publisher_type="broker",
        stock_codes_raw=["005930"],
        company_names_raw=["삼성전자"],
    )
    state = {
        "id": 7, "is_oos": False,
        "llm_raw": raw,
        "published_at_final": date(2026, 5, 1),
        "stock_codes_final": ["005930"],
        "company_names_final": ["삼성전자"],
        "sectors_major_final": ["전기전자"],
        "sectors_minor_final": ["반도체"],
        "products_final": ["DRAM", "NAND"],
        "tagging_status": "auto", "tagging_confidence": "high",
        "tagging_notes": None,
    }
    out = _build_payload(state, taxonomy_version="KRX@test")
    assert len(out) == 19
    assert out[2] == "단일종목"
    assert out[7] == ["005930"]
    assert out[8] == ["삼성전자"]
    assert out[9] == ["005930"]   # raw audit
    assert out[10] == ["삼성전자"]
    assert out[11] == ["전기전자"]
    assert out[14] is None        # OOS reason null for in-scope
```

(기존 v1 테스트 중 `topics`나 18-arg를 검증하는 항목은 모두 수정 또는 삭제.)

- [ ] **Step 4: test_supabase_io.py 갱신 — UPDATE_SQL placeholder count 검증**

`langgraph_tagger/tests/test_supabase_io.py`에 다음 테스트 갱신/추가:

```python
def test_update_sql_has_19_placeholders():
    import re
    from langgraph_tagger.supabase_io import UPDATE_SQL
    placeholders = set(re.findall(r"\$\d+", UPDATE_SQL))
    expected = {f"${i}" for i in range(1, 20)}
    assert placeholders == expected


def test_update_sql_has_raw_audit_columns():
    from langgraph_tagger.supabase_io import UPDATE_SQL
    assert "stock_codes_raw=$10" in UPDATE_SQL
    assert "company_names_raw=$11" in UPDATE_SQL
    assert "topics" not in UPDATE_SQL


def test_update_sql_tagger_version_is_2_0():
    from langgraph_tagger.supabase_io import UPDATE_SQL
    assert "tagger_version='langgraph-tagger@2.0'" in UPDATE_SQL
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_write.py langgraph_tagger/tests/test_supabase_io.py -v`
Expected: 모두 통과.

- [ ] **Step 6: Commit**

```bash
git add langgraph_tagger/supabase_io.py langgraph_tagger/nodes/write.py langgraph_tagger/tests/test_write.py langgraph_tagger/tests/test_supabase_io.py
git commit -m "feat(write): v2 — 19-arg payload (raw audit cols), OOS preserves LLM report_type"
```

---

## Task 13: graph.py — 8 노드 wiring

**Files:**
- Modify: `langgraph_tagger/graph.py`
- Modify: `langgraph_tagger/tests/test_graph.py`

- [ ] **Step 1: graph.py 재작성**

`langgraph_tagger/graph.py`:

```python
"""Assemble the v2 row-graph from 8 node modules.

v1 → v2 변경:
- canonicalize / validate / enrich → resolve_krx (1 노드)
- oos_gate 라벨 'canonicalize' → 'resolve_krx'
- 총 10 노드 → 8 노드
"""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from langgraph_tagger.nodes.decide_status import decide_status
from langgraph_tagger.nodes.extract_pdf import extract_pdf
from langgraph_tagger.nodes.llm_extract import llm_extract
from langgraph_tagger.nodes.mark_oos_reason import mark_oos_reason
from langgraph_tagger.nodes.oos_gate import oos_gate
from langgraph_tagger.nodes.resolve_krx import resolve_krx
from langgraph_tagger.nodes.status_oos import status_oos
from langgraph_tagger.nodes.status_unreadable import status_unreadable
from langgraph_tagger.nodes.write import write
from langgraph_tagger.state import RowState
from langgraph_tagger.vocabulary.krx import KRXIndex


def build_graph(client, sb, *, krx: KRXIndex, dry_run: bool, taxonomy_version: str):
    g = StateGraph(RowState)

    g.add_node("extract_pdf", extract_pdf)
    g.add_node("llm_extract", partial(llm_extract, client=client))
    g.add_node("mark_oos_reason", mark_oos_reason)
    g.add_node("status_oos", status_oos)
    g.add_node("status_unreadable", status_unreadable)
    g.add_node("resolve_krx", partial(resolve_krx, krx=krx))
    g.add_node("decide_status", decide_status)
    g.add_node("write", partial(write, sb=sb, dry_run=dry_run, taxonomy_version=taxonomy_version))

    g.add_edge(START, "extract_pdf")
    g.add_edge("extract_pdf", "llm_extract")
    g.add_conditional_edges(
        "llm_extract",
        partial(oos_gate, krx=krx),
        {
            "mark_oos_reason":   "mark_oos_reason",
            "status_unreadable": "status_unreadable",
            "resolve_krx":       "resolve_krx",
        },
    )
    g.add_edge("mark_oos_reason", "status_oos")
    g.add_edge("status_oos", "write")
    g.add_edge("status_unreadable", "write")
    g.add_edge("resolve_krx", "decide_status")
    g.add_edge("decide_status", "write")
    g.add_edge("write", END)

    return g.compile()
```

- [ ] **Step 2: test_graph.py 갱신**

`langgraph_tagger/tests/test_graph.py`에서 v1 노드 (`canonicalize`, `validate`, `enrich`) 참조를 모두 제거하고 `resolve_krx`로 교체. 노드 개수 검증을 8개로:

```python
def test_graph_has_8_nodes():
    """v2 graph has 8 nodes (down from v1's 10)."""
    from unittest.mock import MagicMock
    from pathlib import Path
    from langgraph_tagger.graph import build_graph
    from langgraph_tagger.vocabulary.krx import KRXIndex

    krx = KRXIndex.load(Path("docs/stock_data/KRX_stocks_data.csv"))
    app = build_graph(
        client=MagicMock(), sb=MagicMock(),
        krx=krx, dry_run=True, taxonomy_version="t",
    )
    # LangGraph compiled app exposes nodes via .nodes (or graph dict). Use 1.0 API:
    nodes = app.get_graph().nodes
    # Subtract LangGraph's internal __start__/__end__ nodes if present.
    user_nodes = {n for n in nodes if not n.startswith("__")}
    assert user_nodes == {
        "extract_pdf", "llm_extract", "mark_oos_reason",
        "status_oos", "status_unreadable", "resolve_krx",
        "decide_status", "write",
    }
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_graph.py -v`
Expected: 모두 통과.

- [ ] **Step 4: Commit**

```bash
git add langgraph_tagger/graph.py langgraph_tagger/tests/test_graph.py
git commit -m "refactor(graph): v2 — 8-node wiring (canonicalize/validate/enrich → resolve_krx)"
```

---

## Task 14: orchestrator.py — review_reasons set + oos_counter 갱신

**Files:**
- Modify: `langgraph_tagger/orchestrator.py`
- Modify: `langgraph_tagger/tests/test_orchestrator.py`

- [ ] **Step 1: orchestrator.py의 `_empty_report` 및 `_aggregate` 변경**

`langgraph_tagger/orchestrator.py`의 두 함수 수정:

```python
def _empty_report(model: str) -> dict:
    return {
        "model": model, "processed": 0,
        "auto": 0, "review_needed": 0,
        "confidence": {"high": 0, "medium": 0, "low": 0},
        "oos": {"foreign": 0, "fund": 0, "digital": 0, "private": 0, "ir_self": 0},
        "review_reasons": {},
        "transient_errors": 0,
        "deadline_errors": 0,
        "unhandled_errors": 0,
    }


def _aggregate(results: list[dict], *, model: str, batch_size: int, dry_run: bool) -> dict:
    auto = sum(1 for r in results if r.get("tagging_status") == "auto")
    review = sum(1 for r in results if r.get("tagging_status") == "review_needed")
    transient = sum(1 for r in results if r.get("error") == "transient")
    deadline = sum(1 for r in results if r.get("error") == "deadline_exceeded")
    unhandled = sum(1 for r in results if r.get("error") == "unhandled")

    conf_counter = Counter(r.get("tagging_confidence") for r in results if "tagging_confidence" in r)
    oos_counter = Counter(r.get("oos_reason") for r in results if r.get("is_oos"))

    review_reasons: Counter[str] = Counter()
    for r in results:
        notes = r.get("tagging_notes") or ""
        for token in notes.split(";"):
            if not token:
                continue
            tag = token.split(":", 1)[0]
            if tag in ("first_page_unreadable", "llm_refusal", "type_indeterminate",
                       "krx_unmatched_in_scope"):
                review_reasons[tag] += 1

    return {
        "model": model,
        "processed": len(results),
        "auto": auto,
        "review_needed": review,
        "confidence": {
            "high": conf_counter.get("high", 0),
            "medium": conf_counter.get("medium", 0),
            "low": conf_counter.get("low", 0),
        },
        "oos": {
            "foreign":  oos_counter.get("foreign", 0),
            "fund":     oos_counter.get("fund", 0),
            "digital":  oos_counter.get("digital", 0),
            "private":  oos_counter.get("private", 0),
            "ir_self":  oos_counter.get("ir_self", 0),
        },
        "review_reasons": dict(review_reasons),
        "transient_errors": transient,
        "deadline_errors": deadline,
        "unhandled_errors": unhandled,
        "dry_run": dry_run,
        "batch_size": batch_size,
    }
```

(변경: `oos`에 `ir_self` 추가; review_reasons set이 v1의 `unknown_*` 4종 제거하고 `krx_unmatched_in_scope` 추가; v1 4개 → v2 4개로 동일 개수지만 키 변경.)

- [ ] **Step 2: test_orchestrator.py 갱신**

`langgraph_tagger/tests/test_orchestrator.py`의 review_reasons / oos counter 관련 테스트를 v2 키로 갱신. 핵심:

```python
def test_aggregate_oos_includes_ir_self():
    from langgraph_tagger.orchestrator import _aggregate
    results = [
        {"id": 1, "is_oos": True, "oos_reason": "ir_self", "tagging_status": "auto",
         "tagging_confidence": "high"},
        {"id": 2, "is_oos": True, "oos_reason": "foreign", "tagging_status": "auto",
         "tagging_confidence": "high"},
    ]
    rep = _aggregate(results, model="m", batch_size=2, dry_run=False)
    assert rep["oos"]["ir_self"] == 1
    assert rep["oos"]["foreign"] == 1


def test_aggregate_review_reasons_v2_keys():
    from langgraph_tagger.orchestrator import _aggregate
    results = [
        {"id": 1, "tagging_status": "review_needed",
         "tagging_notes": "krx_unmatched_in_scope:ipo_pending_or_unknown"},
        {"id": 2, "tagging_status": "review_needed",
         "tagging_notes": "type_indeterminate"},
    ]
    rep = _aggregate(results, model="m", batch_size=2, dry_run=False)
    assert rep["review_reasons"] == {
        "krx_unmatched_in_scope": 1, "type_indeterminate": 1,
    }
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_orchestrator.py -v`
Expected: 모두 통과.

- [ ] **Step 4: Commit**

```bash
git add langgraph_tagger/orchestrator.py langgraph_tagger/tests/test_orchestrator.py
git commit -m "feat(orchestrator): v2 — oos counter += ir_self, review_reasons replaces unknown_* with krx_unmatched_in_scope"
```

---

## Task 15: parity fixtures 재구성 (6종 × 5 OOS + mismatch)

**Files:**
- Modify: `langgraph_tagger/tests/parity/fixtures.json`
- Modify: `langgraph_tagger/tests/parity/README.md` (필요 시)

- [ ] **Step 1: 기존 fixtures.json 백업 + 새 v2 fixtures 작성**

`langgraph_tagger/tests/parity/fixtures.json`을 다음 12개 case로 재작성:

| case | report_type | OOS | confidence | notes |
|---|---|---|---|---|
| 단일종목_auto_high | 단일종목 | - | high | KRX 매칭 |
| 단일종목_unmatched_review | 단일종목 | - | low | krx_unmatched_in_scope (IPO 후보) |
| 단일종목_mismatch_medium | 단일종목 | - | medium | krx_name_code_mismatch |
| 산업_auto_high | 산업 | - | high | KRX skip, sectors 빈 배열 |
| 섹터_aggregates_n | 섹터 | - | high | 두 종목 union |
| 섹터_zero_match_auto | 섹터 | - | high | 0 매칭이어도 auto |
| 전략시황_auto_high | 전략·시황 | - | high | KRX skip |
| oos_foreign | 단일종목 | foreign | high | 해외 primary coverage (report_type 보존) |
| oos_fund | 기타 | fund | high | ETF |
| oos_digital | 기타 | digital | high | BTC |
| oos_private | 기타 | private | medium | 비상장 분석 |
| oos_ir_self | IR자료 | ir_self | high | 자체 IR (publisher='해당기업') |

샘플 fixture 구조 (한 case 전체):

```json
[
  {
    "case": "단일종목_auto_high",
    "input": {
      "file_name": "ssung_q1.pdf",
      "caption": null,
      "sent_at": "2026-05-01T05:00:00+00:00",
      "pdf_text": "삼성전자 005930 1Q26 Preview\n분석가: 홍길동\n키움증권 리서치센터\n2026-04-30"
    },
    "llm_mock": {
      "report_type": "단일종목",
      "title": "삼성전자 1Q26 Preview",
      "published_at": "2026-04-30",
      "stock_codes_raw": ["005930"],
      "company_names_raw": ["삼성전자"],
      "publisher_canon": "키움증권",
      "publisher_type": "broker",
      "analysts": ["홍길동"],
      "oos_signals": {
        "foreign_primary_coverage": false, "etf_or_fund": false,
        "digital_asset": false, "private_company_likely": false
      },
      "self_confidence": "high",
      "notes": null
    },
    "expected": {
      "report_type": "단일종목",
      "publisher": "키움증권",
      "publisher_type": "broker",
      "stock_codes": ["005930"],
      "company_names": ["삼성전자"],
      "stock_codes_raw": ["005930"],
      "company_names_raw": ["삼성전자"],
      "out_of_scope_reason": null,
      "tagging_status": "auto",
      "tagging_confidence": "high",
      "tagging_notes": null
    }
  }
]
```

전체 12 case의 JSON은 위 표를 따라 동일 구조로 생성. test_parity.py가 expected를 19-arg payload와 매칭하므로 모든 expected 필드는 v2 컬럼 이름 사용.

- [ ] **Step 2: test_parity.py가 v2 expected를 검증하도록 갱신**

`langgraph_tagger/tests/test_parity.py`의 검증 부분이 19-arg payload의 v2 인덱스를 사용하도록 수정. 예:

```python
# In test_parity, after running the graph and capturing the UPDATE call:
sql, args = mock_supabase.executed[-1]
# v2 payload positions ($1..$19):
#  $1 id, $2 published_at, $3 report_type, $4 publisher, $5 publisher_type,
#  $6 analysts, $7 title, $8 stock_codes, $9 company_names,
#  $10 stock_codes_raw, $11 company_names_raw,
#  $12 sectors_major, $13 sectors_minor, $14 products,
#  $15 out_of_scope_reason, $16 tagging_status, $17 tagging_confidence,
#  $18 tagging_notes, $19 taxonomy_version

assert args[2] == fix["expected"]["report_type"]
assert args[3] == fix["expected"]["publisher"]
assert args[4] == fix["expected"]["publisher_type"]
assert list(args[7]) == fix["expected"]["stock_codes"]
assert list(args[8]) == fix["expected"]["company_names"]
assert list(args[9]) == fix["expected"]["stock_codes_raw"]
assert list(args[10]) == fix["expected"]["company_names_raw"]
assert args[14] == fix["expected"]["out_of_scope_reason"]
assert args[15] == fix["expected"]["tagging_status"]
assert args[16] == fix["expected"]["tagging_confidence"]
assert args[17] == fix["expected"]["tagging_notes"]
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `pytest langgraph_tagger/tests/test_parity.py -v`
Expected: 12 passed.

- [ ] **Step 4: Commit**

```bash
git add langgraph_tagger/tests/parity/fixtures.json langgraph_tagger/tests/test_parity.py
git commit -m "test(parity): v2 fixtures — 6 report_types × 5 OOS reasons + mismatch case"
```

---

## Task 16: 전체 테스트 + dry-run + migration 003 적용 + live verification

**Files:**
- (no source changes — verification only)

- [ ] **Step 1: 전체 단위 테스트 실행**

Run: `pytest langgraph_tagger/tests/ -v --tb=short 2>&1 | tail -40`
Expected: 모든 테스트 통과 (test_canonicalize/validate/enrich/topics는 모두 삭제됐으므로 collection에서 제외).

- [ ] **Step 2: lint/import sanity check**

Run: `python -c "from langgraph_tagger import cli, graph, orchestrator, supabase_io; from langgraph_tagger.nodes import extract_pdf, llm_extract, oos_gate, mark_oos_reason, status_oos, status_unreadable, resolve_krx, decide_status, write; print('all v2 modules import OK')"`
Expected: `all v2 modules import OK`

(canonicalize/validate/enrich import는 GraphPath나 다른 곳에서 잔재 없는지 확인.)

Run: `grep -rn "from langgraph_tagger.nodes.canonicalize\|from langgraph_tagger.nodes.validate\|from langgraph_tagger.nodes.enrich\|topics_canon\|topic_unmapped\|publisher_raw" langgraph_tagger/`
Expected: matches 없음 (또는 삭제된 파일에 있는 것만).

- [ ] **Step 3: migration 003 적용 전 분포 확인**

Run: `python -m langgraph_tagger inspect`
Expected: v1 분포 출력 (예: `auto=3,317, review_needed=73, oos_total=151`). 이 숫자를 메모해둠.

- [ ] **Step 4: migration 003 적용**

Supabase SQL Editor 또는 psql에서 `migrations/003_v2_redesign.sql` 전체 실행.

검증:
```sql
-- 모든 row가 pending이고 분류 컬럼이 비어있어야 함
SELECT tagging_status, count(*) FROM reports GROUP BY tagging_status;
-- 예상: pending = 전체 row 수 (~3,541)

SELECT count(*) FROM reports WHERE report_type IS NOT NULL;
-- 예상: 0

SELECT count(*) FROM reports WHERE stock_codes_raw IS NULL;
-- 예상: 0 (default '{}'로 채워졌어야 함)
```

- [ ] **Step 5: dry-run 검증 (3건)**

Run: `python -m langgraph_tagger run --dry-run --batch-size 3`
Expected: JSON 보고서 출력. `processed=3`, 분포 확인. `oos`, `review_reasons` 키가 v2 형태.

샘플 출력 점검 포인트:
- `oos`에 `ir_self` 키 존재
- `review_reasons` 값이 `krx_unmatched_in_scope` / `type_indeterminate` / `first_page_unreadable` / `llm_refusal` 중 하나만
- 결과가 합리적이지 않으면 prompt 또는 vocab 점검 (Task 6 보강 후 재시도)

- [ ] **Step 6: 소규모 실 backfill (10건)**

Run: `python -m langgraph_tagger run --batch-size 10`
Expected: 10건이 `auto` 또는 `review_needed`로 처리. inspect로 분포 확인:

Run: `python -m langgraph_tagger inspect`
Expected: 처리한 만큼 pending 감소, auto/review_needed 증가.

- [ ] **Step 7: 전체 backfill (반복 실행)**

PDF가 ~3,541건이고 batch-size 50, max_concurrent_llm 10 기준 약 1~2시간 소요 예상.

Run (반복): `while [ "$(python -m langgraph_tagger inspect | python -c 'import sys, json; print(json.load(sys.stdin)[\"pending\"])')" -gt 0 ]; do python -m langgraph_tagger run --batch-size 50 --max-concurrent-llm 10; done`

또는 pwsh:
```pwsh
while ((python -m langgraph_tagger inspect | ConvertFrom-Json).pending -gt 0) {
  python -m langgraph_tagger run --batch-size 50 --max-concurrent-llm 10
}
```

- [ ] **Step 8: 최종 분포 확인 + Commit (verification만)**

Run: `python -m langgraph_tagger inspect`
Expected: `pending=0`, `processing=0`, 대부분 `auto`, 일부 `review_needed`/`oos_total`.

이 task는 코드 변경 없음 — verification만이므로 별도 commit 불필요. v2 implementation이 production에 반영되었음을 확인한다.

---

## Self-Review

이 plan을 spec rev-7과 대조해서 누락 점검:

**§4 v1→v2 변경 요약**:
- ✓ PDF 페이지 1~3p (Task 7)
- ✓ LLM 출력 schema 축소 (Task 5)
- ✓ report_type 6종 (Task 2, 5)
- ✓ publisher LLM 자의적 매핑 (Task 6)
- ✓ sectors/products KRX 답지 (Task 10)
- ✓ topics 폐기 (Task 2, 5)
- ✓ OOS 5종 (Task 2, 8, 9)
- ✓ IR자료 OOS (Task 8)
- ✓ OOS row report_type 보존 (Task 12)
- ✓ 종목명 정규화 (Task 10)
- ✓ canonicalize/validate/enrich 삭제 (Task 10)
- ✓ resolve_krx 신규 (Task 10)
- ✓ KRX lookup 정책 (Task 10)
- ✓ decide_status 단순화 (Task 11)
- ✓ name/code mismatch (Task 10, 11)
- ✓ DB 컬럼 (Task 1)
- ✓ GIN 인덱스 (Task 1)
- ✓ 기존 데이터 reset (Task 1, 16)

**§9 노드별 동작**:
- ✓ extract_pdf max=3 (Task 7)
- ✓ llm_extract — schema 변경만 자동 적용 (Task 5)
- ✓ prompts.py (Task 6)
- ✓ oos_gate (Task 8)
- ✓ mark_oos_reason (Task 8)
- ✓ status_oos ir_self high (Task 9)
- ✓ status_unreadable — 그대로
- ✓ resolve_krx (Task 10)
- ✓ decide_status (Task 11)
- ✓ write (Task 12)
- ✓ graph 조립 (Task 13)

**§10 운영**:
- ✓ orchestrator review_reasons + oos_counter (Task 14)
- ✓ inspect / escalate — 그대로

**§11 migration 003**:
- ✓ Task 1 — BEGIN/COMMIT, DROP 먼저, reset, ADD/DROP, 새 CHECK ADD, GIN

**§13 기존 row reset → backfill**:
- ✓ Task 16 — migration 적용 + dry-run + backfill 실행

**§16 우선순위 1~8**:
- 1 migration 003 → Task 1 (실행은 Task 16)
- 2 publishers.yaml + taxonomy.yaml → Task 2
- 3 llm_schemas + state → Task 5
- 4 prompts → Task 6
- 5 resolve_krx 신규 + 노드 삭제 → Task 10
- 6 decide_status + write → Task 11, 12
- 7 테스트 + parity fixtures → 각 task 안에 + Task 15
- 8 dry-run / live verification → Task 16

모든 spec 요구사항이 task에 매핑됨. 누락 없음.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-09-langgraph-tagger-v2.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec compliance + code quality), fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

Which approach?
