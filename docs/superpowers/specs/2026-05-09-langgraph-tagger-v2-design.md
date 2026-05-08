# LangGraph Tagger v2 — 설계 (KRX-driven 단순화)

작성일: 2026-05-09
상태: 설계 (구현 전)
선행 spec (v1): `docs/superpowers/specs/2026-05-08-langgraph-tagger-design.md`
선행 구현: 22 commits (v1 rev 1~4) — incremental 변경으로 v2 적용

---

## 1. 배경

v1 spec/구현으로 dry-run 3건을 돌려본 결과, **결과 정합성**과 **운영 효율** 양쪽에서 문제가 드러났다.

dry-run 결과 (3건 모두 review_needed/low):
- LLM 추출 자체는 정확 (report_type 분류, publisher 후보 추출, OOS 판정 등 합리적)
- 그러나 vocab 매칭이 strict한 deterministic 코드 룩업이라:
  - "Hana" / "Daishin Commodity / 대신증권 Research Center" / "QMC Corp., Ltd." 모두 publishers.yaml에 매칭 실패
  - LLM이 추출한 sectors_major (`'원자재'`, `'Commodity'`)가 KRX 28종 도메인에 없음
  - LLM이 추출한 products (`'엑스코프리'`, `'세노바메이트'`, `'Semiconductor'`, `'Camera Module'` 등) 중 대다수가 KRX `주요제품` 셀에 한글/약어 형태가 아니라서 substring 매칭 실패
- 결과: 3건 모두 `unknown_publisher` + `unknown_product` + `unknown_sector` 등 다중 issue로 review_needed 큐에 들어감

