# LangGraph 기반 PDF 메타데이터 태깅 — 설계

**기존 Claude Code/Codex 스킬을 OpenAI API + LangGraph로 이식**

작성일: 2026-05-08
상태: 설계 (구현 전)
선행 spec: `docs/superpowers/specs/2026-05-07-report-metadata-tagging-routine-design.md` (이하 "원 spec")

---

## 1. 배경

`claude/friendly-mclaren-815e01`(Claude Code 기반)과 `codex/skills_for_Codex`(Codex 기반) 두 브랜치에서 PDF 리포트 메타데이터 태깅을 스킬로 구현했다. 분류 정확도와 결정 룰 정교함은 만족스러우나, 실측 운영에서 두 가지 한계가 드러났다:

1. **처리 속도가 느리다.** 대화형 LLM 호출 + skill 워크플로우의 다단계 추론으로 row 1건 처리에 수십 초가 걸린다.
2. **토큰 소진이 빠르다.** 모든 결정(추출, OOS 판정, canonical 정규화, 산업 합류, status 결정)을 LLM이 한 줄기로 처리하므로 입출력 토큰이 두텁다.

원 spec의 룰·도메인·CHECK 제약·인덱스는 이미 검증되었으므로 그대로 보존한다. 본 spec은 동일한 결과를 더 빠르고 더 저렴하게 내기 위해 **호출 환경을 OpenAI API로, 오케스트레이션을 LangGraph로** 이식하는 설계다.

## 2. 목표 (Phase 1 — 환경 이식)

- 원 spec의 모든 결정 룰·CHECK 제약·OOS 분류·status 결정을 **결과 동일성** 기준으로 100% 보존한다.
- LLM의 책임을 "자유 텍스트 → 구조화 JSON 추출, 분류, OOS 신호 감지" 한 회의 호출로 압축한다.
- 룩업·검증·합류·status 결정은 **Python 코드로 결정적으로** 처리해 LLM 토큰 소모를 줄이고 일관성을 확보한다.
- backfill 가속을 위해 row 단위 그래프를 `asyncio.gather + Semaphore`로 병렬 실행한다.
- mini → 대형 모델 escalation을 **외부 2-pass 패턴**으로 분리해 비용 가시성을 확보한다.

## 3. 비범위

- 원 spec의 데이터 모델은 변경하지 않는다. `migrations/002_tagging_columns.sql`을 그대로 사용.
- Claude Code/Codex 스킬을 삭제·수정하지 않는다. 두 환경은 병행 가능 (서로 다른 worker_id로 충돌 없음).
- Phase 2(톤·요지 분석), Phase 3(트레이싱 UI), Phase 4(커버리지 확장)는 본 spec 범위 외.

## 4. 핵심 설계 결정

| # | 결정 | 선택 | 근거 |
|---|---|---|---|
| 1 | LLM과 코드 책임 분담 | 결과 1:1, 책임 재분담 | LLM은 자유 텍스트 추출/분류/OOS 신호만. 룩업·검증·합류·status 결정은 코드. |
| 2 | LangGraph 그래프 구조 | 단일 row 그래프 + 외부 asyncio batch | 학습 부담 최소, master `collector.py` 동시성 패턴 재사용 |
| 3 | PDF → 텍스트 추출 | PyMuPDF (`fitz`) | 성능 우수 |
| 4 | LLM 모델 | gpt-5.4-mini → gpt-5.4 escalation | 일상 batch는 mini, review_needed만 gpt-5.4 재처리 |
| 5 | escalation 위치 | 외부 2-pass (`row_ids` 인자 사용) | 그래프 단순, 비용 가시성, 1pass 결과 영속화 |
| 6 | LangGraph 버전 | 1.0.x GA | 안정 API, TypedDict 권장 |
| 7 | OpenAI SDK | v2.x `client.chat.completions.parse()` | Pydantic structured output GA, langchain-openai 의존 불필요 |
| 8 | Vocabulary 표현 | YAML (`pyyaml`) | 사람 가독성 + git diff 친화 |

## 5. 산출물

1. **새 패키지** `langgraph_tagger/` (master 코드 비건드림)
2. **마이그레이션은 추가 없음** — `002_tagging_columns.sql`을 friendly-mclaren에서 가져와 `migrations/`에 commit
3. **KRX CSV** `docs/stock_data/KRX_stocks_data.csv`를 git tracked로 commit (master에 미포함)
4. **CLI** `python -m langgraph_tagger run|inspect|escalate ...`
5. **Vocabulary YAML** 3종 + KRX 인덱스 1종

기존 `collector.py`/`storage.py`/`telegram_client.py`/`main.py`/`config.py`는 **수정하지 않는다**.

## 6. 아키텍처

### 6.1 큰 그림

```
┌─────────────────────────────────────────────────────────────┐
│  CLI 진입점  (python -m langgraph_tagger ...)                │
│   subcommands: run | inspect | escalate                     │
│   args: batch_size, dry_run, row_ids, model, since          │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator (orchestrator.py, async)                      │
│   1. stale lock 회수 (운영 모드만)                            │
│   2. atomic claim (운영) / SELECT (dry_run) /                │
│      ROW_IDS_FETCH (row_ids 명시)                            │
│   3. asyncio.gather + Semaphore(N) → row_graph.ainvoke      │
│   4. 분포 집계 + 보고                                         │
└──────────────────────────┬──────────────────────────────────┘
                           ▼ (row 1건마다 동시에 N개)
┌─────────────────────────────────────────────────────────────┐
│  LangGraph row_graph (graph.py)                             │
│   extract_pdf → llm_extract → oos_gate (routing-only,       │
│                                3-way branch)                │
│      ├─ OOS:         mark_oos_reason → status_oos → write   │
│      ├─ unreadable:  status_unreadable               → write│
│      └─ in-scope:    canonicalize → validate → enrich →     │
│                       decide_status                  → write │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
                      Supabase (UPDATE)
```

### 6.2 escalation 흐름 (외부 2-pass)

```
1pass:  python -m langgraph_tagger run --batch-size 50 --model gpt-5.4-mini
        → DB: 일부 row가 tagging_status='review_needed' 상태로 영속됨
2pass:  python -m langgraph_tagger escalate --since "2026-05-08T09:00" --model gpt-5.4
        → 1pass에서 review_needed로 빠진 row만 row_ids로 강제 재처리
```

`escalate` 서브커맨드는 내부적으로 다음 SQL을 먼저 실행해 `row_ids`를 만든다:

```sql
select id from reports
 where tagging_status = 'review_needed'
   and tagged_at >= $since
```

그 후 같은 그래프를 `--row-ids <list> --model gpt-5.4`로 호출. spec §"호출 패턴"의 `row_ids` 분기를 그대로 사용 — atomic claim 건너뛰고 명시 ID들만 처리, status가 `'pending'`이 아니어도 강제.

### 6.3 디렉토리 구조

