# Analytics Dashboard (Phase 1) — Design

태거가 분류·매핑한 리서치 메타데이터를 운영자(1인)가 **종목 단위 시계열**과 **매크로 트렌드** 두 관점에서 탐색할 수 있는 로컬 Streamlit 웹 대시보드.

LLM 요약(톤·포인트·리스크) 백필과 시계열 변화 분석은 Phase 2/3로 분리. 본 spec은 **기존 v2 스키마의 메타데이터만으로 즉시 가능한 분석 view**에 집중하며, 데이터가 실제로 담고 있는 정보의 범위를 솔직히 반영한다.

## 1. Why

- 매일 신규 리서치가 collector·tagger를 거쳐 `tagging_status='auto'` 또는 `'verified'`로 in-scope 분류 완료됨. 그러나 운영자는 이 데이터를 직접 사용할 출구가 없음. PDF가 디스크에 쌓이고 Supabase에 메타가 쌓이는데 활용 통로가 없으면 가치 0.
- 운영자가 자주 갖는 질문:
  - **종목 단위**: "이 종목을 누가 언제 다뤘나 / 발행처별 view는?" — 종목 dashboard.
  - **매크로 단위 (두 갈래)**: ① "어느 sector·제품이 최근 (KRX 매핑된) 리서치에서 자주 다뤄지나?" — sector coverage. ② "산업·전략·시황 리포트 자체의 발행량 추이는?" — report type volume.
- 운영자는 1인(레포 소유자), 로컬에서만 사용. 외부 노출 없음 → 인증·동시성 부담 없음.

## 2. Goals

1. **매크로 페이지 — Sector coverage sub-tab**: 산업 level(대/중/제품) 선택 + 산업 multi-select(검색 가능) + 기간/단위 필터 → KRX-mapped explicit coverage(stock_codes 비어있지 않은 in-scope 리서치)의 sector 분포 **시계열 차트** + 해당 산업 내 종목 **coverage ranking**.
2. **매크로 페이지 — Report type volume sub-tab**: report_type별 발행량 시계열 (단일종목 / 산업 / 섹터 / IR자료 / 전략·시황 / 기타). OOS 포함 여부 toggle.
3. **종목 dashboard**: 종목 1개에 대해 헤더(섹터·총 발행수·즐겨찾기 토글·기간) + 시계열 차트 + 발행처 분포 pie + 발행 리스트(PDF 클릭 열기). "KRX-mapped explicit coverage only" 한 줄 명시.
4. **즐겨찾기**: 자주 보는 종목을 sidebar에 영구 노출, 클릭 1번으로 dashboard 진입. 추가·해제 가능.
5. **종목 검색**: sidebar의 검색 박스에서 종목 code 또는 회사명 입력 → KRX 마스터 기반 자동완성 → 선택 시 dashboard.

## 3. Non-goals

- **LLM 리포트 요약(톤·포인트·리스크) 추출 및 표시** — Phase 2 범위.
- **시계열 변화 분석**(예: "이 종목의 톤 변화") — Phase 3.
- **본문 mention 종목 추출** — 현재 태거는 보고서 1페이지 헤더의 명시 종목만 보수적으로 추출. 산업·전략 리포트 안에 본문 언급된 종목은 `stock_codes`에 없음. 본문 mention 보강은 Phase 3 후보.
- **외부 노출 / 다중 사용자 / 인증** — localhost 1인 전용.
- **모바일 레이아웃** — 데스크탑 브라우저 1280×720↑ 가정.
- **review_needed 처리 도구** — review_viewer가 별도. 본 대시보드는 in-scope 데이터만 표시(단 Report type volume sub-tab은 OOS toggle로 옵션 노출).
- **PDF 본문 검색** — Phase 미정. title/caption text만 노출.
- **`published_at`의 source 분리(LLM 추출 vs sent_at fallback)** — 태거가 NULL일 때 sent_at KST date로 `published_at_final`을 채워 DB의 `published_at`에 저장하므로, source flag는 현재 DB에 없음. 별도 컬럼 추가는 Phase 2 작업 시 같이 처리. Phase 1엔 "발간일" 단일 표기.