**의도 재정렬** (사용자 입력 #1~#6):

| # | 의도 |
|---|---|
| 1 | report_type 14종이 너무 fragmented — **6종으로 축소** |
| 2 | vocab 코드 매핑은 실효성 없음 — **LLM이 vocab 보고 자의적 매핑** (publisher 등) |
| 3 | LLM은 종목코드/종목명만 확보. **sectors/products는 KRX CSV가 절대 답지** — LLM이 sectors/products 추출하지 않음 |
| 4 | topics는 결과물이 쓸만하지 않음 — **폐기** |
| 5 | 종목명 정규화: **KRX 매칭 시 KRX 종목명으로 overwrite**, 미매칭 시 LLM raw 사용 + raw 별도 audit 컬럼 |
| 6 | PDF 1~5p → **1~3p** (5p too much) |

**OOS 정책 변경** (Q5/Q6 결정):
- **IR자료를 OOS로** 처리 — 분석 타겟은 증권사·리서치사가 분석한 리포트. 자체 IR자료는 분석 대상이 아님
- OOS 5종: foreign / fund / digital / private / **ir_self** (신규)
- KRX 미매칭 + IR자료 → OOS ir_self
- KRX 미매칭 + 그 외 → review_needed (IPO 예정 등)

## 2. 목표 (v2)

- LLM의 책임을 "stock_code/company_name + report_type + 핵심 보조 정보 + OOS 신호" 한 번 호출로 압축
- KRX CSV를 sectors_major/sectors_minor/products + 회사명 정식 표기의 **단일 진실 공급원**으로 사용
- vocab 코드 매칭 실효성 문제 해소: publisher만 LLM 자의적 매핑, sectors/products/topics는 폐기 또는 KRX 답지로 대체
- IR자료 = 분석 타겟 외 → OOS ir_self로 자동 배제
- v1 코드는 폐기하지 않고 **rev-5로 incremental 변경**

## 3. 비범위

- v1 commit 폐기·squash 없음 — incremental rev
- 기존 master 코드 (`collector.py`, `storage.py` 등) 변경 없음
- 분석가 vocab 매핑 (Option γ는 v1과 동일하게 유지)
- LangSmith 트레이스는 v1 그대로 (env로 활성화)

## 4. v1 → v2 변경 요약

| 영역 | v1 (현재) | v2 (변경) |
|---|---|---|
| **PDF 페이지** | 1~5p fallback | **1~3p** (사용자 #6) |
| **LLM 출력 schema** | report_type(14) + sectors_major/minor + products + topics + publisher_raw + ... | **report_type(6) + stock_codes_raw + company_names_raw + publisher_canon + publisher_type + title + published_at + analysts + oos_signals(4)** |
| **report_type enum** | 14종 | **6종** (단일종목/산업/섹터/IR자료/전략·시황/기타) |
| **publisher 매핑** | LLM raw + 코드 deterministic 룩업 | **LLM이 publishers.yaml 보고 자의적 매핑 → publisher_canon 직접 출력** |
| **sectors/products** | LLM 추출 + KRX 검증 + 산업 합류 enrich | **LLM 추출 안 함. KRX entry에서 직접 가져옴** |
| **topics** | LLM 추출 + topics.yaml 매핑 | **폐기** |
| **OOS reason 종류** | 4종 (foreign/fund/digital/private) | **5종** (+ ir_self) |
| **IR자료 처리** | in-scope (publisher_type='company') | **OOS ir_self** |
| **종목명 정규화** | LLM raw 그대로 | **KRX 매칭 시 KRX 종목명 overwrite + raw audit** |
| **canonicalize 노드** | publisher 룩업 + topic alias | **삭제** (publisher는 LLM, topic은 폐기) |
| **validate 노드** | KRX code/sector/product 검증 | **resolve_krx로 통합** |
| **enrich 노드** | KRX 산업 합류 + published_at fallback | **resolve_krx로 통합 + published_at fallback 분리** |
| **resolve_krx 노드** | (없음) | **신규** — stock_code 우선 + name fuzzy로 KRX entry 결정, sectors/products 답지 회수 |
| **decide_status 정책** | unknown_publisher/product/sector → review_needed/low | **krx_unmatched_in_scope만 review_needed/low** (vocab 검증 자체가 사라짐) |
| **DB 컬럼** | (v1 그대로) | **+ stock_codes_raw, company_names_raw** (audit). **− topics** (drop) |

## 5. 핵심 결정

| # | 결정 | 근거 |
|---|---|---|
| 1 | report_type 6종 | 14종 분류는 fragmented하고 운영 효용 낮음. dry-run 정확도 OK였지만 카테고리 단순화 우선 |
| 2 | publisher LLM 자의적 매핑 | dry-run에서 영문/슬래시/부서명 포함 publisher들이 코드 룩업 모두 실패 — LLM이 prompt-vocab 보고 fuzzy 매칭이 robust |
| 3 | KRX 단일 진실 공급원 | 사용자 #3 명시. LLM이 sectors/products를 PDF에서 정확히 KRX 도메인 형식으로 추출 못함 (영문/한글, 약어/풀네임 mismatch) |
| 4 | topics 폐기 | dry-run에서 LLM이 출력한 topics가 모두 ad-hoc 자유 텍스트 — vocab 매핑이 거의 안 됨, 재처리 가치 낮음 |
| 5 | IR자료 OOS | 자체 IR은 분석 대상 아님. 비상장사 IR자료는 KRX와 무관 → OOS ir_self가 자연스러움 |
| 6 | KRX 미매칭 + 비-IR자료 → review_needed | 사용자 #2: IPO 예정 종목 등은 KRX에 없을 수 있음 → 사람 검토 필요 |
| 7 | LLM raw audit 컬럼 보존 | 사용자 #1: 사람이 추후 검토할 수 있도록 LLM이 추출한 stock_codes/company_names raw 그대로 별도 보존 |

## 6. 산출물

1. **migration 003** `migrations/003_v2_redesign.sql`
   - report_type CHECK: 14종 → 6종
   - out_of_scope_reason CHECK: 4종 → 5종 (+ ir_self)
   - publisher_type CHECK: 5종 → 4종 (- company)
   - 신규 컬럼: `stock_codes_raw text[] NOT NULL DEFAULT '{}'`, `company_names_raw text[] NOT NULL DEFAULT '{}'`
   - drop: `topics text[]` 컬럼 + `ix_reports_topics_gin` 인덱스
   - 기존 row 마이그레이션 (§13)

2. **vocabulary 변경**:
   - `publishers.yaml` — 그대로 유지 (LLM prompt 주입용)
   - `topics.yaml` — **삭제**
   - `taxonomy.yaml` — report_type 14→6, sector_major_aliases 유지

3. **노드 변경**:
   - 삭제: `nodes/canonicalize.py`, `nodes/validate.py`, `nodes/enrich.py`
   - 신규: `nodes/resolve_krx.py` — KRX entry 결정 + sectors/products 답지 회수 + published_at 폴백 모두 통합
   - 변경: `nodes/extract_pdf.py` (max=3), `nodes/oos_gate.py` (IR자료 분기 + private 룰), `nodes/mark_oos_reason.py` (ir_self), `nodes/decide_status.py` (단순화), `nodes/write.py` (컬럼 변경)
   - `nodes/llm_extract.py`, `nodes/status_oos.py`, `nodes/status_unreadable.py` 그대로

4. **vocabulary 모듈**:
   - `vocabulary/__init__.py` — `lookup_publisher`/`map_topics` 제거 (LLM이 직접 처리). `taxonomy()` 유지.
   - `vocabulary/krx.py` — `lookup_by_name(name)` 신규 메서드, `has_product` 제거.

5. **schemas**:
   - `llm_schemas.py` — LLMExtraction 축소·재정의
   - `state.py` — RowState 키 재정의

6. **prompts.py** — 6종 enum + publishers.yaml 본문 주입 + KRX 답지 안내

7. **graph.py** — 새 노드 wiring

8. **테스트** — 변경된 노드의 단위테스트 + 새 parity fixtures (6종 × 5 OOS reasons)

기존 v1 commit history (Tasks 1~22)는 보존. v2는 rev-5로 추가 commit.

## 7. 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│  CLI (변경 없음): python -m langgraph_tagger run|inspect|escalate │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator (변경 없음): claim → asyncio.gather + Semaphore │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LangGraph row_graph (단순화)                               │
│   extract_pdf → llm_extract → oos_gate (3-way)              │
│      ├─ OOS:        mark_oos_reason → status_oos → write    │
│      ├─ unreadable: status_unreadable → write               │
│      └─ in-scope:   resolve_krx → decide_status → write     │
└─────────────────────────────────────────────────────────────┘
```

v1 vs v2 노드 흐름 차이:
- v1 in-scope: `canonicalize → validate → enrich → decide_status → write` (4 노드)
- v2 in-scope: `resolve_krx → decide_status → write` (2 노드)

`resolve_krx`가 publisher canonicalization·sector enrich·product 회수를 모두 흡수.
`published_at` 폴백은 `resolve_krx` 안에서 처리.

## 8. 데이터 모델

### 8.1 LLMExtraction (Pydantic) — 축소

```python
from typing import Optional
from pydantic import BaseModel, Field
from typing_extensions import Literal

REPORT_TYPES = Literal[
    "단일종목", "산업", "섹터", "IR자료", "전략·시황", "기타",
]

class OOSSignals(BaseModel):
    foreign_primary_coverage: bool = Field(
        description="primary coverage가 해외 상장사. 국내 종목/산업 리포트가 외국 티커를 peer/벨류체인으로 단순 언급하는 경우는 false."
    )
    etf_or_fund: bool = Field(description="ETF 라인업 / 펀드평가 / 펀드비교")
    digital_asset: bool = Field(description="가상자산·디지털자산·BTC·ETH·코인")
    private_company_likely: bool = Field(
        description="명백한 비상장/장외 컨텍스트 (000000 코드, '비상장 분석' 표기 등). "
                    "IR자료/IPO/KRX-매칭 케이스는 false (별도 분기 처리)."
    )
    # ir_self는 LLM signal로 안 둠 — report_type='IR자료'에서 자동 결정

class LLMExtraction(BaseModel):
    report_type: REPORT_TYPES
    title: Optional[str] = Field(default=None, max_length=120)
    published_at: Optional[str] = Field(default=None, description="YYYY-MM-DD or null")

    stock_codes_raw: list[str] = Field(
        default_factory=list,
        description="KRX 6자리 후보 (영문 포함). 첫 페이지 헤더에 명시된 것만."
    )
    company_names_raw: list[str] = Field(
        default_factory=list,
        description="회사명 후보. 단일종목/IR/IPO에서 1개, 산업/시황은 0개."
    )

    publisher_canon: Optional[str] = Field(
        default=None,
        description="publishers.yaml의 canonical 형태로 정규화한 발행 주체. 매칭 안 되면 null."
    )
    publisher_type: Optional[Literal["broker","data_provider","ir_agency","other"]] = Field(
        default=None,
        description="publisher_canon이 set되면 함께 결정. 매칭 안 되면 null."
    )

    analysts: list[str] = Field(default_factory=list, description="첫 페이지 명시 애널리스트")

    oos_signals: OOSSignals
    self_confidence: Literal["high","medium","low"]
    notes: Optional[str] = Field(default=None, max_length=200)
```

**제거된 필드**: `sectors_major`, `sectors_minor`, `products`, `topics`, `company_names` (raw 만 유지), `publisher_raw` (canon으로 통합).

### 8.2 RowState (TypedDict) — 변경

```python
class RowState(TypedDict, total=False):
    # 입력 (claim 직후)
    id: int; file_path: str; file_name: str; sent_at: datetime
    caption: Optional[str]; chat_username: str; worker_id: str; model: str

    # extract_pdf 출력
    pdf_text: str; pages_used: list[int]; pdf_unreadable: bool

    # llm_extract 출력
    llm_raw: Optional[LLMExtraction]; llm_refusal: Optional[str]

    # oos_gate / mark_oos_reason 출력
    is_oos: bool
    oos_reason: Optional[Literal["foreign","fund","digital","private","ir_self"]]

    # resolve_krx 출력 (canonicalize+validate+enrich 통합)
    krx_matched: bool
    krx_entry: Optional[KRXEntry]                # 매칭 시
    stock_codes_final: list[str]                  # KRX 매칭이면 [code], 아니면 []
    company_names_final: list[str]                # KRX 매칭이면 [name], 아니면 raw fallback
    sectors_major_final: list[str]
    sectors_minor_final: list[str]
    products_final: list[str]
    published_at_final: Optional[date]
    used_sent_at_fallback: bool

    # decide_status / status_oos / status_unreadable 출력
    tagging_status: Literal["auto","review_needed"]
    tagging_confidence: Literal["high","medium","low"]
    tagging_notes: Optional[str]
```

**제거된 키**: `topics_canon`, `topic_unmapped`, `publisher_canon`, `publisher_type` (LLM이 직접 출력해서 llm_raw에 들어감), `stock_codes_valid/unknown`, `sectors_major_valid/minor_valid/unknown`, `products_valid/unknown`. (vocab 검증 단계 자체가 사라짐.)

### 8.3 KRXIndex 변경

신규 메서드:
```python
def lookup_by_name(self, name: str) -> Optional[KRXEntry]:
    """회사명 fuzzy 매칭 (whitespace+case insensitive). 동명이인 시 첫 매칭."""
    norm = "".join(name.split()).lower()
    for entry in self.by_code.values():
        if "".join(entry.name.split()).lower() == norm:
            return entry
    return None
```

제거: `has_product`, `filter_products_by_membership`, `rows_with_product`, `rows_with_sector_minor`, `fuzzy_sector_match` (validate/enrich/sector_major_aliases 모두 사라지므로 사용처 없음).
유지: `validate_code`, `lookup`, `split_products`, `taxonomy_version`.

### 8.4 vocabulary 변경

`vocabulary/__init__.py`:
- 제거: `lookup_publisher`, `map_topics`
- 유지: `taxonomy()` (prompts.py에서 사용)

`vocabulary/publishers.yaml`: 그대로 유지. **system_prompt에 본문 그대로 주입**해서 LLM이 vocab 보고 자의적 매핑.

`vocabulary/topics.yaml`: **삭제**.

`vocabulary/taxonomy.yaml`:
- `report_types`: 6종 (단일종목/산업/섹터/IR자료/전략·시황/기타)
- `oos_reasons`: 5종 (foreign/fund/digital/private/ir_self)
- `publisher_types`: 4종 (- company)
- `tagging_statuses`/`tagging_confidences`: 그대로
- `sector_major_aliases`: **삭제**. v2에서는 KRX entry가 sector_major를 직접 제공하므로 alias 매핑 불필요
- `precedence_rules`: 6종/IR자료 OOS 반영해서 수정

## 9. 노드별 동작

### 9.1 `extract_pdf` (변경)

`max_pages: int = 3` (v1 5 → v2 3). 그 외 동일.

### 9.2 `llm_extract` (그대로)

호출 자체는 변경 없음. SYSTEM_PROMPT만 변경 (§9.3).

### 9.3 `prompts.py` (대폭 변경)

```python
SYSTEM_PROMPT = f"""너는 한국 주식 리서치 PDF 첫 1~3페이지를 보고 메타데이터를 추출하는 전문가다.
출력은 정의된 JSON schema를 정확히 따른다.

## report_type (6종)

단일종목, 산업, 섹터, IR자료, 전략·시황, 기타

각 type 정의:
- 단일종목: 한 KRX 상장사 개별 분석. stock_codes_raw에 6자리 코드, company_names_raw에 회사명 1개.
- 산업: 산업(대) 단위 분석. stock_codes_raw 비움, company_names_raw 비움.
- 섹터: 좁은 섹터/테마. stock_codes_raw/company_names_raw는 0~수개.
- IR자료: 발행 주체 = 해당기업 자체 (자체 IR 발표자료). 분석 타겟 외이므로 자동 OOS 처리됨.
  → stock_codes_raw/company_names_raw에 회사 정보를 추출 (audit용으로 보존됨).
- 전략·시황: 시황·데일리·매크로·퀀트·전략·테마를 모두 포함. 자산배분/톱다운 의견 포함.
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
{publishers_yaml_content}

[publishers.yaml 본문이 여기 주입됨 — broker/data_provider/ir_agency/other 4 섹션]

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
```

`publishers_yaml_content`는 import time에 read해서 string interpolation. 약 +1.5KB token (gpt-5.4-mini 기준 약 0.001¢/row 추가).

### 9.4 `oos_gate` (변경)

```python
def oos_gate(state, *, krx) -> Literal["mark_oos_reason","status_unreadable","resolve_krx"]:
    if state.get("pdf_unreadable") or state.get("llm_refusal"):
        return "status_unreadable"
    raw = state.get("llm_raw")
    if raw is None:
        return "status_unreadable"

    # IR자료 = 자동 OOS ir_self
    if raw.report_type == "IR자료":
        return "mark_oos_reason"

    sig = raw.oos_signals
    if sig.foreign_primary_coverage or sig.etf_or_fund or sig.digital_asset:
        return "mark_oos_reason"

    if sig.private_company_likely:
        # 명백한 비상장 컨텍스트: KRX 매칭 시 in-scope (예: 0008Z0 SPAC), 미매칭 시 OOS private
        if any(krx.validate_code(c) for c in raw.stock_codes_raw):
            return "resolve_krx"
        return "mark_oos_reason"

    return "resolve_krx"
```

v1 대비 변경:
- `IR자료` 자동 분기 추가
- 'canonicalize' → 'resolve_krx' (라벨 변경)
- private_company_likely + IPO 예외 룰 제거 (IPO enum 자체가 사라짐 — 6종에 IPO 없음)

### 9.5 `mark_oos_reason` (변경)

```python
def mark_oos_reason(state) -> dict:
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

### 9.6 `status_oos` (그대로)

`is_oos=True`, `tagging_status='auto'`, confidence:
- foreign/fund/digital/ir_self: `high`
- private: `medium` (보더라인)

### 9.7 `status_unreadable` (그대로)

### 9.8 `resolve_krx` (신규 — canonicalize+validate+enrich 통합)

```python
def resolve_krx(state, *, krx) -> dict:
    raw = state["llm_raw"]

    # 1. KRX 매칭 시도 — stock_code 우선, 회사명 fallback
    entry: Optional[KRXEntry] = None
    for code in raw.stock_codes_raw:
        if krx.validate_code(code):
            entry = krx.lookup(code)
            break
    if entry is None:
        for name in raw.company_names_raw:
            entry = krx.lookup_by_name(name)
            if entry:
                break

    # 2. 매칭 결과에 따라 final 필드 set
    if entry:
        result = {
            "krx_matched": True,
            "krx_entry": entry,
            "stock_codes_final": [entry.code],
            "company_names_final": [entry.name],   # KRX 정식 표기로 통일
            "sectors_major_final": [entry.sector_major] if entry.sector_major else [],
            "sectors_minor_final": [entry.sector_minor] if entry.sector_minor else [],
            "products_final": krx.split_products(entry.products_text),
        }
    else:
        # KRX 미매칭 — LLM raw fallback (audit 컬럼은 별도)
        result = {
            "krx_matched": False,
            "krx_entry": None,
            "stock_codes_final": [],
            "company_names_final": list(raw.company_names_raw),
            "sectors_major_final": [],
            "sectors_minor_final": [],
            "products_final": [],
        }

    # 3. published_at 폴백
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

**핵심 단순화**:
- LLM이 sectors/products를 추출 안 하므로 검증 단계 불필요
- KRX entry 1개로 sectors_major/minor/products 모두 결정 (산업 합류 로직 불필요 — KRX 한 row가 한 종목의 모든 답)
- publisher는 LLM이 이미 canonical로 출력 — 별도 노드 불필요

### 9.9 `decide_status` (단순화)

```python
def decide_status(state) -> dict:
    if state.get("pdf_unreadable"):
        return {"tagging_status":"review_needed","tagging_confidence":"low",
                "tagging_notes":"first_page_unreadable"}
    if state.get("llm_refusal"):
        return {"tagging_status":"review_needed","tagging_confidence":"low",
                "tagging_notes": f"llm_refusal:{state['llm_refusal']}"}

    # OOS 케이스는 status_oos가 이미 처리. 여기 도달하면 in-scope.
    raw = state.get("llm_raw")
    
    # KRX 미매칭 + in-scope (= IPO 예정 등 KRX에 없는 종목 분석)
    if not state.get("krx_matched"):
        return {"tagging_status":"review_needed","tagging_confidence":"low",
                "tagging_notes":"krx_unmatched_in_scope"}

    # type_indeterminate (LLM이 자체 신뢰도 low이고 report_type='기타')
    if raw is not None and raw.report_type == "기타" and raw.self_confidence == "low":
        return {"tagging_status":"review_needed","tagging_confidence":"low",
                "tagging_notes":"type_indeterminate"}

    # KRX 매칭 + in-scope = auto. confidence는 폴백 신호로만 결정.
    used_fallback = (
        state.get("used_sent_at_fallback")
        or len(state.get("pages_used") or [1]) > 1
    )
    return {
        "tagging_status": "auto",
        "tagging_confidence": "medium" if used_fallback else "high",
        "tagging_notes": None,
    }
```

**제거된 분기**:
- unknown_stock_code/sector/product/publisher (vocab 검증 자체가 사라짐)
- topic_unmapped (topics 폐기)
- publisher_canon=None 분기 (LLM이 직접 매핑 — null이어도 정상 케이스)

review_needed 트리거: `pdf_unreadable`, `llm_refusal`, `krx_unmatched_in_scope`, `type_indeterminate` 4종.

### 9.10 `write` (변경)

UPDATE_SQL 컬럼 변경 — `topics` 제거, `stock_codes_raw`/`company_names_raw` 추가. payload는 19-arg 위치 placeholder.

```python
def _build_payload(state, taxonomy_version) -> tuple:
    raw = state.get("llm_raw")
    is_oos = bool(state.get("is_oos"))

    # OOS 케이스 — 분류 메타 비우고 audit raw는 그대로 남김
    if is_oos:
        return (
            state["id"],                                  # $1
            None,                                          # $2 published_at (OOS는 null)
            "기타",                                        # $3 report_type 강제
            None, None,                                    # $4,$5 publisher 모두 null
            [],                                            # $6 analysts 비움
            (raw.title if raw else None),                  # $7 title 보존
            [],                                            # $8 stock_codes
            [],                                            # $9 company_names
            list(raw.stock_codes_raw) if raw else [],     # $10 stock_codes_raw (audit)
            list(raw.company_names_raw) if raw else [],   # $11 company_names_raw (audit)
            [], [], [],                                    # $12,$13,$14 sectors/products 비움
            state["oos_reason"],                           # $15 out_of_scope_reason
            state["tagging_status"],                       # $16
            state["tagging_confidence"],                   # $17
            state.get("tagging_notes"),                    # $18
            taxonomy_version,                              # $19
        )

    # 가독 실패
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
        list(raw.stock_codes_raw),                # audit 항상 보존
        list(raw.company_names_raw),              # audit 항상 보존
        list(state.get("sectors_major_final", [])),
        list(state.get("sectors_minor_final", [])),
        list(state.get("products_final", [])),
        None,                                      # out_of_scope_reason NULL
        state["tagging_status"],
        state["tagging_confidence"],
        state.get("tagging_notes"),
        taxonomy_version,
    )
```

UPDATE_SQL 19개 위치 placeholder ($1..$19) — `topics` 제거, `stock_codes_raw`, `company_names_raw` 추가.

### 9.11 graph 조립

```python
def build_graph(client, sb, *, krx, dry_run, taxonomy_version):
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
    g.add_conditional_edges("llm_extract", partial(oos_gate, krx=krx), {
        "mark_oos_reason":   "mark_oos_reason",
        "status_unreadable": "status_unreadable",
        "resolve_krx":       "resolve_krx",
    })
    g.add_edge("mark_oos_reason", "status_oos")
    g.add_edge("status_oos", "write")
    g.add_edge("status_unreadable", "write")
    g.add_edge("resolve_krx", "decide_status")
    g.add_edge("decide_status", "write")
    g.add_edge("write", END)
    return g.compile()
```

총 8 노드 (v1 10 노드에서 2 감소: canonicalize/validate/enrich 폐기, resolve_krx/published_at_fallback 통합·1개로 합쳐짐).

## 10. 운영 (대부분 v1과 동일)

- Orchestrator (claim/fan-out/aggregate): v1 그대로
- Per-row deadline + broad except: v1 그대로
- LangSmith 자동 trace: env로 활성화
- inspect/escalate 명령: v1 그대로

`_aggregate`의 review_reasons 키 변경 (검증 기반 unknown_* 4종 제거, krx_unmatched_in_scope 추가):
```
review_reasons = {first_page_unreadable, llm_refusal, type_indeterminate, krx_unmatched_in_scope}
```

## 11. migration 003

```sql
-- migrations/003_v2_redesign.sql

-- 1. 기존 데이터 마이그레이션 (14종 → 6종 매핑)
--    그대로 유지하는 5종 (단일종목/산업/섹터/IR자료/기타)은 손대지 않음.
UPDATE reports SET report_type = '전략·시황'
 WHERE report_type IN ('시황·데일리','거시·매크로','퀀트·전략','전략·테마');
UPDATE reports SET report_type = '단일종목'
 WHERE report_type = 'IPO';   -- IPO 분석은 한 종목 분석 본질. KRX 미매칭이면 review_needed로 빠짐.
UPDATE reports SET report_type = '산업'
 WHERE report_type IN ('ESG','부동산·리츠','파생·원자재','채권·크레딧');

-- 2. 기존 publisher_type='company' (자체 IR) → 'other' + 동시에 OOS ir_self
--    이건 IR자료 데이터를 OOS로 옮기는 마이그레이션
UPDATE reports
   SET out_of_scope_reason = 'ir_self',
       publisher_type      = 'other',
       publisher           = COALESCE(publisher, '해당기업')
 WHERE report_type = 'IR자료';

-- 3. CHECK 제약 갱신 (DROP+ADD)
ALTER TABLE reports DROP CONSTRAINT chk_report_type;
ALTER TABLE reports ADD CONSTRAINT chk_report_type CHECK (
  report_type IS NULL OR report_type IN
  ('단일종목','산업','섹터','IR자료','전략·시황','기타')
);

ALTER TABLE reports DROP CONSTRAINT chk_out_of_scope_reason;
ALTER TABLE reports ADD CONSTRAINT chk_out_of_scope_reason CHECK (
  out_of_scope_reason IS NULL OR out_of_scope_reason IN
  ('foreign','fund','digital','private','ir_self')
);

ALTER TABLE reports DROP CONSTRAINT chk_publisher_type;
ALTER TABLE reports ADD CONSTRAINT chk_publisher_type CHECK (
  publisher_type IS NULL OR publisher_type IN
  ('broker','data_provider','ir_agency','other')
);

-- 4. audit 컬럼 추가
ALTER TABLE reports
  ADD COLUMN IF NOT EXISTS stock_codes_raw   text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS company_names_raw text[] NOT NULL DEFAULT '{}';

-- 5. topics 제거 (인덱스 + 컬럼)
DROP INDEX IF EXISTS ix_reports_topics_gin;
ALTER TABLE reports DROP COLUMN IF EXISTS topics;
```

## 12. 활용 시나리오 (변경)

| ID | 시나리오 | v2에서 동작 |
|---|---|---|
| A-1 | KRX 코드로 종목별 시계열 | `stock_codes @> array['005930']` (그대로) |
| A-2 | 회사명으로 시계열 | `company_names @> array['삼성전자']` — KRX 정규화로 통일됨 (v1보다 일관성 ↑) |
| B | 산업/sector 트레이싱 | KRX 답지로 무조건 채워지므로 v1보다 정확. 단 `sectors_major @> array['반도체']` |
| C | 발행일 시계열 | 그대로 |
| D | 발행 주체·애널리스트별 | publisher canonical 통일 (LLM 자의적 매핑) |
| E | 제목 키워드 | 그대로 |
| F | 비-종목 토픽 | **폐기** — topics 컬럼 자체 없음. 운영 필요 시 title ILIKE으로 대체 |
| G (신규) | KRX 미매칭 분석 (audit) | `krx_unmatched_in_scope`인 row의 `stock_codes_raw`/`company_names_raw` 검토 |
| H (신규) | OOS IR자료 분포 | `out_of_scope_reason='ir_self'` |

## 13. 기존 row 처리 (마이그레이션)

inspect 결과: `auto=3,317`, `review_needed=73`, `oos_total=151`. 이 데이터는 v1 14종으로 분류됨.

migration 003의 step 1·2가 자동으로 처리:
- 14종 → 6종 mapping
- IR자료 row → OOS ir_self 추가

기존 `topics` 데이터는 컬럼과 함께 폐기. 운영자가 백업이 필요하면 migration 전에 export 권장.

기존 `stock_codes`/`company_names`는 그대로 남음. v1에서는 v2의 `stock_codes_final`에 해당. v2 신규 row만 `stock_codes_raw`/`company_names_raw`가 채워짐 (기존 row는 audit 비어있음).

## 14. v1 commit 매핑 (incremental rev-5)

| v1 영역 | v2 변경 |
|---|---|
| Task 1 (migration 002 + KRX CSV) | migration 003 추가 (003 = 002에 ALTER) |
| Task 2 (package skeleton) | 그대로 |
| Task 3 (taxonomy/publishers/topics YAML) | topics.yaml **삭제**, taxonomy.yaml report_types 6종으로 |
| Task 4 (vocabulary __init__) | `lookup_publisher`/`map_topics` 삭제. `taxonomy()` 유지 |
| Task 5 (KRX index) | `lookup_by_name` 신규, `has_product`/`filter_*` 삭제 |
| Task 6 (state.py + llm_schemas.py) | 둘 다 v2 schema로 재정의 |
| Task 7 (prompts.py) | publishers.yaml 본문 주입, 6종 enum, 1~3p |
| Task 8 (extract_pdf) | max_pages=3 |
| Task 9 (llm_extract) | 그대로 (호출만, schema는 새 LLMExtraction) |
| Task 10 (oos_gate + mark_oos_reason) | 둘 다 룰 변경 (IR자료 분기 + ir_self) |
| Task 11 (status_oos + status_unreadable) | 그대로 |
| Task 12 (canonicalize) | **삭제** |
| Task 13 (validate) | **삭제** |
| Task 14 (enrich) | **삭제 + resolve_krx 신규** |
| Task 15 (decide_status) | 단순화 |
| Task 16 (write + supabase_io) | UPDATE_SQL 19개 placeholder, 컬럼 변경 |
| Task 17 (graph assembly) | 노드 wiring 변경 (8 노드) |
| Task 18 (orchestrator) | 그대로 (review_reasons set만 갱신) |
| Task 19 (config + CLI) | 그대로 |
| Task 20 (parity) | fixtures 6종/5 OOS로 재구성 |
| Task 21 (golden PDFs) | 그대로 (여전히 유효) |
| Task 22 (live verification) | 새로 dry-run 후 진행 |

## 15. 의존성 (변경 없음)

`langgraph>=1.0`, `openai>=2.11`, `pymupdf>=1.24`, `pyyaml>=6.0`, `asyncpg>=0.29`, `pydantic>=2.7`. 모두 v1에서 설치됨.

## 16. brainstorming → 구현 분기

본 spec의 후속 단계는 superpowers의 `writing-plans` skill로 v2 task list 작성. 변경 폭이 크므로 ~10~15 task 예상 (대부분 기존 코드 변경, 일부 삭제, 1개 신규 노드).
