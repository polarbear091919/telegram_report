# Review Viewer — Design

LangGraph 태거가 `review_needed`로 분류한 행을 운영자(1인)가 한 화면씩 빠르게 검수하는 로컬 Streamlit 웹 viewer.

## 1. Why

- 태거가 `tagging_status='review_needed'`로 분류한 행은 사람이 손대지 않으면 절대로 `verified`로 진행되지 않음. 운영 큐에 무한정 누적되어 자동 분류 시스템의 신호(분포·정확도)를 흐리고, in-scope 분석에 빠뜨려야 할 행이 그대로 남음.
- Supabase 콘솔에서 한 건씩 row 클릭·UPDATE 하기엔 PDF 미리보기가 없고 클릭 수가 많음. 전용 viewer가 한 자리에서 PDF·LLM 결과·결정 버튼을 묶어 결정 비용을 최소화.
- 운영자는 1인(레포 소유자), 로컬에서만 사용. 외부 노출 없음 — 인증·동시성 부담 없음.

## 2. Goals

1. `tagging_status='review_needed'` 행을 **한 번에 한 건씩** 화면에 표시.
2. 각 행에 대해 운영자가 **네 가지 결정** 중 하나를 1~2 클릭으로 내릴 수 있음:
   - `verified` — LLM 결과 그대로 사람 검수 마감
   - `OOS<reason>` — 사실은 범위 밖. 분석 본체 필드 비우고 `out_of_scope_reason` 설정 후 `verified`로 마감
   - `re-tag` — LLM 추출 자체가 부적절(PDF 첫 페이지 읽기 실패 등). `tagging_status='pending'`로 reset해 다음 배치 사이클에 재태깅
   - `skip` — 결정 보류. 같은 세션에선 다시 안 보임, 다음 세션엔 다시 큐에
3. **PDF 본문 미리보기**가 동일 화면 좌측에 떠서 LLM 결과와 즉시 비교 가능.
4. 결정 직후 **자동으로 다음 행** 로드 (수동 next 클릭 없음).
5. **직전 1단계 undo** 가능 (실수 복구). 결정 전 row 전체 스냅샷을 메모리에 보관, undo 시 모든 필드 복원.

## 3. Non-goals

- LLM 추출 결과의 **field-level 직접 수정**은 v1 범위 아님. 잘못 추출된 stock_codes 등은 별도 SQL로 처리.
- **여러 운영자 동시 작업** 미지원. row-level lock 안 만듦.
- **외부 노출 / 인증** 미지원. localhost 전용.
- **모바일 레이아웃** 미지원. 데스크탑 브라우저 1280×720↑ 가정.
- **PDF 인터랙티브 뷰어**(검색·하이라이트·줌) 미지원. 페이지 이미지 렌더링 + OS 기본 PDF 뷰어로 별도 열기 링크로 대체.

## 4. Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│ Browser (localhost:<streamlit default port>)                       │
│ ┌────────────────────┬───────────────────────────────────────┐     │
│ │ PDF page images    │ Review Panel                          │     │
│ │ (좌, flex:2)       │  - 사유 highlight                     │     │
│ │ + [Open in OS      │  - 분류 (report_type, publisher…)     │     │
│ │   viewer] button   │  - 종목 매핑 (raw vs KRX)             │     │
│ │                    │  - 섹터/제품                          │     │
│ │                    │  - 메타 (접힘)                        │     │
│ │                    │  - [verified] [OOS▼] [re-tag] [skip]  │     │
│ │                    │  - 진척: "n / N"   ↶undo              │     │
│ └────────────────────┴───────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────┘
                                  ↑↓
         ┌────────────────────────┴──────────────────────────┐
         │ Streamlit app (Python, sync)                      │
         │  - session_state: skipped_ids, last_snapshot,     │
         │    total_at_start, counts{verified,oos,retag,skip}│
         │  - PDF: PyMuPDF → PNG bytes → st.image()          │
         │  - "Open in OS viewer" → server-side opener       │
         └─────────────────┬─────────────────────────────────┘
                           ↓ supabase-py (REST)
                    ┌──────┴───────┐
                    │ Supabase     │
                    │ reports 테이블│
                    └──────────────┘