```
telegram_report/
├── collector.py / storage.py / main.py / ...   # 기존, 수정 없음
├── migrations/
│   ├── 001_init.sql                             # 기존
│   └── 002_tagging_columns.sql                  # friendly-mclaren에서 이식
├── docs/stock_data/
│   └── KRX_stocks_data.csv                      # friendly-mclaren에서 이식
├── docs/superpowers/specs/
│   └── 2026-05-08-langgraph-tagger-design.md   # 본 문서
│
└── langgraph_tagger/                            # ← 새 패키지
    ├── __init__.py
    ├── __main__.py                              # CLI 엔트리
    ├── cli.py                                   # argparse, 서브커맨드 분기
    ├── config.py                                # env 로딩 + dataclass
    ├── orchestrator.py                          # batch 루프, claim, gather+Semaphore
    ├── graph.py                                 # StateGraph 조립
    ├── state.py                                 # TypedDict RowState
    ├── llm_schemas.py                           # Pydantic LLMExtraction, OOSSignals
    ├── supabase_io.py                           # SQL 실행 어댑터
    ├── prompts.py                               # SYSTEM_PROMPT 빌더
    ├── nodes/
    │   ├── __init__.py
    │   ├── extract_pdf.py
    │   ├── llm_extract.py
    │   ├── oos_gate.py
    │   ├── status_oos.py
    │   ├── canonicalize.py
    │   ├── validate.py
    │   ├── enrich.py
    │   ├── decide_status.py
    │   └── write.py
    ├── vocabulary/
    │   ├── __init__.py                          # 로딩 + 룩업 함수 export
    │   ├── publishers.yaml
    │   ├── topics.yaml
    │   ├── taxonomy.yaml                        # 14종 enum + precedence rule (참조용)
    │   └── krx.py                               # KRXIndex 클래스
    └── tests/
        ├── conftest.py
        ├── test_extract_pdf.py
        ├── test_oos_gate.py
        ├── test_canonicalize.py
        ├── test_validate.py
        ├── test_enrich.py
        ├── test_decide_status.py
        ├── test_orchestrator.py
        └── golden/
            └── *.pdf                             # 14 type + 4 OOS 케이스
```

### 6.4 CLI

```bash
# 일상: pending에서 mini로 N건
python -m langgraph_tagger run --batch-size 50 --model gpt-5.4-mini

# 분포만 (처리 없음)
python -m langgraph_tagger inspect

# dry-run preview (status 변경 없음, JSON 결과만)
python -m langgraph_tagger run --batch-size 10 --dry-run

# escalation: 1pass 후 review_needed 행만 gpt-5.4로 재처리
python -m langgraph_tagger escalate --since "2026-05-08T09:00" --model gpt-5.4

# 명시 row 디버그
python -m langgraph_tagger run --row-ids 1234,1235 --model gpt-5.4
```

기본 모델은 env `OPENAI_MODEL_DEFAULT` (`gpt-5.4-mini`). escalation 모델은 `OPENAI_MODEL_ESCALATION` (`gpt-5.4`).

## 7. 데이터 모델

### 7.1 LangGraph state (TypedDict)

`state.py`. 모든 키 `total=False` — 노드가 일부만 채우는 패턴.

```python
from typing import Optional, Literal
from typing_extensions import TypedDict
from datetime import date, datetime

class RowState(TypedDict, total=False):
    # 입력 (claim 직후)
    id: int
    file_path: str
    file_name: str
    sent_at: datetime           # UTC
    caption: Optional[str]
    chat_username: str
    worker_id: str
    model: str

    # extract_pdf 출력
    pdf_text: str
    pages_used: list[int]
    pdf_unreadable: bool

    # llm_extract 출력
    llm_raw: "LLMExtraction"    # Pydantic instance
    llm_refusal: Optional[str]

    # oos_gate 출력
    is_oos: bool
    oos_reason: Optional[Literal["foreign","fund","digital","private"]]

    # canonicalize 출력
    publisher_canon: Optional[str]
    publisher_type: Optional[Literal["broker","company","data_provider","ir_agency","other"]]
    topics_canon: list[str]
    topic_unmapped: list[str]

    # validate 출력
    stock_codes_valid: list[str]
    stock_codes_unknown: list[str]
    sectors_major_valid: list[str]
    sectors_minor_valid: list[str]
    sectors_unknown: list[str]

    # enrich 출력
    company_names_final: list[str]
    sectors_major_final: list[str]
    sectors_minor_final: list[str]
    products_final: list[str]
    published_at_final: Optional[date]
    used_sent_at_fallback: bool

    # decide_status 출력
    tagging_status: Literal["auto","review_needed"]
    tagging_confidence: Literal["high","medium","low"]
    tagging_notes: Optional[str]
```

LangGraph 1.0 표준 패턴 (TypedDict + 부분 업데이트).

### 7.2 LLM 추출 schema (Pydantic, OpenAI structured output)

`llm_schemas.py`. 한 번의 `client.chat.completions.parse()`가 받아내는 모든 후보:

```python
from typing import Optional, Literal
from pydantic import BaseModel, Field

REPORT_TYPES = Literal[
    "단일종목","산업","섹터","시황·데일리","거시·매크로","퀀트·전략",
    "전략·테마","IPO","ESG","부동산·리츠","파생·원자재","채권·크레딧",
    "IR자료","기타",
]

class OOSSignals(BaseModel):
    """LLM-observed primary-coverage signals. 'primary coverage'를 강조해
    국내 리포트의 해외 peer/벨류체인 언급은 false로 처리.
    """
    foreign_primary_coverage: bool   # primary coverage가 해외 상장사 (peer 언급은 false)
    etf_or_fund: bool
    digital_asset: bool
    private_company_likely: bool

class LLMExtraction(BaseModel):
    report_type: REPORT_TYPES
    title: Optional[str] = Field(None, max_length=120)
    published_at: Optional[str] = None        # YYYY-MM-DD or null

    stock_codes_raw: list[str]
    company_names: list[str]
    sectors_major: list[str]
    sectors_minor: list[str]
    products: list[str]

    publisher_raw: Optional[str] = None
    analysts: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)

    oos_signals: OOSSignals
    self_confidence: Literal["high","medium","low"]
    notes: Optional[str] = None
```

호출:

```python
completion = await client.chat.completions.parse(
    model=state["model"],
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": _user_msg(state)},
    ],
    response_format=LLMExtraction,
    temperature=0,
)
```

### 7.3 Vocabulary YAML

#### `publishers.yaml` (예시)

```yaml
broker:
  - canonical: 키움증권
    aliases: ["키움", "키움증권 리서치센터", "Kiwoom Securities"]
  - canonical: NH투자증권
    aliases: ["NH투자", "NH 투자증권"]

data_provider:
  - canonical: FnGuide
    aliases: ["FN가이드", "에프엔가이드"]
  - canonical: KIRS
    aliases: []

ir_agency:
  - canonical: IRKUDOS
    aliases: ["IR쿠도스"]
  - canonical: dyneasset
    aliases: ["다인에셋"]
  - canonical: GL Research
    aliases: ["GL리서치"]
```

friendly-mclaren의 `references/publishers.md`에 적힌 항목을 그대로 옮긴다.

#### `topics.yaml`

```yaml
- canonical: FOMC
  aliases: ["연준", "Fed", "미연준", "Federal Reserve"]
- canonical: 미국금리
  aliases: ["US금리", "미 금리", "미국기준금리"]
```

#### `taxonomy.yaml`

```yaml
report_types: [단일종목, 산업, 섹터, 시황·데일리, 거시·매크로, 퀀트·전략,
                전략·테마, IPO, ESG, 부동산·리츠, 파생·원자재, 채권·크레딧,
                IR자료, 기타]
oos_reasons: [foreign, fund, digital, private]
publisher_types: [broker, company, data_provider, ir_agency, other]

# 사람·LLM 참조용 (코드는 hard-coded enum 사용)
precedence_rules:
  - "OOS 패턴은 모든 분류에 우선"
  - "자산군이 prefix보다 우선"
  - "상장사 IPO 업데이트 vs IPO: KRX에 이미 상장된 기업은 단일종목"
  - "IPO vs OOS private: KRX 매칭 시 in-scope, 미매칭 + 비상장 컨텍스트만 OOS private"
  - "publisher_type='company' 자체 IR은 비상장사여도 OOS private 아님 (IR자료로 in-scope)"
  - "prefix 모호 시 첫 페이지 헤더 키워드로 분류, 추출 불가 시 type_indeterminate"
```

