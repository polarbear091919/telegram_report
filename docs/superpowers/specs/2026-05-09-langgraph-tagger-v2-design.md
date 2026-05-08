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
| **IR자료 처리** | in-scope (publisher_type='company') | **OOS ir_self** (`report_type='IR자료'` 유지) |
| **OOS row의 report_type** | n/a (대부분 in-scope 분류) | **LLM 분류 그대로 유지** (예: 단일종목+foreign, IR자료+ir_self). `'기타'` 강제 안 함 |
| **종목명 정규화** | LLM raw 그대로 | **KRX 매칭 시 KRX 종목명 overwrite + raw audit** |
| **canonicalize 노드** | publisher 룩업 + topic alias | **삭제** (publisher는 LLM, topic은 폐기) |
| **validate 노드** | KRX code/sector/product 검증 | **resolve_krx로 통합** |
| **enrich 노드** | KRX 산업 합류 + published_at fallback | **resolve_krx로 통합 + published_at fallback 분리** |
| **resolve_krx 노드** | (없음) | **신규** — type별 정책: 단일종목 1 entry / 섹터 N entry aggregate / 산업·전략·시황 skip |
| **KRX lookup 정책** | 전 in-scope에 시도 (validate→enrich) | **report_type별 분기**: 단일종목 1개 / 섹터 N개 union / 산업·전략·시황 skip / 기타 1개 시도 |
| **decide_status 정책** | unknown_publisher/product/sector → review_needed/low | **`report_type='단일종목'` + `krx_unmatched_in_scope`만** review_needed/low. 산업·전략·시황은 KRX 없이도 auto |
| **name/code mismatch** | n/a | **`confidence=medium` + `tagging_notes='krx_name_code_mismatch'`** (review까진 보내지 않음) |
| **DB 컬럼** | (v1 그대로) | **+ stock_codes_raw, company_names_raw** (audit). **− topics** (drop) |
| **GIN 인덱스** | stock_codes/company_names/... | **+ stock_codes_raw_gin, company_names_raw_gin** (audit 시나리오 G용) |
| **기존 데이터 마이그레이션** | n/a | **모든 태깅 메타데이터 reset → pending** (14→6 매핑 안 함). PDF는 storage 보존, v2가 backfill로 재태깅 |

## 5. 핵심 결정

| # | 결정 | 근거 |
|---|---|---|
| 1 | report_type 6종 | 14종 분류는 fragmented하고 운영 효용 낮음. dry-run 정확도 OK였지만 카테고리 단순화 우선 |
| 2 | publisher LLM 자의적 매핑 | dry-run에서 영문/슬래시/부서명 포함 publisher들이 코드 룩업 모두 실패 — LLM이 prompt-vocab 보고 fuzzy 매칭이 robust |
| 3 | KRX 단일 진실 공급원 | 사용자 #3 명시. LLM이 sectors/products를 PDF에서 정확히 KRX 도메인 형식으로 추출 못함 (영문/한글, 약어/풀네임 mismatch) |
| 4 | topics 폐기 | dry-run에서 LLM이 출력한 topics가 모두 ad-hoc 자유 텍스트 — vocab 매핑이 거의 안 됨, 재처리 가치 낮음 |
| 5 | IR자료 OOS | 자체 IR은 분석 대상 아님. 비상장사 IR자료는 KRX와 무관 → OOS ir_self가 자연스러움 |
| 6 | KRX 미매칭 + 단일종목 → review_needed | IPO 예정 종목 등 KRX에 없는 종목 분석은 사람 검토 필요. 단 산업·전략·시황·섹터(0매칭)는 정상 케이스라 auto 통과 |
| 7 | LLM raw audit 컬럼 보존 | 사용자 #1: 사람이 추후 검토할 수 있도록 LLM이 추출한 stock_codes/company_names raw 그대로 별도 보존 |
| 8 | KRX lookup은 report_type별 분기 (산업·전략·시황은 skip) | 산업·전략·시황은 회사 1개로 대표 불가. 매칭 강제하면 정상 리포트가 false review_needed로 폭증 |
| 9 | OOS row의 report_type은 LLM 분류 그대로 유지 | 분포 분석 시 더 풍부 (단일종목+foreign 등). migration 003의 IR자료 처리(`report_type='IR자료'` 유지)와 일관 |
| 10 | name/code mismatch는 review까지 안 보냄 | confidence=medium + notes로 신호. 명백한 오류는 audit raw 컬럼으로 추후 검토 가능. review_needed는 단일종목 KRX 미매칭으로만 트리거 |
| 11 | 기존 v1 데이터는 14→6 매핑 대신 reset | v1 OOS는 `report_type='기타'` 강제로 풍부함이 이미 손실. 14→6 매핑(특히 ESG/부동산/파생/채권 → 산업)은 거친 변환이라 v2 재분류가 더 정확. 부분 마이그레이션의 정합성 복잡도(`publisher_type='company'` 잔존, IR row의 `tagging_status` 등)도 모두 사라짐. 비용은 ~$14 1회 |