```

Streamlit이 단일 Python process, 동기적으로 DB 쿼리 + UI 렌더. 결정 클릭 → DB UPDATE → `st.rerun()` → 다음 행 fetch.

PDF는 [PyMuPDF](https://pymupdf.readthedocs.io/)로 첫 N 페이지(default 3)를 PNG bytes로 렌더 후 `st.image()`. 브라우저의 `http://localhost` 페이지가 `file://` 리소스를 직접 임베드/링크할 수 없는 보안 제약을 우회.

전체 PDF가 필요할 때는 우측 패널의 `Open in OS viewer` **버튼**이 처리. `file://` 링크가 아니라 **server-side opener**가 동작 — Streamlit 콜백에서 `os.startfile(path)` (Windows) / `subprocess.run(['open', path])` (macOS) / `subprocess.run(['xdg-open', path])` (Linux) 분기 호출해 OS 기본 PDF 뷰어를 띄움. 운영자가 같은 머신에서 viewer를 돌리는 localhost 전제 위에서 안전.

## 5. Components

신규 패키지 `langgraph_tagger/review_viewer/`:

| 파일 | 책임 |
|---|---|
| `app.py` | Streamlit entry. UI 렌더, 액션 핸들러, session_state로 진척·undo 관리. |
| `config.py` | `ReviewViewerConfig` — viewer가 필요한 env만 로드 (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `STORAGE_BASE_DIR`). 태거의 `OPENAI_API_KEY`/`SUPABASE_DB_URL`이나 collector의 `TELEGRAM_*`은 요구하지 않음 — viewer 단독 실행 시 무관 env 누락으로 실패하지 않게 분리. |
| `db.py` | Supabase 쿼리 6종: `count_review_queue()`, `fetch_next_review(skipped_ids)`, `mark_verified(id, payload)`, `mark_oos(id, payload)`, `mark_pending(id)`, `restore_snapshot(id, snapshot)`. supabase-py REST 사용 (Streamlit이 sync). |
| `pdf.py` | `resolve_path(storage_base_dir, file_path)` → 로컬 절대 Path 변환 + 존재 확인. `render_pages(path, n=3, dpi=120)` → PyMuPDF로 첫 N페이지 PNG bytes 리스트 반환. `open_locally(path)` → 플랫폼 분기로 OS 기본 PDF 뷰어 띄움 (Windows `os.startfile`, macOS `open`, Linux `xdg-open`). |
| `actions.py` | row + 액션 결정 → DB payload 생성. OOS는 [write.py](/langgraph_tagger/nodes/write.py)의 OOS 분기와 동일한 의미 (분석 본체 비움 + LLM 분류·raw audit 보존). undo snapshot 직렬화. |
| `__main__.py` | `python -m langgraph_tagger.review_viewer` 실행 시 streamlit subprocess 띄움. |
| `tests/test_pdf.py` | path resolver + PyMuPDF 렌더 pure logic (1페이지 PDF fixture). |
| `tests/test_db.py` | 쿼리 payload 빌드 검증 (fake supabase client). |
| `tests/test_actions.py` | OOS payload가 writer 의미와 같은지(분석 본체 비움, LLM 분류·raw 보존) + undo snapshot round-trip 검증. |

`langgraph_tagger/` 하위에 두는 이유: 같은 `reports` 테이블·동일 v2 분류 의미를 공유하는 같은 시스템의 일부. 다만 config는 독립.

## 6. Data flow