#### `vocabulary/__init__.py` (룩업 API)

```python
def lookup_publisher(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """raw publisher 문자열 → (canonical, publisher_type) or (None, None)."""

def map_topics(raw: list[str]) -> tuple[list[str], list[str]]:
    """raw topics → (canonical_list, unmapped_list)."""
```

매칭 룰: 정규화(공백·구두점 제거) 후 canonical/aliases와 정확 매칭. 부분 매칭은 하지 않음 (false positive 위험).

### 7.4 KRX 인덱스

`vocabulary/krx.py`:

```python
from dataclasses import dataclass
from pathlib import Path
import csv

@dataclass(frozen=True)
class KRXEntry:
    code: str           # ^[0-9A-Z]{6}$
    name: str
    market: str         # KOSPI / KOSDAQ / KOSDAQ GLOBAL
    sector_major: str
    sector_minor: str
    products_text: str  # 자유 텍스트 ("DRAM, NAND 등")

class KRXIndex:
    def __init__(self, entries: list[KRXEntry], csv_path: Path):
        self.by_code = {e.code: e for e in entries}
        self.sectors_major = {e.sector_major for e in entries if e.sector_major}
        self.sectors_minor = {e.sector_minor for e in entries if e.sector_minor}
        self.taxonomy_version = self._build_version(csv_path)

    @classmethod
    def load(cls, csv_path: Path) -> "KRXIndex":
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = [c.replace("\n", "").strip() for c in next(reader)]
            assert header == ['종목코드','종목명','시장','산업명(대)','산업명(중)','주요제품']
            entries = [KRXEntry(*row) for row in reader]
        return cls(entries, csv_path)

    def validate_code(self, code: str) -> bool:
        import re
        return bool(re.fullmatch(r"[0-9A-Z]{6}", code)) and code in self.by_code

    def lookup(self, code: str) -> Optional[KRXEntry]:
        return self.by_code.get(code)

    def split_products(self, products_text: str) -> list[str]:
        """ "MLCC, 기판, 카메라 모듈 등" → ['MLCC','기판','카메라 모듈']
            "DRAM, NAND 등"           → ['DRAM','NAND']
        Trailing ' 등' 접미사도 제거 (KRX CSV에 흔한 형태).
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

    def fuzzy_sector_match(self, value: str) -> Optional[str]:
        """alias 매핑 (예: '자동차'/'Auto'/'자동차산업' → 정규형). 도메인 외면 None."""
        norm = value.replace(" ", "").lower()
        for s in self.sectors_major | self.sectors_minor:
            if s.replace(" ", "").lower() == norm: return s
        # 추가 alias 룰은 vocabulary/taxonomy.yaml에 보강 가능
        return None

    def has_product(self, product_token: str) -> bool:
        """True if product_token appears as substring in any KRX row's products_text.
        validate가 사용해 products_valid / products_unknown으로 분리한다.
        silent drop 안 함 — 원 spec §6.6 정책 보존.
        """
        return any(product_token in e.products_text for e in self.by_code.values())

    def rows_with_product(self, product_token: str) -> list[KRXEntry]:
        """주요제품 셀에 product_token이 substring으로 들어간 KRX 행."""
        return [e for e in self.by_code.values() if product_token in e.products_text]

    def rows_with_sector_minor(self, sector_minor: str) -> list[KRXEntry]:
        return [e for e in self.by_code.values() if e.sector_minor == sector_minor]

    @staticmethod
    def _build_version(csv_path: Path) -> str:
        from datetime import datetime
        ts = datetime.fromtimestamp(csv_path.stat().st_mtime)
        return f"KRX@{ts:%Y-%m-%d}"
```

CSV 헤더 정규화 (`종목\n코드` → `종목코드`)는 원 spec §"KRX CSV 로딩"의 요구사항.

## 8. 노드별 동작

각 노드는 `RowState`의 일부 키를 받아 일부 키를 반환한다 (LangGraph 1.0 부분 업데이트 패턴).

### 8.1 `extract_pdf`

```python
import fitz  # PyMuPDF
import asyncio

async def extract_pdf(state: RowState) -> dict:
    path = Path(STORAGE_BASE_DIR) / state["file_path"]
    return await asyncio.to_thread(_sync_extract, path)

def _sync_extract(path: Path) -> dict:
    try:
        doc = fitz.open(path)
    except Exception:
        return {"pdf_text": "", "pages_used": [], "pdf_unreadable": True}
    pages_used, parts = [], []
    for i in range(min(5, doc.page_count)):
        text = doc[i].get_text("text")
        parts.append(text)
        pages_used.append(i + 1)
        if _has_meta_signals(text):  # 분석가/발행처/투자의견 등 헤더
            break
    doc.close()
    pdf_text = "\n".join(parts).strip()
    return {"pdf_text": pdf_text, "pages_used": pages_used,
            "pdf_unreadable": not pdf_text}
```

원 spec §3.a 준수: 1p 부족 시 최대 5p까지 폴백. 폴백 자체는 review_needed 사유가 아님 (decide_status에서 confidence=medium 정도로만 영향).

### 8.2 `llm_extract`

```python
async def llm_extract(state: RowState, *, client: AsyncOpenAI) -> dict:
    if state.get("pdf_unreadable"):
        return {"llm_raw": None}      # decide_status가 first_page_unreadable 처리
    try:
        completion = await client.chat.completions.parse(
            model=state["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": _user_msg(state)},
            ],
            response_format=LLMExtraction,
            temperature=0,
        )
    except (RateLimitError, APITimeoutError, InternalServerError) as e:
        raise OpenAITransientError(str(e))   # orchestrator가 pending 되돌림
    msg = completion.choices[0].message
    if msg.refusal:
        return {"llm_raw": None, "llm_refusal": msg.refusal}
    return {"llm_raw": msg.parsed}
```

`SYSTEM_PROMPT`(prompts.py)에 박는 내용:
- 14종 `report_type` enum + 각 정의 (taxonomy.yaml에서 빌드)
- precedence rule 5개 (자연어로)
- OOS 4종 신호 정의 + 예시
- 보수적 추출 룰 ("본문 등장 종목 ≠ 추출. 첫 페이지 헤더 명시 종목만.")
- "publisher는 자유 텍스트로", "topics는 자유 추출"

`temperature=0`으로 일관성 우선. 한국어 분류에 mini는 충분 (5.4 mini의 SWE-bench 점수가 5.4 standard에 매우 근접).

### 8.3 `oos_gate` (3-way 조건부 분기, routing-only)

LangGraph 1.0의 `add_conditional_edges` routing function은 string label만 반환해야 한다 (state mutation 금지). `oos_reason` set은 별도 노드 `mark_oos_reason`이 담당한다.