## 6. 산출물

1. **migration 003** `migrations/003_v2_redesign.sql`
   - **transaction 안에서 실행** (BEGIN/COMMIT) — 도중 실패 시 rollback
   - 순서: ① 기존 CHECK 3개 DROP → ② **모든 태깅 메타데이터 reset (UPDATE → NULL/'{}', tagging_status='pending')** → ③ 컬럼 ADD/DROP (raw 추가, topics DROP) → ④ 새 CHECK 3개 ADD → ⑤ raw GIN 인덱스 추가
   - report_type CHECK: 14종 → 6종
   - out_of_scope_reason CHECK: 4종 → 5종 (+ ir_self)
   - publisher_type CHECK: 5종 → 4종 (- company)
   - 신규 컬럼: `stock_codes_raw text[] NOT NULL DEFAULT '{}'`, `company_names_raw text[] NOT NULL DEFAULT '{}'`
   - 신규 GIN 인덱스: `ix_reports_stocks_raw_gin`, `ix_reports_companies_raw_gin` (audit 시나리오 G)
   - drop: `topics text[]` 컬럼 + `ix_reports_topics_gin` 인덱스
   - 기존 v1 데이터는 reset → v2 backfill로 재태깅 (§13)

2. **vocabulary 변경**:
   - `publishers.yaml` — `해당기업` 항목의 `publisher_type_override: company` 라인 **제거** (other 섹션 안에 그대로 두면 자동으로 publisher_type='other'). LLM이 IR자료 발행 주체를 매칭할 수 있도록 항목 자체는 유지.
   - `topics.yaml` — **삭제**
   - `taxonomy.yaml` — report_type 14→6, oos 5종, publisher_type 4종, **`sector_major_aliases` 삭제** (KRX entry가 sector_major 답지를 직접 제공하므로 alias 매핑 불필요)

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

`resolve_krx`가 sector enrich·product 회수·종목명 정규화를 모두 흡수.
`published_at` 폴백은 `resolve_krx` 안에서 처리.
publisher canonicalization은 v2에서 LLM이 직접 출력 (별도 노드 불필요).

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
    krx_lookup_skipped: bool                      # 산업/전략·시황은 True (KRX 시도 자체 안 함)
    krx_matched: bool                              # 매칭 entry가 1개 이상 존재
    krx_entries: list[KRXEntry]                    # 단일종목=0~1, 섹터=0~N, 산업/전략·시황=[]
    krx_name_code_mismatch: bool                   # 단일종목에서 stock_code 매칭이지만 entry.name이 raw에 없음
    stock_codes_final: list[str]                   # KRX 매칭이면 [entry.code, ...], 아니면 []
    company_names_final: list[str]                 # KRX 매칭이면 [entry.name, ...], 아니면 raw fallback
    sectors_major_final: list[str]                 # entries union (set 병합)
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

**`krx_entry`(단일) → `krx_entries`(리스트)**: 섹터 리포트가 여러 종목을 포함할 수 있어 N개 entry aggregate가 필요. 단일종목은 [0..1], 섹터는 [0..N], 산업/전략·시황은 항상 [].

**`krx_lookup_skipped`**: 산업/전략·시황은 KRX lookup을 시도하지 않으므로 `krx_matched=False`만으로 review_needed로 보내면 안 됨 — `decide_status`가 이 키를 `report_type` 분기 없이 단독 사용해도 안전하도록 보조 신호로 둠.

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

`vocabulary/publishers.yaml`:
- `해당기업` 항목의 `publisher_type_override: company` 라인 **제거** ('other' 섹션 안에 두면 자동으로 publisher_type='other')
- 항목 자체는 유지 — IR자료의 발행 주체를 LLM이 매칭할 수 있도록
- **system_prompt에 본문 그대로 주입**해서 LLM이 vocab 보고 자의적 매핑

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