```
[session start]
  → session.total_at_start = db.count_review_queue()
  → session.counts = {verified: 0, oos: 0, retag: 0, skip: 0}
  → session.skipped_ids = set()
  → session.last_snapshot = None

[fetch next]
  → db.fetch_next_review(skipped_ids) → row | None
  → if None: show "🎉 큐 비었음" + 세션 통계
  → else:
       page_images = pdf.render_pages(pdf.resolve_path(storage, row.file_path))
       render(page_images, [Open in OS viewer] button, review_panel(row))

[user clicks "Open in OS viewer"]
  → pdf.open_locally(resolved_path)   # 서버측 OS opener, DB 무변화

[user clicks verified]
  → snapshot = actions.capture_snapshot(row)   # allowlist 컬럼만
  → db.mark_verified(row.id, payload=actions.build_verified(row))
  → session.last_snapshot = snapshot
  → session.counts.verified += 1
  → st.rerun()

[user clicks OOS, selects reason]
  → snapshot = actions.capture_snapshot(row)
  → payload = actions.build_oos(row, reason)
      # write.py와 동일: stock_codes/company_names/sectors_*/products 비움,
      # report_type/publisher/title/analysts/stock_codes_raw/company_names_raw 보존,
      # published_at=NULL, out_of_scope_reason=<reason>, tagging_status='verified'
  → db.mark_oos(row.id, payload=payload)
  → session.last_snapshot = snapshot
  → session.counts.oos += 1
  → st.rerun()

[user clicks re-tag]
  → snapshot = actions.capture_snapshot(row)
  → db.mark_pending(row.id)
      # migration 003 reset과 동일 패턴: 분석·태깅 메타 모두 NULL/빈배열로 reset.
      # 다음 태거 배치가 새 LLM 결과로 덮어씀.
  → session.last_snapshot = snapshot
  → session.counts.retag += 1
  → st.rerun()

[user clicks skip]
  → session.skipped_ids.add(row.id)   # DB 무변화
  → session.counts.skip += 1
  → st.rerun()

[user clicks ↶ undo]
  → db.restore_snapshot(snapshot.id, snapshot)
      # snapshot의 allowlist 컬럼만 그대로 UPDATE
  → session.last_snapshot = None
  → (counts 감소는 안 함 — 마지막 카운트가 무엇이었는지 모르므로 보수적으로 유지)
  → st.rerun()
```

### 진척 카운터 정의

- `N = session.total_at_start`: **세션 시작 시 한 번** `db.count_review_queue()`로 fetch. 이후 변하지 않음. "이번 세션에서 마주칠 수 있는 최대 큐 크기" 의미.
- `n = sum(session.counts.values())`: 세션 동안 사용자가 내린 결정 수 (verified + oos + retag + skip 합).
- UI 표시: `"n / N"` + 분포 작은 글씨 `"✓N1  ✗N2  ↺N3  ↻N4"` (verified/oos/retag/skip 카운터).
- skip을 분모에서 빼지 않는 이유: skip된 행은 다음 세션엔 다시 큐로 올라오지만 이번 세션 진척에는 "처리한 1건"으로 카운트되는 게 자연.

## 7. Database semantics

기존 v2 스키마 (`migrations/003_v2_redesign.sql`)에 신규 컬럼 추가 없음. status enum 그대로:

| 결정 | DB 변화 |
|---|---|
| `verified` | `tagging_status='verified'`. 분석 필드 그대로(LLM이 추출한 값 유지) |
| `OOS<reason>` | `tagging_status='verified'`, `out_of_scope_reason=<foreign\|fund\|digital\|private\|ir_self>`, `published_at=NULL`, `stock_codes=[]`, `company_names=[]`, `sectors_major=[]`, `sectors_minor=[]`, `products=[]`. `report_type`/`publisher`/`publisher_type`/`title`/`analysts`/`stock_codes_raw`/`company_names_raw`는 LLM 출력 그대로 보존 — [write.py](/langgraph_tagger/nodes/write.py)의 자동 OOS 분기와 동일 의미. |
| `re-tag` | [migration 003](/migrations/003_v2_redesign.sql)의 reset 흐름과 동일하게 분석·태깅 메타 모두 비움: `tagging_status='pending'`, `tagging_locked_at=NULL`, `tagging_worker_id=NULL`, `tagged_at=NULL`, `tagging_notes=NULL`, `tagging_confidence=NULL`, `tagger_version=NULL`, `taxonomy_version=NULL`, `published_at=NULL`, `report_type=NULL`, `publisher=NULL`, `publisher_type=NULL`, `analysts=[]`, `title=NULL`, `stock_codes=[]`, `company_names=[]`, `stock_codes_raw=[]`, `company_names_raw=[]`, `sectors_major=[]`, `sectors_minor=[]`, `products=[]`, `out_of_scope_reason=NULL`. 다음 태거 배치가 새 LLM 결과로 덮어씀. (`tagged_at`도 NULL로 둬야 [inspect의 `last_24h` 카운터](/langgraph_tagger/supabase_io.py:106)가 stale 값을 잡지 않음.) |
| `skip` | DB 변화 없음. 같은 세션 동안 `session_state.skipped_ids`에만 표시. |
| `undo` | `session.last_snapshot`의 **allowlist 컬럼만** UPDATE로 복원. 원본 메타(`id`, `message_id`, `chat_username`, `file_path`, `file_name`, `file_size_bytes`, `file_hash_sha256`, `caption`, `downloaded_at`, `sent_at`)는 절대 건드리지 않음. |