```python
def oos_gate(state: RowState, *, krx: KRXIndex) -> Literal["mark_oos_reason", "status_unreadable", "canonicalize"]:
    """Routing only — does NOT mutate state."""
    # 0. 추출 실패는 OOS가 아니라 별도 경로
    if state.get("pdf_unreadable") or state.get("llm_refusal"):
        return "status_unreadable"

    raw = state.get("llm_raw")
    if raw is None:
        return "status_unreadable"

    sig = raw.oos_signals

    # 1. OOS 신호 (있으면 mark_oos_reason이 사유 결정)
    if sig.foreign_primary_coverage or sig.etf_or_fund or sig.digital_asset:
        return "mark_oos_reason"

    # 2. private_company_likely는 §6.5 룰 4 예외 적용
    if sig.private_company_likely:
        # KRX 매칭 코드 1개 이상 → in-scope (룰 4 첫째)
        if any(krx.validate_code(c) for c in raw.stock_codes_raw):
            return "canonicalize"
        # IR자료 후보 → in-scope (룰 4 셋째: 자체 IR은 OOS private 아님)
        if raw.report_type == "IR자료":
            return "canonicalize"
        # IPO 후보 + KRX 미매칭 → in-scope IPO 유지 (룰 4 둘째)
        if raw.report_type == "IPO":
            return "canonicalize"
        return "mark_oos_reason"

    return "canonicalize"
```

#### 8.3.1 `mark_oos_reason` 노드

`oos_gate`가 `"mark_oos_reason"`을 반환하면 이 노드가 정확한 `oos_reason`을 결정·기록 후 `status_oos`로 진입.

```python
def mark_oos_reason(state: RowState) -> dict:
    sig = state["llm_raw"].oos_signals
    if sig.foreign_primary_coverage:
        return {"is_oos": True, "oos_reason": "foreign"}
    if sig.etf_or_fund:
        return {"is_oos": True, "oos_reason": "fund"}
    if sig.digital_asset:
        return {"is_oos": True, "oos_reason": "digital"}
    # 여기 도달 = private_company_likely (룰 4 예외 모두 false 통과)
    return {"is_oos": True, "oos_reason": "private"}
```

LangGraph `add_conditional_edges`에 3-way 매핑:
```python
g.add_conditional_edges("llm_extract", partial(oos_gate, krx=KRX), {
    "mark_oos_reason":   "mark_oos_reason",
    "status_unreadable": "status_unreadable",
    "canonicalize":      "canonicalize",
})
g.add_edge("mark_oos_reason", "status_oos")
```

### 8.4 `status_oos`

```python
def status_oos(state: RowState) -> dict:
    reason = state["oos_reason"]
    confidence = "high" if reason in ("foreign","fund","digital") else "medium"
    return {
        "is_oos": True,
        "tagging_status": "auto",
        "tagging_confidence": confidence,
        "tagging_notes": None,
        # write 단에서 OOS payload 빌드 시 사용:
        # - report_type='기타' 강제
        # - out_of_scope_reason=reason
        # - 분류 메타 빈 값
        # - title/published_at은 LLM 추출 그대로 (있으면)
    }
```

원 spec §6.6 OOS 케이스 룰 (write 단에서 강제 적용):
- `report_type='기타'` 강제 (LLM이 다른 type을 뽑았어도 OOS 경로면 덮어씀)
- 분류 메타(`stock_codes`, `sectors_*`, `products`, `topics`, `analysts`, `publisher`, `publisher_type`, `company_names`)는 빈 배열·NULL
- `title`은 LLM 추출 그대로 저장 (검색용)
- `published_at`은 LLM 추출 가능하면 채움, 그 외 NULL (sent_at 폴백 안 함 — OOS는 시계열 트레이싱 대상 아님)
- `tagging_notes`는 NULL (검토 메모와 분리)

### 8.4.1 `status_unreadable`

```python
def status_unreadable(state: RowState) -> dict:
    if state.get("pdf_unreadable"):
        notes = "first_page_unreadable"
    else:  # llm_refusal
        notes = f"llm_refusal:{state.get('llm_refusal','')}"
    return {
        "tagging_status": "review_needed",
        "tagging_confidence": "low",
        "tagging_notes": notes,
    }
```

write 단에서 분류 메타는 모두 빈 값/NULL. `report_type`도 NULL (분류 시도 자체가 실패한 케이스).

### 8.5 `canonicalize` (in-scope 진입 시)

```python
def canonicalize(state: RowState) -> dict:
    raw = state["llm_raw"]
    pub_canon, pub_type = lookup_publisher(raw.publisher_raw)
    topics_canon, topic_unmapped = map_topics(raw.topics)
    return {
        "publisher_canon": pub_canon,
        "publisher_type": pub_type,
        "topics_canon": topics_canon,
        "topic_unmapped": topic_unmapped,
    }
```

publisher 룩업 실패(`publisher_canon=None`)는 decide_status에서 `review_needed/low + notes='unknown_publisher:<value>'`로 처리한다 (원 spec 2026-05-07 §6.6 정책 보존). canonicalize 노드 자체는 정책을 모르고 단순 룩업 결과만 반환한다.

topic 미매핑은 그대로 채택 (자유 어휘). confidence만 medium으로 떨어지며 review_needed 아님.

analysts는 vocabulary 매핑이 없다 (Option γ) — LLM이 추출한 raw 이름 그대로 `analysts text[]`에 적재한다.

### 8.6 `validate`

```python
def validate(state: RowState) -> dict:
    raw = state["llm_raw"]
    valid_codes, unknown_codes = [], []
    for c in raw.stock_codes_raw:
        if not re.fullmatch(r"[0-9A-Z]{6}", c):
            unknown_codes.append(c); continue
        (valid_codes if KRX.validate_code(c) else unknown_codes).append(c)

    smajor_valid, sminor_valid, s_unknown = [], [], []
    for s in raw.sectors_major:
        m = KRX.fuzzy_sector_match(s)
        if m and m in KRX.sectors_major: smajor_valid.append(m)
        else:                            s_unknown.append(s)
    for s in raw.sectors_minor:
        m = KRX.fuzzy_sector_match(s)
        if m and m in KRX.sectors_minor: sminor_valid.append(m)
        else:                            s_unknown.append(s)

    # products: KRX substring 멤버십 검증 (원 spec §6.6 정책 — silent drop 안 함)
    products_valid, products_unknown = [], []
    for p in raw.products:
        if KRX.has_product(p):
            products_valid.append(p)
        else:
            products_unknown.append(p)

    return {
        "stock_codes_valid": valid_codes,
        "stock_codes_unknown": unknown_codes,
        "sectors_major_valid": smajor_valid,
        "sectors_minor_valid": sminor_valid,
        "sectors_unknown": s_unknown,
        "products_valid": products_valid,
        "products_unknown": products_unknown,
    }
```

`unknown_codes`/`sectors_unknown`/`products_unknown`이 비지 않았는데 OOS 패턴도 아니면 decide_status에서 `review_needed/low` 트리거 (원 spec §6.6 정책).

### 8.7 `enrich`

```python
def enrich(state: RowState) -> dict:
    raw = state["llm_raw"]
    company_names = list(raw.company_names)
    sectors_major = list(state["sectors_major_valid"])
    sectors_minor = list(state["sectors_minor_valid"])
    products = list(state["products_valid"])  # validate가 KRX 멤버십 검증한 결과만 입력

    # 단일종목/IR/IPO + KRX 매칭 → 자동 보강
    if raw.report_type in ("단일종목","IR자료","IPO"):
        for code in state["stock_codes_valid"]:
            entry = KRX.lookup(code)
            if not entry: continue
            if entry.name not in company_names: company_names.append(entry.name)
            if entry.sector_major and entry.sector_major not in sectors_major:
                sectors_major.append(entry.sector_major)
            if entry.sector_minor and entry.sector_minor not in sectors_minor:
                sectors_minor.append(entry.sector_minor)
            for tok in KRX.split_products(entry.products_text):
                if tok not in products: products.append(tok)

    # 산업 깊이 합류: products → minor/major, minor → major (원 spec §6.3)
    # validate가 이미 substring 멤버십 검증함. 여기서 다시 필터링 안 함.
    for p in products:
        for entry in KRX.rows_with_product(p):
            if entry.sector_minor and entry.sector_minor not in sectors_minor:
                sectors_minor.append(entry.sector_minor)
            if entry.sector_major and entry.sector_major not in sectors_major:
                sectors_major.append(entry.sector_major)
    for sm in list(sectors_minor):
        for entry in KRX.rows_with_sector_minor(sm):
            if entry.sector_major and entry.sector_major not in sectors_major:
                sectors_major.append(entry.sector_major)

    # published_at 폴백
    pub = _parse_iso_date(raw.published_at)
    used_fallback = False
    if pub is None:
        sent_at_kst = state["sent_at"].astimezone(KST).date()
        pub = sent_at_kst
        used_fallback = True

    return {
        "company_names_final": company_names,
        "sectors_major_final": sectors_major,
        "sectors_minor_final": sectors_minor,
        "products_final": products,
        "published_at_final": pub,
        "used_sent_at_fallback": used_fallback,
    }
```