## 4. Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│ Browser (localhost:<streamlit default port>)                       │
│ ┌──────────────────┬─────────────────────────────────────────────┐ │
│ │ Sidebar          │ Main (mode-driven)                          │ │
│ │  [🔍 종목 검색]   │                                              │ │
│ │  ⭐ 즐겨찾기      │  [모드 1] 📊 매크로 트렌드                    │ │
│ │   ▸ 005930       │   ├─ Sector coverage (sub-tab)                │
│ │   ▸ 000660       │   │   selector(level/period/unit/산업)        │ │
│ │   ▸ ...          │   │   좌 시계열 line  /  우 종목 ranking        │ │
│ │  📊 매크로        │   └─ Report type volume (sub-tab)             │
│ │                  │       toggle: OOS 포함 (default off)         │ │
│ │                  │       report_type별 발행량 시계열             │ │
│ │                  │                                              │ │
│ │                  │  [모드 2] ⭐ 종목 dashboard                    │ │
│ │                  │     헤더 (종목·섹터·총 발행수·★·기간 필터)     │ │
│ │                  │     "explicit KRX-mapped coverage only" 표시  │ │
│ │                  │     좌 시계열  /  우 발행처 분포 pie           │ │
│ │                  │     하단 발행 리스트(PDF 열기)                │ │
│ └──────────────────┴─────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
                                  ↑↓
         ┌────────────────────────┴──────────────────────────┐
         │ Streamlit single-page app (Python, sync)          │
         │  - session_state: current_mode, current_stock,    │
         │    filters, oos_include                           │
         │  - data fetch: paginated raw rows + pandas agg    │
         │  - cache: @st.cache_data(ttl=180) on fetchers     │
         │  - charts: Plotly                                 │
         │  - KRX master: docs/stock_data/KRX_stocks_data.csv│
         │  - favorites: ~/.review_viewer/favorites.json     │
         └─────────────────┬─────────────────────────────────┘
                           ↓ supabase-py REST (.range pagination)
                    ┌──────┴────────┐
                    │ Supabase      │
                    │ reports 테이블 │
                    └───────────────┘