OOS도 `tagging_status='verified'`로 마감하는 이유: 사람이 검수해서 OOS 결론을 내렸으므로 자동 OOS(status='auto' + out_of_scope_reason set)와 달리 "사람이 손 댐" 상태로 표시. inspect 카운터에선 `verified` + `oos_total` 둘 다 증가.

### Snapshot allowlist

`actions.capture_snapshot(row)`이 `session.last_snapshot`에 보관하고 `restore_snapshot`이 UPDATE하는 컬럼은 다음 22개 (액션이 만질 수 있는 모든 컬럼):

분석 본체: `published_at`, `report_type`, `publisher`, `publisher_type`, `analysts`, `title`, `stock_codes`, `company_names`, `stock_codes_raw`, `company_names_raw`, `sectors_major`, `sectors_minor`, `products`, `out_of_scope_reason`

태깅 메타: `tagging_status`, `tagging_confidence`, `tagging_notes`, `tagged_at`, `tagger_version`, `taxonomy_version`, `tagging_locked_at`, `tagging_worker_id`

직렬화는 dict (asyncpg/supabase-py 둘 다 row → dict 가능). 배열은 list, timestamp는 ISO 8601 string으로 저장. 단순 메모리 보관이라 세션 종료 시 사라짐 (undo 불가).

### 인덱스 추가

`tagging_status='review_needed' ORDER BY tagged_at ASC` 패턴의 fetch_next_review가 매 액션 후 rerun마다 호출되므로 partial index 필요. 신규 migration `004_review_queue_index.sql`:

```sql
CREATE INDEX IF NOT EXISTS ix_reports_review_needed_tagged
  ON reports(tagged_at) WHERE tagging_status='review_needed';
```

기존 002의 `(tagging_status, downloaded_at)` 인덱스는 pending(=태거 fetch) 전용이라 review 큐 fetch에는 안 맞음.

## 8. UI 위계 (우측 검수 패널)

위에서 아래로:

1. **사유 highlight** — 노란 박스. `tagging_notes`에서 review trigger 사유 표시 (`krx_unmatched_in_scope`, `type_indeterminate`, `first_page_unreadable` 등). `first_page_unreadable` 사유일 때는 빨강 박스로 강조해 운영자에게 "재태깅 후보"임을 시각적으로 알림.
2. **분류** — `report_type`, `publisher`, `publisher_type`, `tagging_confidence`.
3. **종목 매핑** — `stock_codes_raw` (LLM 원본) vs `stock_codes` (KRX 매핑). `company_names_raw` vs `company_names`. raw에 있는데 매핑이 비어있으면 review 트리거 사유 → 빨강 강조.
4. **섹터/제품** — `sectors_major`, `sectors_minor`, `products`.
5. **메시지 메타 (접힘)** — `file_name`, `sent_at`, `caption`. `<details>`로 default 접힘.
6. **액션 버튼 4개** —
   - `verified` (초록)
   - `OOS ▼` (주황, 클릭 시 reason 5개 dropdown: foreign / fund / digital / private / ir_self)
   - `re-tag` (회색-주황 계열) — `tagging_status='pending'`으로 reset, 다음 배치 사이클에 재태깅
   - `skip` (회색) — DB 무변화, 같은 세션에서만 제외
7. **진척 + undo + open PDF** — `"n / N"` 카운터 (n=세션에서 결정한 건, N=세션 시작 시 `count_review_queue` 결과) + 분포 작은 글씨 `✓ ✗ ↺ ↻` + `↶ undo last` + `Open in OS viewer` 버튼 (Streamlit 콜백 → `os.startfile`/`open`/`xdg-open` 분기).