products 필터링 (원 spec §3.d/§6.6): LLM이 뱉은 product 토큰이 KRX CSV의 어떤 row의 `주요제품` 셀에든 substring으로 등장해야 `products_valid`에 채택. 등장 안 하면 `products_unknown`에 들어가 decide_status가 `review_needed/low/notes='unknown_product:<value>'`로 처리. silent drop 안 함 — 원 spec §6.6 정책 보존.

### 8.8 `decide_status`

원 spec §6.6 결정 트리를 코드 함수 하나로 (이 노드가 사용자 우려 해소의 핵심):

```python
def decide_status(state: RowState) -> dict:
    # 0. 가독 실패 케이스
    if state.get("pdf_unreadable"):
        return {"tagging_status":"review_needed", "tagging_confidence":"low",
                "tagging_notes":"first_page_unreadable"}
    if state.get("llm_refusal"):
        return {"tagging_status":"review_needed", "tagging_confidence":"low",
                "tagging_notes": f"llm_refusal:{state['llm_refusal']}"}

    notes: list[str] = []
    raw = state.get("llm_raw")

    # 1. type_indeterminate (in-scope만)
    if (raw is not None and raw.report_type == "기타"
            and raw.self_confidence == "low" and not state.get("is_oos")):
        notes.append("type_indeterminate")

    # 2. 검증 실패 수집 (in-scope만) — 원 spec §6.6 정책:
    #    unknown_stock_code / unknown_sector / unknown_product / unknown_publisher
    #    네 개 모두 review_needed/low 트리거.
    if not state.get("is_oos"):
        if state.get("stock_codes_unknown"):
            notes.append("unknown_stock_code:" + ",".join(state["stock_codes_unknown"]))
        if state.get("sectors_unknown"):
            notes.append("unknown_sector:" + ",".join(state["sectors_unknown"]))
        if state.get("products_unknown"):
            notes.append("unknown_product:" + ",".join(state["products_unknown"]))
        if state.get("publisher_canon") is None and raw is not None and raw.publisher_raw:
            notes.append(f"unknown_publisher:{raw.publisher_raw}")

    has_validation_failure = any(
        n.startswith(("unknown_stock_code:", "unknown_sector:",
                      "unknown_product:", "unknown_publisher:",
                      "type_indeterminate"))
        for n in notes
    )
    if has_validation_failure:
        return {"tagging_status":"review_needed", "tagging_confidence":"low",
                "tagging_notes":";".join(notes)}

    # 3. auto 케이스 — confidence는 폴백·페이지 fallback·새 토픽으로 결정
    used_fallback = (
        state.get("used_sent_at_fallback")
        or bool(state.get("topic_unmapped"))
        or len(state.get("pages_used") or [1]) > 1
    )

    return {
        "tagging_status": "auto",
        "tagging_confidence": "medium" if used_fallback else "high",
        "tagging_notes": ";".join(notes) if notes else None,
    }
```

이 함수 한 개가 원 spec §6.6의 모든 분기를 표현. **단위 테스트로 LLM 호출 0회로 모든 케이스를 커버**할 수 있음 (test_decide_status.py). 정책: `unknown_stock_code`/`unknown_sector`/`unknown_product`/`unknown_publisher` 모두 `review_needed/low` (원 spec 2026-05-07 §6.6 그대로).

### 8.9 `write`

```python
async def write(state: RowState, *, sb: SupabaseSQL, dry_run: bool) -> dict:
    if dry_run:
        return {}  # 결과는 _aggregate_report에서 state 자체로 수집
    payload = _build_update_payload(state)
    await sb.execute(UPDATE_REPORTS_SQL, payload)
    return {}
```

OOS 경로의 row는 분류 메타(`stock_codes`, `company_names`, `sectors_*`, `products`, `topics`, `analysts`, `publisher`, `publisher_type`)가 빈 배열·NULL로 set. `report_type='기타'`, `out_of_scope_reason=<oos_reason>` 강제.
in-scope 경로의 row는 `enrich`가 채운 final 값 + `decide_status`가 정한 status/confidence/notes 사용.

공통: `tagging_locked_at=NULL`, `tagging_worker_id=NULL`, `tagged_at=now()`, `tagger_version='langgraph-tagger@1.0'`, `taxonomy_version=KRX.taxonomy_version`.

### 8.10 그래프 조립

```python
# graph.py
from langgraph.graph import StateGraph, START, END
from functools import partial

def build_graph(client, sb, *, krx, dry_run: bool, taxonomy_version: str):
    g = StateGraph(RowState)
    g.add_node("extract_pdf", extract_pdf)
    g.add_node("llm_extract", partial(llm_extract, client=client))
    g.add_node("mark_oos_reason", mark_oos_reason)         # §8.3.1 — sets is_oos/oos_reason
    g.add_node("status_oos", status_oos)
    g.add_node("status_unreadable", status_unreadable)
    g.add_node("canonicalize", canonicalize)
    g.add_node("validate", partial(validate, krx=krx))
    g.add_node("enrich", partial(enrich, krx=krx))
    g.add_node("decide_status", decide_status)
    g.add_node("write", partial(write, sb=sb, dry_run=dry_run, taxonomy_version=taxonomy_version))

    g.add_edge(START, "extract_pdf")
    g.add_edge("extract_pdf", "llm_extract")
    # oos_gate는 routing-only — state mutation 없이 label만 반환.
    # mark_oos_reason 별도 노드가 is_oos/oos_reason set 후 status_oos로 진입.
    g.add_conditional_edges("llm_extract", partial(oos_gate, krx=krx), {
        "mark_oos_reason":   "mark_oos_reason",
        "status_unreadable": "status_unreadable",
        "canonicalize":      "canonicalize",
    })
    g.add_edge("mark_oos_reason", "status_oos")
    g.add_edge("status_oos", "write")
    g.add_edge("status_unreadable", "write")
    g.add_edge("canonicalize", "validate")
    g.add_edge("validate", "enrich")
    g.add_edge("enrich", "decide_status")
    g.add_edge("decide_status", "write")
    g.add_edge("write", END)
    return g.compile()
```

## 9. 운영

### 9.1 Supabase 연동 (SQL via asyncpg)

`supabase_io.py`. **`SUPABASE_DB_URL` (직접 Postgres 연결 string)** 으로 `asyncpg` 풀을 만들어 raw SQL을 실행한다. supabase-py는 PostgREST 래퍼라서 `FOR UPDATE SKIP LOCKED` 같은 트랜잭션·락 SQL을 RPC 함수 등록 없이 실행하기 어렵다 — 본 spec은 SQL 투명성을 위해 asyncpg 직접 사용.