### 9.6 `status_oos` (변경 — `ir_self` high 추가)

v1 코드는 `confidence = "high" if reason in ("foreign","fund","digital") else "medium"`이라 새 reason `ir_self`가 medium으로 떨어짐. v2에서 high로 추가:

```python
def status_oos(state: RowState) -> dict:
    reason = state["oos_reason"]
    confidence = "high" if reason in ("foreign","fund","digital","ir_self") else "medium"
    return {
        "is_oos": True,
        "tagging_status": "auto",
        "tagging_confidence": confidence,
        "tagging_notes": None,
    }
```

`is_oos=True`, `tagging_status='auto'`, confidence:
- foreign/fund/digital/ir_self: `high`
- private: `medium` (보더라인 — 비상장 판단이 LLM heuristic에 의존)

### 9.7 `status_unreadable` (그대로)

### 9.8 `resolve_krx` (신규 — canonicalize+validate+enrich 통합)

`report_type`별로 KRX lookup 정책이 다르다.

| report_type | KRX lookup | entry 개수 | sectors/products |
|---|---|---|---|
| 단일종목 | stock_code 우선, 미매칭 시 회사명 fallback | 0~1 | 매칭 entry 1개의 답 |
| 섹터 | stock_code+회사명 모두 시도, dedupe | 0~N | entry들 union (set 병합) |
| 산업 / 전략·시황 | **skip** (lookup 안 함) | 0 | 빈 배열 |
| 기타 (in-scope, OOS 아님) | 단일종목과 동일 | 0~1 | 매칭 entry 1개의 답 |

`name/code mismatch`는 단일종목에서 stock_code 매칭이 성공했을 때만 의미가 있으므로 그 경로에서만 감지한다 (회사명 fallback이나 섹터 N-aggregate에선 검사 안 함).