```

Single-page Streamlit app. `st.tabs` 또는 사이드바 분기로 모드 전환. 데이터 fetch는 client-side 집계 패턴: in-scope 필터·기간 필터만 Supabase 측에서 적용해 raw rows fetch → pandas에서 group-by/unnest/date_trunc 집계. PostgREST가 native group-by를 지원하지 않으므로 RPC 함수 신설보다 client-side 집계가 단순. Streamlit `@st.cache_data(ttl=180)`로 같은 필터 반복 fetch를 회피.

## 5. Components

신규 패키지 `langgraph_tagger/analytics/`:

| 파일 | 책임 |
|---|---|
| `app.py` | Streamlit entry. sidebar 렌더, main 모드 라우팅(매크로/종목), session_state 관리. |
| `config.py` | `AnalyticsConfig` — viewer가 필요한 env만 (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `STORAGE_BASE_DIR`, `KRX_CSV_PATH`). review_viewer와 같은 분리 원칙 — 태거·collector envs 요구 안 함. |
| `db.py` | Supabase 쿼리 wrapper. 5종 fetcher (모두 `@st.cache_data(ttl=180)`): `fetch_inscope_rows(period)` (raw rows), `fetch_inscope_or_oos_rows(period, include_oos)` (Report type volume용), `fetch_stock_rows(code, period)`, `fetch_stock_publisher_rows(code, period)`, `fetch_stock_report_list(code, period, limit, offset)`. **1000-row page loop 필수** — Supabase PostgREST의 기본 max는 1000 row이므로 `.range(offset, offset+999)` 반복으로 전부 가져옴. fetcher는 컬럼·기간 외엔 필터 안 함; 집계는 client-side. |
| `aggregate.py` | pandas 집계 pure functions: `sector_timeseries(df, level, items, unit)`, `sector_ranking(df, items, level, limit)`, `report_type_timeseries(df, unit, include_oos)`, `stock_monthly(df, unit)`, `publisher_dist(df, top_k)`. 모두 DataFrame in, DataFrame out. unnest는 pandas `.explode()` 활용. |
| `krx.py` | KRX 마스터 CSV 로딩(`@st.cache_data` once). `search_stocks(query)` — code 또는 회사명 부분일치 자동완성. `lookup(code) → (code, name, sector_major)`. |
| `favorites.py` | `load()` / `add(code)` / `remove(code)` — JSON 파일 read/write (`~/.review_viewer/favorites.json`). atomic write (tempfile + os.replace). 손상 시 backup 후 빈 리스트. |
| `charts.py` | Plotly figure builder: `timeseries_line(df, x, y_cols, title)`, `report_type_lines(df, include_oos)`, `monthly_bar(df, x, y, title)`, `publisher_pie(df, label, value)`, `ranking_bar(df, label, value)`. |
| `pages/macro.py` | 모드 1 렌더. 내부 sub-tab 2개: `sector_coverage_tab(session)`, `report_type_tab(session)`. |
| `pages/stock.py` | 모드 2 렌더. db.fetch_stock_* → aggregate → charts + 리스트. 하단 발행 리스트는 PDF `open_locally(path)`로 OS 뷰어 띄움 (review_viewer pdf.py 재사용 가능, 또는 동일 패턴 inline). |
| `__main__.py` | `python -m langgraph_tagger.analytics` → `streamlit run app.py` + `--server.headless=true --browser.gatherUsageStats=false` (review_viewer와 동일 패턴). |
| `tests/test_krx.py` | KRX search/lookup pure logic. |
| `tests/test_favorites.py` | JSON read/write round-trip + 빈 파일 / 잘못된 JSON 복구. |
| `tests/test_aggregate.py` | pandas 집계 함수 5종 단위 테스트 (작은 fixture df → 기대 출력). |
| `tests/test_db.py` | 5종 fetcher mock 검증 — in-scope 필터 자동 적용 (단 `fetch_inscope_or_oos_rows`는 toggle 시 OOS 포함), 1000-row pagination loop 호출, cache 동작. |
| `tests/test_charts.py` | Plotly Figure 객체 type + 입력 컬럼 정합성. |

UI 페이지(`app.py`, `pages/*.py`)는 manual smoke로 검증.

## 6. Pages

### 6.1 Macro (모드 1, default 진입)

상단에 sub-tab 2개. `st.tabs(["Sector coverage", "Report type volume"])`.

#### Sub-tab A: Sector coverage

> **명명 원칙**: 이 view는 "KRX-mapped explicit coverage(stock_codes 비어있지 않은 in-scope 리서치)의 sector tag 분포"이다. 진짜 "산업 트렌드"가 아니라 "리서치에서 그 sector가 얼마나 자주 나오는지". 어떤 row가 포함되는지는 태거 동작에 따라 결정됨: `report_type='단일종목'`은 stock_codes+sectors 모두 채워져 들어오고, `report_type='섹터'`는 stock_codes·sectors가 (멀티 종목으로) 채워질 수 있어 같이 포함, `report_type='산업'`이나 `'전략·시황'`은 태거가 stock_codes/sectors를 빈 배열로 두므로 자연스럽게 빠진다. 별도 `report_type` 필터는 적용하지 않는다 — 데이터의 explicit coverage가 곧 view의 정의.

상단 selector:
- **집계 level** (segmented control, 3택): `산업(대)` / `산업(중)` / `제품`
- **기간** (dropdown): `최근 30일 / 90일 / 180일 / 1년 / 전체`. default = 90일.
- **단위** (dropdown): `일별 / 주별 / 월별`. default = 주별.
- **산업 multi-select** (검색 가능 chip 형태): 선택한 level의 unique values에서 선택. 비어있으면 발행량 top 10 자동.

좌측(2/3): **시계열 line chart** — x=시간 bucket, y=발행 row 수(unnest 후), line=선택한 산업당 1개. legend 클릭으로 toggle.

우측(1/3): **종목 coverage ranking 표** — 선택 산업에 속하는 (stock_codes 비어있지 않은) in-scope 리서치의 `stock_codes`를 unnest 후 count desc top 20. UI 라벨: **"coverage volume — 이 채널에서 다뤄진 횟수 (시장의 hot 지표 아님)"**. 행 클릭 → `current_mode='stock'`, `current_stock=code`, rerun.

#### Sub-tab B: Report type volume

상단 selector:
- **기간** (dropdown): 동일.
- **단위** (dropdown): 동일.
- **OOS 포함 toggle** (`st.toggle`, default **off**): 켜면 `tagging_status='verified' AND out_of_scope_reason IS NOT NULL`인 행도 포함 (운영자가 직접 OOS 처리한 행 + 자동 OOS 둘 다). IR자료(`out_of_scope_reason='ir_self'`), 외국 리포트(`foreign`) 등이 보이게 됨.

차트: **report_type별 line chart** — x=시간 bucket, y=발행 건수, line=6가지 report_type(단일종목/산업/섹터/IR자료/전략·시황/기타). toggle off일 때 IR자료 라인은 사실상 0에 가까울 수 있음(현재 IR자료는 자동 OOS=ir_self로 마감되므로). 차트 하단 footnote에 정책 한 줄 명시.

### 6.2 Stock dashboard (모드 2)

헤더:
- 좌측: `{code} {company_name}`. 그 아래 작은 글씨로 `{sector_major} · {sector_minor} · 총 발행수 N건 · explicit KRX-mapped coverage only`.
- 우측: **기간 dropdown** + **★ 즐겨찾기 토글 버튼**.

좌측(2/3): **월별/주별 발행 시계열 막대 차트** — 기간 dropdown 따름. hover 시 해당 bucket 행 미리보기.

우측(1/3): **발행처 분포 pie chart** — 같은 기간 행을 publisher별로 집계. top 5 + "기타". 발행처 클릭 시 Phase 1은 단순 표시(필터링은 future).

하단 전체폭: **발행 리스트 표** —
- 컬럼: `발간일 | 발행처 | 제목 | 유형 | PDF`
- 정렬: 발간일 desc.
- 발간일은 DB의 `published_at` 그대로(태거가 LLM 추출 또는 sent_at fallback으로 채운 통합 값). source 구분 표시는 Phase 1엔 안 함 — DB에 source flag가 없기 때문.
- `PDF` 컬럼: 버튼 클릭 → `open_locally(path)` (OS 기본 PDF 뷰어).
- pagination: 20행씩 + "더 보기" 버튼.

## 7. Sidebar (모든 모드 공통)

- **🔍 종목 검색**: `st.selectbox(options=krx_master, format='code name')` — 타이핑하면 KRX 마스터에서 code/name 부분일치 자동완성. 선택 시 stock 모드 전환.
- **⭐ 즐겨찾기**: 저장된 종목 리스트. 클릭 시 stock 모드 전환. 현재 모드가 stock이고 그 종목이면 highlight.
- **📊 매크로**: 클릭 시 매크로 모드 전환.

sidebar는 항상 노출. 모드 전환은 main만 바뀜.

## 8. Data semantics

### Default in-scope 필터

대부분 view의 fetch 단계에 기본 적용:
```sql
WHERE tagging_status IN ('auto', 'verified')
  AND out_of_scope_reason IS NULL
```

Sector coverage, Stock dashboard, 종목 검색 자동완성 빈도 등 모두 이 필터.

### Report type volume의 OOS toggle 정책

`fetch_inscope_or_oos_rows(period, include_oos)`:
- `include_oos=False` (default): 위 in-scope 필터 그대로.
- `include_oos=True`: `tagging_status IN ('auto', 'verified')` 만 적용, `out_of_scope_reason`은 무관(NULL 또는 set 모두 포함). 즉 IR자료/foreign/private/digital이 다 들어옴.

`pending` / `processing` / `review_needed`는 어느 경우든 제외.

### 발간일

DB `published_at` 컬럼 그대로 사용. 태거 [resolve_krx.py](/langgraph_tagger/nodes/resolve_krx.py)가 LLM 추출 발간일이 NULL일 때 `sent_at`의 KST date로 채워 [write.py](/langgraph_tagger/nodes/write.py)가 DB에 저장한다. 즉 DB의 `published_at`은 "태거 통합 발간일"이며 Phase 1에서는 source 구분 없이 그대로 사용. source flag 컬럼은 Phase 2에서 LLM 요약 백필 작업할 때 같이 추가(migration 005 후보).

### 종목 매칭

`stock_codes` array에 해당 종목 code가 포함된 행. supabase-py에서 `cs`(contains) operator: `query.filter('stock_codes', 'cs', f'{{{code}}}')`. 단, 본 spec은 client-side 집계라 raw fetch 후 pandas `.explode('stock_codes')`로 처리.

### 산업 multi-select 매칭

"선택한 산업 중 하나라도 포함"이 의도. 따라서 array **overlap**: PostgREST `ov` operator (Postgres `&&`). client-side면 pandas `apply(lambda lst: any(x in selected for x in lst))`.

`cs`(contains)는 row가 선택 항목 **모두**를 포함해야 해서 다른 의미 — 사용 금지.

### Coverage volume metric

ranking 등에서 사용하는 카운트는 정의상 다음:
```
coverage_volume(stock_code, sector_filter, period) :=
  COUNT(row)  WHERE stock_code IN unnest(row.stock_codes)
              AND sector_filter overlaps (row[level])
              AND row.period_filter
```
- 발행 row가 여러 종목을 포함하면 각 종목에 1씩.
- 발행처별 발행 빈도 차이가 그대로 반영됨(가중치 없음).
- "이 채널 내 coverage volume"이지 시장 신호가 아님 — UI 라벨에 명시.

weighted count, momentum, unique_publishers 등은 Future.

### Raw fetch + pagination + cache

모든 fetcher 패턴:
```python
@st.cache_data(ttl=180)
def fetch_inscope_rows(period: str) -> pd.DataFrame:
    PAGE = 1000
    rows = []
    offset = 0
    while True:
        result = (
            sb.table('reports')
              .select('id, published_at, sent_at, report_type, publisher, '
                      'stock_codes, company_names, sectors_major, sectors_minor, '
                      'products, tagging_status, out_of_scope_reason, file_path, '
                      'file_name, title')
              .in_('tagging_status', ['auto', 'verified'])
              .is_('out_of_scope_reason', 'null')
              .gte('published_at', period_start_iso)
              .range(offset, offset + PAGE - 1)
              .execute()
        )
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return pd.DataFrame(rows)
```

Report type volume sub-tab의 `fetch_inscope_or_oos_rows`는 `.in_('tagging_status', ['auto', 'verified'])`까지만 적용하고 `is_('out_of_scope_reason', 'null')`는 toggle에 따라 추가/생략.

`ttl=180` (3분) — 운영자가 viewer 열어두고 종목 전환·sub-tab 전환 시 같은 필터는 cached 활용. 새 리서치 들어와도 3분 안에는 stale 가능 (수동 새로고침으로 비움).

In-scope row 수가 충분히 작아 클라이언트 메모리에 들어옴(전체 fetch ≪ 100MB 가정). 데이터 크게 늘면 Phase 2/3에서 server-side aggregation으로 마이그레이션.

## 9. Favorites storage

파일: `~/.review_viewer/favorites.json` (review_viewer와 같은 디렉터리 — 운영자 설정 한 곳).

스키마:
```json
{
  "stocks": ["005930", "000660", "373220"]
}
```

`favorites.load()` → list of codes (없으면 빈 리스트, 디렉터리 없으면 생성).
`favorites.add(code)` → set 의미로 중복 제거, atomic write.
`favorites.remove(code)` → 동일.

세션 간 유지. 운영자 manual 편집 OK. 손상 시 backup(`favorites.json.bak`) 후 빈 리스트로 시작.

## 10. Error handling

| 상황 | 처리 |
|---|---|
| Supabase 연결 실패 | 화면 상단 `st.error` + 재시도 버튼 |
| KRX_stocks_data.csv 없음 | `st.error("KRX 마스터 CSV가 없습니다: {path}")` + 검색·자동완성 동작 안 함. 매크로·즐겨찾기는 동작 |
| 선택 종목이 데이터에 없음 | "이 종목 다룬 in-scope 리서치가 아직 없습니다" + 즐겨찾기 토글은 동작 |
| 선택 산업이 데이터에 없음 | 매크로 시계열 빈 차트 + "선택한 산업의 데이터 없음" |
| PDF 파일 missing | 발행 리스트의 PDF 버튼 비활성화 + 회색 표시 |
| 즐겨찾기 파일 손상 | 빈 favorites fallback + `favorites.json.bak` 백업 |
| 빈 즐겨찾기 | sidebar에 "★ 즐겨찾기는 종목 dashboard의 ★ 버튼으로 추가" |
| Supabase pagination 중간 실패 | 부분 fetch된 rows로 차트 + 상단 warning(`st.warning`) "데이터 일부만 로드됨" |
| 데이터 fetch 5초 초과 | spinner(`st.spinner`) 표시. timeout 자체는 안 둠 |

## 11. Testing

자동 (pytest):
- `test_krx.py` — search by code/name 부분일치, lookup 정합, KRX CSV 누락 시 처리.
- `test_favorites.py` — load/add/remove round-trip, 빈 파일·없는 파일·손상 json 복구.
- `test_aggregate.py` — pandas 집계 5종 (작은 fixture df 입력 → 기대 출력). overlap 매칭 동작.
- `test_db.py` — fetcher 5종 mock 검증. in-scope 필터 자동 적용, OOS toggle 정상 동작, 1000-row pagination loop가 `.range()` 반복 호출, cache 데코레이터 적용.
- `test_charts.py` — Plotly Figure 객체 type 검증, 입력 컬럼 정합성.

수동 smoke:
- 매크로 진입 → Sector coverage 진입 → 산업 multi-select → 시계열 + ranking 정상.
- Sub-tab 전환 → Report type volume → toggle off/on으로 IR자료 라인 변화 확인.
- ranking 종목 클릭 → 모드 전환 → 그 종목 dashboard.
- sidebar 검색 종목 → dashboard 진입.
- ★ 즐겨찾기 토글 → 다음 세션에도 유지.
- 발행 리스트 PDF 클릭 → OS 뷰어 띄움.
- PDF 없는 행 → 비활성화 표시.

## 12. Dependencies

신규 (Plan 단계에서 `requirements.txt`에 추가될 예정 — 본 spec commit은 design 문서만 변경):
- `plotly` — interactive 차트 (line/bar/pie).
- `pandas` — client-side 집계 (Streamlit transitive 의존을 가정하지 않고 명시 추가).

기존 재사용:
- `streamlit` — review_viewer로 이미 추가됨.
- `supabase-py` — storage.py에서 이미 사용.

설치·실행 (구현 후):
```bash
pip install -r requirements.txt           # plotly, pandas 추가될 것
python -m langgraph_tagger.analytics      # streamlit run + headless (URL 직접 열기)
```

## 13. Future considerations (Phase 2/3 후보)

- **Phase 2 — LLM 요약 백필**: 각 리서치에서 톤·핵심 포인트·리스크 요인 추출. 새 컬럼 또는 별도 테이블. 같이 `published_at_source` / `used_sent_at_fallback` 컬럼 migration 005 추가.
- **Phase 3 — 종목 dashboard에 톤·포인트·리스크 시계열**: Phase 2 결과 활용.
- **본문 mention 종목 추출**: 산업·전략 리포트 본문에서 언급된 KRX 종목까지 추가 매핑. prompts.py 확장 + 백필.
- **PDF 본문 검색**: Postgres full-text 또는 pgvector.
- **발행처 dashboard**: 발행처 단위 분석.
- **export 기능**: 발행 리스트 CSV/Excel.
- **알림**: 즐겨찾기 종목 신규 리서치 들어오면 Slack/Telegram notify.
- **추가 ranking metric**: weighted count(`1 / len(stock_codes)`), momentum(`recent vs prior`), unique publishers.
- **Server-side aggregation**: 데이터 100MB+ 커지면 Postgres RPC functions로 group-by/unnest 마이그레이션.