기존 master의 `storage.py`(supabase-py 사용)와 분리된 어댑터 1개. master env (`SUPABASE_URL`/`SUPABASE_SERVICE_KEY`)는 collector가 계속 사용, tagger는 새 env `SUPABASE_DB_URL`만 읽음.

asyncpg는 `$1, $2, ...` 위치 placeholder만 지원한다 (named placeholder 지원 안 함). 모든 SQL은 위치 인자로 작성.

```python
# 핵심 SQL (원 spec §6.7과 일치)

STALE_LOCK_RECLAIM_SQL = """
UPDATE reports
   SET tagging_status='pending', tagging_locked_at=NULL, tagging_worker_id=NULL
 WHERE tagging_status='processing'
   AND tagging_locked_at < now() - ($1::int * interval '1 minute')
"""

ATOMIC_CLAIM_SQL = """
UPDATE reports
   SET tagging_status='processing',
       tagging_locked_at=now(),
       tagging_worker_id=$1
 WHERE id IN (
       SELECT id FROM reports
        WHERE tagging_status='pending'
        ORDER BY downloaded_at ASC
        LIMIT $2
        FOR UPDATE SKIP LOCKED
       )
RETURNING id, file_path, file_name, sent_at, caption, chat_username
"""

DRY_RUN_SELECT_SQL = """
SELECT id, file_path, file_name, sent_at, caption, chat_username
  FROM reports
 WHERE tagging_status='pending'
 ORDER BY downloaded_at ASC
 LIMIT $1
"""

ROW_IDS_FETCH_SQL = """
SELECT id, file_path, file_name, sent_at, caption, chat_username
  FROM reports
 WHERE id = ANY($1::bigint[])
"""

REVERT_TO_PENDING_SQL = """
UPDATE reports
   SET tagging_status='pending', tagging_locked_at=NULL, tagging_worker_id=NULL
 WHERE id=$1 AND tagging_status='processing'
"""

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
       sectors_major=$10,
       sectors_minor=$11,
       products=$12,
       topics=$13,
       out_of_scope_reason=$14,
       tagging_status=$15,
       tagging_confidence=$16,
       tagging_notes=$17,
       tagging_locked_at=NULL,
       tagging_worker_id=NULL,
       tagged_at=now(),
       tagger_version='langgraph-tagger@1.0',
       taxonomy_version=$18
 WHERE id=$1
"""
# Bind args order: (id, published_at, report_type, publisher, publisher_type,
#                   analysts, title, stock_codes, company_names,
#                   sectors_major, sectors_minor, products, topics,
#                   out_of_scope_reason, tagging_status, tagging_confidence,
#                   tagging_notes, taxonomy_version)

ESCALATION_PICK_SQL = """
SELECT id FROM reports
 WHERE tagging_status='review_needed'
   AND tagged_at >= $1
"""

INSPECT_SUMMARY_SQL = """
SELECT tagging_status, count(*) FROM reports GROUP BY 1
UNION ALL
SELECT 'oos:'||COALESCE(out_of_scope_reason,'none'), count(*)
  FROM reports GROUP BY 2
"""
```

### 9.2 Orchestrator (배치 루프)

`lock_ttl_minutes`/`per_row_deadline_s`는 module-level 상수가 아니라 `run_batch()`의 명시 인자다. `cli.py`가 `load_config()`로 dotenv 로드 후 `cfg.lock_ttl_minutes` / `cfg.per_row_deadline_s`를 그대로 넘긴다. 이렇게 하면 orchestrator 모듈이 import-order에 따라 dotenv 전 env를 캐시하는 함정이 사라진다.

```python
# orchestrator.py
async def run_batch(
    *,
    sb,
    client,
    krx,
    taxonomy_version: str,
    batch_size: int,
    dry_run: bool,
    row_ids: list[int],
    model: str,
    max_concurrent_llm: int,
    worker_id: str,
    lock_ttl_minutes: int = 30,
    per_row_deadline_s: float = 90.0,
):
    if not row_ids and not dry_run:
        await sb.execute(STALE_LOCK_RECLAIM_SQL, [lock_ttl_minutes])

    if row_ids:
        rows = await sb.fetch(ROW_IDS_FETCH_SQL, [row_ids])
    elif dry_run:
        rows = await sb.fetch(DRY_RUN_SELECT_SQL, [batch_size])
    else:
        rows = await sb.fetch(ATOMIC_CLAIM_SQL, [worker_id, batch_size])

    if not rows: return _empty_report(model)

    app = build_graph(client, sb, krx=krx, dry_run=dry_run, taxonomy_version=taxonomy_version)
    sem = asyncio.Semaphore(max_concurrent_llm)

    async def _revert(row_id: int) -> None:
        if not dry_run and not row_ids:
            try:
                await sb.execute(REVERT_TO_PENDING_SQL, [row_id])
            except Exception:
                # REVERT가 실패하면 row가 'processing'으로 남고 stale-lock
                # 회수가 lock_ttl_minutes 후 복구.
                pass

    async def _process(row):
        async with sem:
            init_state = {**row, "worker_id": worker_id, "model": model}
            try:
                final = await asyncio.wait_for(app.ainvoke(init_state),
                                                timeout=per_row_deadline_s)
                return {"id": row["id"], **final}
            except OpenAITransientError as e:
                await _revert(row["id"])
                return {"id": row["id"], "error": "transient", "detail": str(e)}
            except asyncio.TimeoutError:
                await _revert(row["id"])
                return {"id": row["id"], "error": "deadline_exceeded"}
            except Exception as e:
                # broad except로 gather() burst 방지.
                await _revert(row["id"])
                return {"id": row["id"], "error": "unhandled",
                        "detail": f"{type(e).__name__}:{e}"}

    results = await asyncio.gather(*[_process(r) for r in rows])
    return _aggregate_report(results, dry_run=dry_run, model=model)
```

**heartbeat (v1 미구현 — 후일 옵션)**: 매우 큰 PDF로 `per_row_deadline_s`가 길어져야 할 때, 워커가 처리 중 `tagging_locked_at = now()`를 주기적으로 갱신해 stale-lock 회수가 살아있는 워커를 잘못 회수하지 않게 한다. 구현 스케치: `extract_pdf` 직후 `asyncio.create_task(_heartbeat(sb, row_id, heartbeat_interval_s))`로 시작 후 `write` 진입 시 cancel. **본 v1에서는 구현하지 않음** — 운영 안전 제약 `lock_ttl_minutes * 60 > per_row_deadline_s`만 지키면 충분. config는 `heartbeat_enabled=false` / `heartbeat_interval_s=30`을 미래 호환을 위해 보존하지만 `run_batch()`에 전달하지 않는다 (Task 추가 없이 v2에서 도입).

### 9.3 에러 처리 / 재시도

| 실패 종류 | 처리 |
|---|---|
| OpenAI 429 / 5xx / 타임아웃 | `OpenAITransientError` → REVERT to pending. SDK 자체 `max_retries=2`로 1차 흡수, 그래도 실패하면 위 처리. |
| OpenAI refusal | `review_needed/low/notes='llm_refusal:<reason>'`로 정상 write. |
| Pydantic 파싱 실패 (`parse()` 예외) | `OpenAITransientError`로 wrapping → REVERT to pending. 다른 모델로 escalation 가능. |
| PyMuPDF 예외 (PDF 손상) | `pdf_unreadable=True` → `status_unreadable` 노드 → `review_needed/low/first_page_unreadable`로 write. |
| asyncio per-row timeout | `PER_ROW_DEADLINE_S` 초과 → REVERT to pending, `error='deadline_exceeded'`로 보고. |
| 알 수 없는 예외 (네트워크 일시 끊김, asyncpg 일시 오류, 노드 코드 버그) | broad except → REVERT to pending, `error='unhandled'`로 보고. row가 영구적으로 처리 안 되는 것 방지. |
| Supabase write 실패 (REVERT까지 실패) | row가 `processing`으로 남음. 다음 실행의 stale-lock 회수가 `LOCK_TTL_MINUTES` 후 복구. |
| `asyncio.gather` 자체 폭주 | broad except로 모두 격리되므로 `gather`는 raise 안 함 (return_exceptions 효과). |