## 9. 큐 순서

`tagging_status='review_needed'` 중 `tagged_at ASC` (오래된 것부터 FIFO). 단순·재현 가능·일관된 흐름.

세션 내 `skipped_ids` 는 `NOT IN` 절로 제외. 세션 종료(브라우저 닫음 또는 streamlit 재시작) 시 reset → 다음 세션에 다시 노출.

## 10. Error handling

| 상황 | 처리 |
|---|---|
| DB 연결 실패 | 화면 상단 `st.error`. "재시도" 버튼 |
| PDF 파일 없음 (storage 폴더에 없음) | 좌측에 경고 placeholder. 우측 패널·결정 버튼은 그대로 동작 (메타·LLM 결과만 보고 판단 가능) |
| PyMuPDF 렌더 예외 (손상 PDF) | 좌측에 에러 메시지 + `file://` 링크만. 결정 버튼 그대로 |
| UPDATE 실패 (transient) | `st.toast` 알림 + row 화면 유지 (재시도) |
| `fetch_next_review` 빈 결과 | "🎉 review 큐 비었음" 화면 + 마지막 세션 통계 (verified n, OOS m, re-tag k, skip s) |
| undo 실패 (스냅샷 없음 또는 transient) | 알림 후 무시 |

## 11. Testing

자동:
- `test_pdf.py` — `resolve_path(storage_base_dir, file_path)` pure logic (파일 없음·절대경로·상대경로 edge). `render_pages(path, n)`의 페이지 수 / PNG bytes 형식 검증 (작은 fixture PDF 한 개).
- `test_db.py` — supabase-py client mock으로 호출 payload 검증 (SELECT eq/order/limit/NOT IN, UPDATE eq/values, partial index 활용 ORDER BY).
- `test_actions.py` — `build_oos(row, reason)` 결과가 [write.py](/langgraph_tagger/nodes/write.py)의 OOS 분기 payload와 동일한 의미인지(분석 본체 비움, LLM 분류·raw 보존, `published_at=NULL`) 검증. snapshot 직렬화·역직렬화 round-trip.

수동:
- end-to-end smoke: viewer 띄우고 1건 verified → inspect로 카운터 확인.
- 1건 OOS<reason> → `out_of_scope_reason`·분석 필드 비움 확인.
- 1건 re-tag → `tagging_status='pending'` 확인 + 다음 태거 배치 실행 시 재처리되는지 확인.
- skip 후 같은 세션에 안 나오는지 확인.
- undo로 직전 1건 모든 컬럼 복원 확인.
- PDF 없는 row → 경고 표시 + 결정 가능 확인.
- 큰 PDF(10MB+)에서 첫 N페이지 렌더링 latency 점검.

자동 UI 테스트는 ROI 낮아 (1인 사용·로컬) v1엔 없음.

## 12. 의존성

신규:
- `streamlit ~= 1.40` — `requirements.txt`에 추가. Web UI 프레임워크.

기존 재사용:
- `pymupdf` — 이미 [requirements.txt](/requirements.txt)에 있음 (태거의 `nodes/extract_pdf.py`가 PDF 첫 페이지 텍스트 추출에 사용 중). viewer에서도 같은 패키지로 페이지 → PNG 렌더링.
- `supabase-py` — 이미 [storage.py](/storage.py)에서 사용.

설치·실행:
```bash
pip install -r requirements.txt           # streamlit 추가됨
python -m langgraph_tagger.review_viewer  # → streamlit run + 브라우저 자동 열림
```

## 13. Future considerations (v2+ 후보)

- LLM field 직접 수정 (stock_codes, publisher 등 inline 수정 form)
- bulk verified (체크박스 + "다 verified")
- 검수 사유별 필터 / 통계 대시보드
- 검수자 이력 (`verified_by`, `verified_at` 컬럼 추가)
- PDF 인터랙티브 뷰어 (검색·하이라이트·줌) — `streamlit-pdf-viewer` 또는 별도 PDF.js iframe 임베드