```python
def resolve_krx(state, *, krx) -> dict:
    raw = state["llm_raw"]
    rt = raw.report_type

    # ── 산업 / 전략·시황: KRX lookup 자체를 skip ──────────────────────
    if rt in ("산업", "전략·시황"):
        return _finalize(state, raw, krx=krx, entries=[], skipped=True, mismatch=False)

    # ── 단일종목 / 섹터 / 기타: KRX 시도 ─────────────────────────────
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

    # 4. 단일종목/기타는 1개로 자른다 (실수로 N개가 들어와도 안전)
    if rt in ("단일종목", "기타") and len(entries) > 1:
        entries = entries[:1]

    # 5. name/code mismatch 감지 (단일종목 + stock_code 매칭 케이스만)
    mismatch = False
    if rt == "단일종목" and entries and code_match_any and raw.company_names_raw:
        norm_entry = "".join(entries[0].name.split()).lower()
        norm_raws  = ["".join(n.split()).lower() for n in raw.company_names_raw]
        mismatch = norm_entry not in norm_raws

    return _finalize(state, raw, krx=krx, entries=entries, skipped=False, mismatch=mismatch)


def _finalize(state, raw, *, krx, entries, skipped, mismatch) -> dict:
    """entries → final 컬럼 + published_at fallback. lookup 결과를 직렬화한다."""
    if entries:
        sm = []
        smn = []
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
            "company_names_final": [e.name for e in entries],   # KRX 정식 표기로 통일
            "sectors_major_final": sm,
            "sectors_minor_final": smn,
            "products_final": prods,
        }
    else:
        # entries가 비어있는 경우: 산업/전략·시황(skipped=True), 또는 KRX 미매칭(skipped=False)
        if skipped:
            company_names_final = []   # 산업/전략·시황은 회사명 자체가 의미 없음
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

**핵심 단순화**:
- LLM이 sectors/products를 추출 안 하므로 검증 단계 불필요
- 산업/전략·시황은 KRX 시도 안 함 (회사 1개로 대표 불가) — `krx_lookup_skipped=True`로 표시해 `decide_status`가 review_needed로 보내지 않게 함
- 단일종목/기타: 1 entry, 섹터: N entry union
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
    rt = raw.report_type if raw else None

    # 단일종목 + KRX 미매칭만 review_needed (IPO 예정/상장예정/오타 등)
    # 산업/전략·시황은 krx_lookup_skipped=True로 매칭이 의미 없음 → auto OK
    # 섹터는 0개 매칭이어도 정상 케이스 (peer reference 없는 산업·테마 리포트) → auto OK
    if rt == "단일종목" and not state.get("krx_matched"):
        return {"tagging_status":"review_needed","tagging_confidence":"low",
                "tagging_notes":"krx_unmatched_in_scope:ipo_pending_or_unknown"}

    # type_indeterminate (LLM이 자체 신뢰도 low이고 report_type='기타')
    if rt == "기타" and raw is not None and raw.self_confidence == "low":
        return {"tagging_status":"review_needed","tagging_confidence":"low",
                "tagging_notes":"type_indeterminate"}

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

**제거된 분기**:
- unknown_stock_code/sector/product/publisher (vocab 검증 자체가 사라짐)
- topic_unmapped (topics 폐기)
- publisher_canon=None 분기 (LLM이 직접 매핑 — null이어도 정상 케이스)

**review_needed 트리거** (4종): `first_page_unreadable`, `llm_refusal:*`, `krx_unmatched_in_scope:ipo_pending_or_unknown`, `type_indeterminate`.

**`auto/medium` 신호** (`high`로 두지 않는 케이스): `used_fallback`(published_at sent_at fallback 또는 1p가 아닌 페이지 사용) 또는 `krx_name_code_mismatch`. 둘 다 audit raw 컬럼으로 추후 확인 가능 — review까지 강제하진 않음.

### 9.10 `write` (변경)

UPDATE_SQL 컬럼 변경 — `topics` 제거, `stock_codes_raw`/`company_names_raw` 추가. payload는 19-arg 위치 placeholder.

OOS row 처리 정책:
- **`report_type`은 LLM 분류 그대로 유지** (예: `단일종목+foreign`, `IR자료+ir_self`). 강제 변환 없음 → migration 003의 IR자료 처리(`report_type='IR자료'` 유지)와 일관.
- **publisher_canon/publisher_type은 LLM 출력 그대로 유지**. IR자료의 발행 주체는 LLM이 publishers vocabulary의 `해당기업`을 보고 매칭하므로 신규/migrated row 모두 `publisher='해당기업', publisher_type='other'`로 통일됨.
- 분석가/title은 비-OOS와 동일하게 보존 (분포 분석 풍부).
- 분류 본체(stock_codes/company_names/sectors/products)는 비움.
- audit raw(stock_codes_raw/company_names_raw)는 OOS도 LLM 출력 그대로 보존.

```python
def _build_payload(state, taxonomy_version) -> tuple:
    raw = state.get("llm_raw")
    is_oos = bool(state.get("is_oos"))

    # OOS 케이스
    if is_oos:
        return (
            state["id"],                                  # $1
            None,                                          # $2 published_at (OOS는 null)
            (raw.report_type if raw else None),            # $3 report_type — LLM 분류 그대로 (IR자료는 'IR자료')
            (raw.publisher_canon if raw else None),        # $4 publisher_canon
            (raw.publisher_type if raw else None),         # $5 publisher_type
            list(raw.analysts) if raw else [],             # $6 analysts
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

매칭 방식: `tagging_notes`가 prefix 형태(`krx_unmatched_in_scope:ipo_pending_or_unknown`, `llm_refusal:<error>`)이므로 `:` 앞 prefix만 비교. `krx_name_code_mismatch`는 review_needed가 아닌 `auto/medium` notes이므로 review_reasons에 포함되지 않음 (audit 시나리오 G에서 별도로 조회).

## 11. migration 003

**전략 변경**: 기존 v1으로 태깅된 데이터(auto=3,317, review_needed=73, oos_total=151)를 14→6 매핑으로 부분 변환하지 않고 **모두 비우고 `pending`으로 reset**한다. v2가 backfill 모드로 다시 태깅한다.

**근거**:
- v1 OOS row는 `report_type='기타'` 강제로 저장됐으므로 OOS 분포 풍부함이 이미 손실됨
- 14→6 매핑(특히 ESG/부동산/파생/채권 → 산업)은 거친 변환이라 v2가 새로 분류하는 게 더 정확
- 기존 `publisher_type='company'` 잔존 처리, IR row의 `tagging_status` 정합성 등 부분 마이그레이션 복잡도가 모두 사라짐
- PDF 파일은 storage에 그대로 보존 — reset되는 것은 DB의 태깅 메타데이터만

```sql
-- migrations/003_v2_redesign.sql

BEGIN;

-- ============================================================
-- 1. 기존 CHECK 제약 DROP (reset에서 NULL 허용에 필요)
-- ============================================================
ALTER TABLE reports DROP CONSTRAINT IF EXISTS chk_report_type;
ALTER TABLE reports DROP CONSTRAINT IF EXISTS chk_out_of_scope_reason;
ALTER TABLE reports DROP CONSTRAINT IF EXISTS chk_publisher_type;

-- ============================================================
-- 2. 모든 태깅 메타데이터를 비우고 pending 상태로 reset
--    PDF 파일/메시지 메타(file_path, sent_at, caption 등)는 그대로 보존.
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

**reset 후 상태**:
- 모든 row가 `tagging_status='pending'`, 모든 분류 컬럼 NULL/빈 배열
- 신규 `stock_codes_raw`, `company_names_raw`는 default `'{}'` (비어있음)
- `idx_reports_untagged` (001_init.sql, `where tagged_at is null`)이 다시 모든 row를 가리킴
- v2 backfill: `python -m langgraph_tagger run --backfill-days <전체 기간>` 또는 평소 `pending` 큐 처리

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
| G (신규) | KRX 미매칭 분석 (audit) | `tagging_notes LIKE 'krx_unmatched_in_scope%'` 또는 `tagging_notes='krx_name_code_mismatch'`인 row의 `stock_codes_raw`/`company_names_raw` 검토 |
| H (신규) | OOS IR자료 분포 | `out_of_scope_reason='ir_self'` (report_type='IR자료'와 일관) — v2 재태깅 후 모든 row가 v2 정책으로 통일됨 |
| I (신규) | OOS 분포의 type별 분석 | `report_type` × `out_of_scope_reason` 교차 (예: 단일종목+foreign 비중) — v2가 OOS row의 report_type을 강제 변환 안 함 + reset으로 v1 흔적 제거 |

## 13. 기존 row 처리 (reset → v2 재태깅)

inspect 결과: `auto=3,317`, `review_needed=73`, `oos_total=151`. 모두 v1 코드로 태깅된 데이터.

**전략**: migration 003 step 2가 모든 태깅 메타데이터를 비우고 `tagging_status='pending'`으로 reset. PDF 파일은 storage에 그대로 보존되어 v2가 모두 재태깅한다.

| 영역 | reset 후 상태 |
|---|---|
| `published_at`, `report_type`, `publisher`, `publisher_type`, `title`, `out_of_scope_reason`, `tagging_*`, `tagger_version`, `taxonomy_version`, `tagged_at` | NULL |
| `analysts`, `stock_codes`, `company_names`, `sectors_major`, `sectors_minor`, `products` | `'{}'` (빈 배열) |
| `topics` | 컬럼 자체 DROP |
| `stock_codes_raw`, `company_names_raw` | default `'{}'` |
| `tagging_status` | `'pending'` |
| 보존 | `id`, `message_id`, `chat_username`, `sent_at`, `downloaded_at`, `file_*`, `caption`, `tags` (PDF/메시지 메타) |

**v2 재태깅 트리거**: 전체가 `pending`이므로 평소 `python -m langgraph_tagger run --batch-size N`을 반복하거나, `--backfill-days <전체 기간>`으로 한 번에 처리. v1 backfill로 다운로드된 PDF는 모두 storage에 있으므로 추가 다운로드는 발생하지 않음.

**비용 추정** (gpt-5.4-mini, ~3,541건): v1 dry-run 기준 row당 약 0.4¢ × 3,541 ≈ $14 — backfill 시 한 번 발생.

**손실되는 정보** (v1 데이터에서):
- v1의 14종 분류는 v2의 6종으로 새로 분류됨 (운영 분석상 더 정확)
- v1의 `topics` 데이터는 컬럼과 함께 영구 폐기 (사용자 결정 — 결과물 활용도 낮음). 백업 필요 시 migration 전 export 권장
- v1의 OOS row는 `report_type='기타'` 강제 저장이라 LLM 원분류는 이미 손실 상태였음 — reset은 추가 손실 없음

## 14. v1 commit 매핑 (incremental rev-5)

| v1 영역 | v2 변경 |
|---|---|
| Task 1 (migration 002 + KRX CSV) | migration 003 추가: BEGIN/COMMIT transaction wrap, DROP CONSTRAINT 먼저, **모든 태깅 메타데이터 reset (UPDATE → NULL/'{}', tagging_status='pending')**, 컬럼 ADD/DROP (raw 추가, topics DROP), 새 CHECK ADD, raw GIN 인덱스 2개 |
| Task 2 (package skeleton) | 그대로 |
| Task 3 (taxonomy/publishers/topics YAML) | topics.yaml **삭제**, taxonomy.yaml report_types 6종/oos 5종/publisher_type 4종, **publishers.yaml의 `해당기업: publisher_type_override: company` 라인 제거** |
| Task 4 (vocabulary __init__) | `lookup_publisher`/`map_topics` 삭제. `taxonomy()` 유지 |
| Task 5 (KRX index) | `lookup_by_name` 신규, `has_product`/`filter_*` 삭제 |
| Task 6 (state.py + llm_schemas.py) | 둘 다 v2 schema로 재정의. RowState에 `krx_lookup_skipped`/`krx_entries`/`krx_name_code_mismatch` 추가 |
| Task 7 (prompts.py) | publishers.yaml 본문 주입, 6종 enum, 1~3p, 단일종목 정의에 IPO 예정 명시, IR자료 publisher 매칭 안내 |
| Task 8 (extract_pdf) | max_pages=3 |
| Task 9 (llm_extract) | 그대로 (호출만, schema는 새 LLMExtraction) |
| Task 10 (oos_gate + mark_oos_reason) | 둘 다 룰 변경 (IR자료 분기 + ir_self) |
| Task 11 (status_oos + status_unreadable) | **status_oos 변경**: high tier에 `ir_self` 추가 (foreign/fund/digital/ir_self → high, private → medium). status_unreadable은 그대로 |
| Task 12 (canonicalize) | **삭제** |
| Task 13 (validate) | **삭제** |
| Task 14 (enrich) | **삭제 + resolve_krx 신규** — report_type별 분기 (단일종목 1 / 섹터 N / 산업·전략·시황 skip / 기타 1) + name_code_mismatch 감지 + entries union |
| Task 15 (decide_status) | 단순화. review_needed는 단일종목+krx_unmatched / type_indeterminate / pdf_unreadable / llm_refusal 4종만. mismatch는 `auto/medium`으로 강등 |
| Task 16 (write + supabase_io) | UPDATE_SQL 19개 placeholder, 컬럼 변경. **OOS payload는 LLM의 report_type/publisher_canon/publisher_type/title/analysts 모두 보존** (`'기타'` 강제 안 함) |
| Task 17 (graph assembly) | 노드 wiring 변경 (8 노드) |
| Task 18 (orchestrator) | 그대로 (review_reasons set: `first_page_unreadable`, `llm_refusal`, `krx_unmatched_in_scope`, `type_indeterminate`) |
| Task 19 (config + CLI) | 그대로 |
| Task 20 (parity) | fixtures 6종/5 OOS로 재구성. mismatch 케이스 fixture 1개 추가 권장 |
| Task 21 (golden PDFs) | 그대로 (여전히 유효) |
| Task 22 (live verification) | migration 003 적용 → 새로 dry-run → 결과 검토 |

## 15. 의존성 (변경 없음)

`langgraph>=1.0`, `openai>=2.11`, `pymupdf>=1.24`, `pyyaml>=6.0`, `asyncpg>=0.29`, `pydantic>=2.7`. 모두 v1에서 설치됨.

## 16. brainstorming → 구현 분기

본 spec의 후속 단계는 superpowers의 `writing-plans` skill로 v2 task list 작성. 변경 폭이 크지만 v1의 22 task에 매핑되므로 ~12~15 task 예상 (대부분 기존 코드 변경, 3개 삭제, 1개 신규 노드, migration 003 + publishers.yaml 정정).

**우선 순위**:
1. migration 003 (transaction wrap, DROP→UPDATE→ADD 순서) — 다른 모든 변경의 기반
2. publishers.yaml 정리 + taxonomy.yaml 6종/4종 — vocab 정합성
3. llm_schemas + state — 새 schema
4. prompts — 새 vocabulary 주입
5. resolve_krx 신규 + canonicalize/validate/enrich 삭제 — 노드 흐름
6. decide_status + write — 새 정책 반영
7. 테스트 + parity fixtures 재구성
8. dry-run 후 live verification