`row_ids` 모드에서는 `REVERT_TO_PENDING`을 호출하지 않음 — 사용자가 명시한 ID는 status를 건드리지 않는다는 원 spec 룰 준수.

### 9.4 환경 변수

`.env.example`에 추가:

```
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL_DEFAULT=gpt-5.4-mini
OPENAI_MODEL_ESCALATION=gpt-5.4

# Tagger
MAX_CONCURRENT_LLM=10
TAGGER_BATCH_SIZE_DEFAULT=10
KRX_CSV_PATH=docs/stock_data/KRX_stocks_data.csv
TAGGER_VERSION=langgraph-tagger@1.0

# Concurrency / safety knobs
LOCK_TTL_MINUTES=30
PER_ROW_DEADLINE_S=90
HEARTBEAT_INTERVAL_S=30
HEARTBEAT_ENABLED=false

# 기존 (재사용): SUPABASE_URL, SUPABASE_SERVICE_KEY, STORAGE_BASE_DIR
```

### 9.5 동시성 한계 + lock 운영

| 제약 | 영향 / 대응 |
|---|---|
| OpenAI RPM (tier별) | 초과 시 429. SDK 재시도가 1차 흡수. 보수적으로 시작 → 모니터링 후 증대. |
| OpenAI TPM | row당 입력 ≈ 1.5–3K + 출력 ≈ 0.5K = ~3K. TPM 200K면 동시 ~60 row가 한계. |
| Supabase 동시 UPDATE | row 단위 UPDATE라 충돌 없음 (atomic claim으로 row 분리됨). |
| PyMuPDF (sync) | `asyncio.to_thread`로 wrapping. 이벤트 루프 안 막음. |
| **per-row deadline** | `PER_ROW_DEADLINE_S` (기본 90초). 초과 시 row를 pending으로 되돌림. PDF 손상·OpenAI 행거·extract 무한루프 방지. |
| **lock TTL** | `LOCK_TTL_MINUTES` (기본 30분). `tagging_locked_at < now() - LOCK_TTL_MINUTES`인 `processing` row를 stale로 보고 회수. **`LOCK_TTL_MINUTES * 60 > PER_ROW_DEADLINE_S`** 보장 (그 사이 정상 처리가 끝날 시간을 줘야 stale 회수가 살아있는 워커를 방해하지 않음). |
| **heartbeat (선택)** | `HEARTBEAT_ENABLED=true`이면 워커가 처리 중 `tagging_locked_at = now()`를 `HEARTBEAT_INTERVAL_S`마다 갱신. PDF가 매우 큰 경우 (`PER_ROW_DEADLINE_S`를 길게 잡아야 할 때) lock TTL 안 늘리면서 stale 오작동 방지. 일상 batch에는 불필요. |

기본 `MAX_CONCURRENT_LLM=10`. 실패율·지연 보면서 조정.

### 9.6 테스트 전략

```
tests/
├── conftest.py            # KRX 인덱스 fixture, mock AsyncOpenAI, mock SupabaseSQL
├── test_extract_pdf.py    # 실제 sample PDF 1~5p fallback 검증
├── test_oos_gate.py       # 4종 OOS 패턴 + private/IR자료 경계 (룰 4)
├── test_canonicalize.py   # publisher alias 매핑, topic alias
├── test_validate.py       # KRX 검증, 정규식, fuzzy sector
├── test_enrich.py         # 산업 합류 (대⊃중⊃제품), 단일종목 자동 보강, sent_at 폴백
├── test_decide_status.py  # 원 spec §6.6 결정 트리 모든 분기 (parametrize)
├── test_orchestrator.py   # 동시성, atomic claim 시뮬, broad exception 처리, deadline, dry_run/row_ids
├── test_parity.py         # NEW: friendly-mclaren skill 결과 JSON과 본 구현 출력 비교 (regression)
└── golden/
    ├── single_stock_*.pdf
    ├── industry_*.pdf
    ├── sector_*.pdf
    ├── daily_market.pdf
    ├── macro.pdf
    ├── quant.pdf
    ├── theme.pdf
    ├── ipo_listing.pdf
    ├── ipo_unlisted.pdf            # KRX 미매칭 IPO (in-scope 유지) — §6.5 룰 4
    ├── esg.pdf
    ├── reit.pdf
    ├── derivative.pdf
    ├── credit.pdf
    ├── ir_company_self.pdf         # private 경계 → in-scope
    ├── etc_in_scope.pdf
    ├── foreign_primary.pdf         # OOS foreign (해외 단일종목 분석)
    ├── domestic_with_foreign_peer.pdf  # NEW: 국내 단일종목 + AAPL/NVDA peer 언급 → in-scope
    ├── etf_lineup.pdf              # OOS fund
    ├── digital_btc.pdf             # OOS digital
    ├── private_unlisted.pdf        # OOS private
    ├── unknown_publisher_in_scope.pdf  # NEW: vocab에 없는 broker → review_needed/low
    └── unknown_product_in_scope.pdf    # NEW: KRX 도메인 외 product → review_needed/low
```

핵심:
- `test_decide_status.py`: 원 spec §6.6의 모든 분기를 input → expected output 케이스로 parametrize. **LLM 호출 0회**로 결정 트리 검증. 사용자 우려("코드가 LLM을 완전 대체하는 게 안전한지")의 직접 답.
- `test_orchestrator.py`: `mock_openai_returning(LLMExtraction(...))` fixture로 그래프 전체를 LLM 호출 없이 검증. atomic claim race, per-row deadline timeout, broad exception, dry_run/row_ids 모두 케이스화.
- **`test_parity.py` (신규)**: friendly-mclaren의 evals workspace에 적재된 result.json과 본 구현 출력을 비교하는 regression. "결과 동일성 100% 보존"의 자동 검증. 가용한 result.json이 없는 fields는 사람이 6~10개 대표 케이스를 fixture로 고정.
- golden PDFs: 14 type + 4 OOS + 5 경계 케이스. friendly-mclaren의 evals와 동일 PDF 사용 가능.

### 9.7 운영 보고

```
[langgraph-tagger] worker=hostX-12345-a1b2 model=gpt-5.4-mini batch=50
processed:  50  (auto=42, review_needed=8)
confidence: high=30, medium=12, low=8
oos:        foreign=2, fund=1, digital=0, private=1
review_needed reasons:
  - unknown_stock_code: 3
  - first_page_unreadable: 2
  - type_indeterminate: 2
  - llm_refusal: 1
  - unknown_publisher: 2 (IRKUDOS, NewBoutique)
  - unknown_product: 1
duration: 47.3s
cost (estimated): input=$0.X, output=$0.Y, total=$0.Z
```

cost 추정은 OpenAI completion 응답의 `usage.prompt_tokens` / `usage.completion_tokens`를 누적해서 환산.

#### 9.7.1 unknown publisher / product 정기 보강 흐름

`unknown_publisher`/`unknown_product`는 `review_needed/low`로 빠지므로 vocabulary 보강 후 일괄 재처리가 정상 흐름이다.

```sql
-- 최근 7일 미등록 publisher 상위 (PR로 publishers.yaml에 추가할 후보)
SELECT split_part(tagging_notes, ':', 2) AS unknown_pub, count(*)
  FROM reports
 WHERE tagging_notes LIKE 'unknown_publisher:%'
   AND tagged_at >= now() - interval '7 days'
 GROUP BY 1
 ORDER BY 2 DESC;

-- 최근 7일 미등록 product 상위
SELECT split_part(tagging_notes, ':', 2) AS unknown_prod, count(*)
  FROM reports
 WHERE tagging_notes LIKE 'unknown_product:%'
   AND tagged_at >= now() - interval '7 days'
 GROUP BY 1
 ORDER BY 2 DESC;
```

위 결과로 `publishers.yaml` PR 또는 KRX CSV 갱신 후, 해당 row들을 `pending`으로 되돌려 재처리:

```sql
UPDATE reports
   SET tagging_status='pending', tagging_notes=NULL,
       tagging_confidence=NULL, tagging_locked_at=NULL, tagging_worker_id=NULL
 WHERE tagging_notes LIKE 'unknown_publisher:NewBroker%';
```

> **analysts는 vocabulary 매핑 없음** (Option γ): LLM이 추출한 raw 이름을 `analysts text[]`에 그대로 기록. 새 애널리스트 등장 빈도가 매우 높고 vocabulary 유지 비용이 publisher 대비 큼. 검색은 GIN 인덱스로 충분. `analysts` 부재는 `confidence='medium'` 정도로만 영향 (review_needed 아님).

## 10. 의존성

`requirements.txt` 추가 (master 기존 파일에 append):

```
langgraph>=1.0,<2.0
openai>=2.11
pymupdf>=1.24
pyyaml>=6.0
pydantic>=2.7

# 기존: supabase, asyncpg, python-telegram-bot, ... 그대로
```

`langchain-openai`는 사용하지 않음 — vanilla `openai.AsyncOpenAI`만으로 structured output 충분 (LangGraph 1.0과 호환).

## 11. friendly-mclaren spec과의 매핑 (룰 보존 검증)

| 원 spec 룰 | 본 spec 위치 |
|---|---|
| §3.a PDF 1~5p fallback | §8.1 `extract_pdf` |
| §3.a `first_page_unreadable` (가독 실패) | §8.4.1 `status_unreadable` (oos_gate에서 별도 분기) |
| §3.b 후보 필드 추출 | §7.2 `LLMExtraction` + §8.2 `llm_extract` (1회 호출) |
| §3.b `llm_refusal` 처리 | §8.4.1 `status_unreadable` |
| §3.c OOS 우선 판정 | §8.3 `oos_gate` (routing-only) + §8.3.1 `mark_oos_reason` + §8.4 `status_oos` |
| §3.d Canonical 정규화 (publisher/topics/products) | §8.5 `canonicalize` (publisher/topics) + §8.6 `validate` (products `KRX.has_product` 멤버십) |
| §3.e CSV 검증 + 산업 깊이 | §8.6 `validate` + §8.7 `enrich` (`rows_with_product`/`rows_with_sector_minor`) |
| §6.5 룰 4 IPO 경계 (KRX 미매칭 IPO in-scope) | §8.3 `oos_gate`의 private 분기 (IR자료 / KRX 매칭 / IPO 후보 모두 in-scope 유지) |
| §6.6 `unknown_publisher` → review_needed/low | §8.8 `decide_status` (코드 정책) — 원 spec 정책 보존 |
| §6.6 `unknown_product` → review_needed/low | §8.6 `validate` (products_unknown 분리) + §8.8 `decide_status` |
| §3.f status/confidence 결정 | §8.8 `decide_status` |
| §3.g UPDATE row | §8.9 `write` + §9.1 `UPDATE_SQL` |
| §6.5 precedence rule | §8.2 SYSTEM_PROMPT (LLM 분류 시) + §8.3 oos_gate (룰 4) + §8.7 enrich (자동 보강) |
| §6.6 결정 룰 | §8.8 `decide_status` (코드 함수 1개) + §8.4 `status_oos` (OOS 케이스) + §8.4.1 `status_unreadable` (가독 실패) |
| §6.7 동시성 (atomic claim, stale lock) | §9.1 SQL + §9.2 orchestrator |
| `dry_run`/`row_ids` 인자 | §9.2 orchestrator 분기 |
| `tagger_version`/`taxonomy_version` 감사 | §9.1 `UPDATE_SQL` + §7.4 `KRXIndex.taxonomy_version` |

**결과 동일성 기준 100% 매핑**. 결정 룰 자체는 동일, 실행 환경만 변경.

## 12. 변경 가능성 / 후속

- **vocabulary 추가**: `publishers.yaml` / `topics.yaml`에 항목 추가 후 PR. 코드 변경 없음.
- **모델 escalation 자동화**: 1pass 끝에 곧장 2pass 호출하는 wrapper (`run_batch_with_escalation`) 추가 가능 — 본 spec에서는 명시적 두 명령으로 분리 (사용자 가시성).
- **OpenAI Batch API**: 24h 비범위 비동기 처리, 50% 할인. 현재 spec은 사용 안 함 (사용자 결정). 후일 backfill용으로 어댑터 추가 가능.
- **LangSmith 관측성**: 환경변수 (`LANGSMITH_API_KEY`, `LANGSMITH_TRACING=true`)만 설정해도 LangGraph가 자동으로 trace 송출. 본 spec은 옵션으로 두고 강제하지 않음.
- **본 spec의 한계**: products substring 매칭이 단순 `in` 검사라 "메모리"가 "메모리반도체" 셀에 매칭되는 식의 false positive 가능. 운영 중 발견되면 토큰 경계 정규화 (단어 경계 + 사전) 추가.

## 13. 운영 흐름 (브랜치 시작 → 첫 backfill)

1. 새 브랜치 분기 from master
2. 본 spec commit
3. friendly-mclaren에서 다음 파일 가져와 commit:
   - `migrations/002_tagging_columns.sql`
   - `docs/stock_data/KRX_stocks_data.csv`
   - `references/publishers.md` / `topics.md` 내용을 본 spec §7.3의 YAML로 변환 commit
4. `langgraph_tagger/` 패키지 작성 (writing-plans → 구현 단계)
5. `tests/`의 단위 테스트 작성 (특히 `test_decide_status.py`로 룰 보존 검증)
6. golden PDFs 6개 정도로 dry-run → status/confidence/notes 분포 점검
7. 작은 batch (10건) 실 운영 호출 → 에러율·토큰 사용량 측정
8. publishers.yaml / topics.yaml vocabulary 보강
9. 큰 backfill (`--batch-size 100`)
10. 1pass 끝 후 `escalate --since ...`로 review_needed만 gpt-5.4 재처리
11. 주기적 vocabulary 보강 흐름 (§9.7.1): unknown_publisher/unknown_product 분포 쿼리 → 결과를 보고 publishers.yaml PR / KRX CSV 갱신 → 해당 row를 pending으로 일괄 되돌려 재처리. analysts는 vocabulary 매핑 없이 raw 기록되므로 별도 보강 불필요 (Option γ).

## 14. brainstorming → 구현 분기

본 spec의 후속 단계는 superpowers의 `writing-plans` skill — 구현 task list 작성 → 단계별 구현. 본 spec에서 결정 룰·SQL·schema·노드 인터페이스가 모두 고정되어 있으므로 plan은 "각 파일 작성 + 단위 테스트 추가"의 task로 분해된다.
