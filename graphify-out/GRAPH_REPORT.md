# Graph Report - telegram_report  (2026-09-15)

## Corpus Check
- 141 files · ~125,024 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 2, .csv 1, .ini 1)

## Summary
- 1225 nodes · 2549 edges · 58 communities (55 shown, 2 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 114 edges (avg confidence: 0.91)
- Token cost: unavailable — host subagent tools do not expose token usage; no separate provider API was called.

## Graph Freshness
- Built from commit: `c95514c1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- 종목 요약 실행 흐름
- 요약 결과와 LLM 호출
- 태깅 실행과 KRX 색인
- 요약 저장과 이전 보고서 조회
- 태깅 배치와 오류 복구
- 수집 진행과 재시도 검증
- PDF 파일과 메타데이터 저장
- 분류 그래프와 처리 상태
- 리포트 발행량 시계열
- 검수 결정과 되돌리기
- 전체 PDF 읽기와 요약 설계
- DB 구조와 분류 기준
- 종목 즐겨찾기
- 범위 제외 신호와 추출 형식
- 구버전 경계 사례와 v2 정책
- 태깅용 PDF 페이지 추출
- KRX 종목과 산업 연결
- 파일명과 무결성 검사
- AI 메타데이터 추출
- 검수 PDF 표시
- 태깅 결과 DB 기록
- 검수 대기열 관리
- 검수 DB 모의 테스트
- 수집 명령과 종료 결과
- 분석 차트 생성
- KRX 색인 검증
- 수집 설정과 채널 식별
- 텔레그램 PDF 판별
- 수집 미리보기 테스트
- 분석 데이터 조회 검증
- 분석 범위 분기
- 대시보드 종목 검색
- 전체 태깅 경로 검증
- 검수 화면과 설정
- 발행처 사전과 v2 전환
- 분석 화면과 설정
- 수집 진입점과 백필
- 텔레그램 접속과 다운로드
- 설계 변화와 공통 설정
- 자동 확정과 검수 판단
- 운영 규칙과 채널 전환
- 대시보드 데이터 조회
- 수집 테스트 환경
- 검수 화면 실행과 설계
- 분석 테스트 표본
- 종목 상세 화면
- 산업과 유형별 분석 화면
- DB 처리 규칙 검증
- 다운로드 동시성 검증
- 수집기 역할 분리 설계
- 분석 화면 실행과 설계
- 의존성과 실행 추적
- 발행처별 분포 집계
- 산업별 종목 순위
- 합성 PDF 생성
- 수집 설정 모의 객체
- 검수 PDF 표본

## God Nodes (most connected - your core abstractions)
1. `make_llm_extraction()` - 44 edges
2. `run()` - 29 edges
3. `ExtractionResult` - 27 edges

## Surprising Connections (you probably didn't know these)
- `test_run_returns_run_result_with_all_counters()` --uses--> `RunResult`  [INFERRED]
  tests/test_collector.py → collector.py
- `retry_one()` --indirect_call--> `storage()`  [INFERRED]
  collector.py → tests/test_storage_files.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **같은 리포트 자료를 분류·검수·탐색** — docs_superpowers_specs_2026_05_09_langgraph_tagger_v2_design_architecture, docs_superpowers_specs_2026_05_12_review_viewer_design_architecture, docs_superpowers_specs_2026_05_12_analytics_dashboard_design_architecture [INFERRED 0.95]

## Communities (58 total, 2 thin omitted)

### Community 0 - "종목 요약 실행 흐름"
Cohesion: 0.05
Nodes (71): LLMSummaryConfig, load_llm_summary_config(), Lazy config — OPENAI_API_KEY는 첫 analyze 호출 시점에만 검증. 메타데이터 탭은 OPENAI 키 없이도 정상…, 첫 analyze 호출 시점에 호출. 키 없으면 RuntimeError., require_openai_key(), analyze_stock(), _call_summary_store_update_diff(), _call_summary_store_upsert() (+63 more)

### Community 1 - "요약 결과와 LLM 호출"
Cohesion: 0.07
Nodes (53): _call_with_retry(), diff_one(), extract_one(), _call(), Any, OpenAI async wrapper — extract_one + diff_one + transient 재시도 1회. structured…, 429 / timeout / connection — 재시도 가능., ExtractionResult + (input_tokens, output_tokens) 반환. (+45 more)

### Community 2 - "태깅 실행과 KRX 색인"
Cohesion: 0.05
Nodes (41): _cmd_escalate(), _cmd_inspect(), _cmd_reset_worker(), _cmd_run(), main(), _make_openai_client(), _make_worker_id(), _parse_row_ids() (+33 more)

### Community 3 - "요약 저장과 이전 보고서 조회"
Cohesion: 0.06
Nodes (32): dict, fetch_summaries(), find_prev_for_diff(), PrevRow, Any, date, DB CRUD for report_summaries. REST (supabase-py): fetch / upsert / update_diff…, 같은 종목 이전 단일종목 in-scope 리포트 중 active 버전 summary를 가진 prev. 같은 발행처 우선, 없으면 발행처 무관… (+24 more)

### Community 4 - "태깅 배치와 오류 복구"
Cohesion: 0.10
Nodes (34): _aggregate(), _empty_report(), Any, Batch orchestration: claim → fan-out via Semaphore → aggregate. Per-row…, Process a batch of pending reports. - run mode: stale_reclaim → atomic_claim →…, run_batch(), _process(), _revert() (+26 more)

### Community 5 - "수집 진행과 재시도 검증"
Cohesion: 0.16
Nodes (33): Run one collection cycle for the configured channel. Stage A: re-attempt every…, run(), RuntimeError, make_msg(), SimpleNamespace, Build a fake Telethon-Message-like object for collector tests., asyncio, Tests for collector.run — the two-phase orchestration logic. (+25 more)

### Community 6 - "PDF 파일과 메타데이터 저장"
Cohesion: 0.07
Nodes (17): process_new(), Any, Path, Return ALL message_ids already in reports for this chat. Pages through results…, Return all message_ids currently in failed_attempts for this chat (oldest…, Upsert a row into reports keyed on (chat_username, message_id). Idempotent at…, Insert a new failed_attempts row, or increment attempt_count if it exists.…, Delete the failed_attempts row for this message (no-op if absent). (+9 more)

### Community 7 - "분류 그래프와 처리 상태"
Cohesion: 0.12
Nodes (20): 대형 모델 재처리 · v1 계획, 태거 v1 구현 계획 · 5월 8일, Assemble the v2 row-graph from 8 node modules. v1 → v2 변경: - canonicalize /…, LangGraph-driven PDF metadata tagger. Spec:…, decide_status node (v2 simplified). review_needed 트리거 4종: - pdf_unreadable -…, LangGraph row-graph nodes., status_oos node: OOS rows get auto status + reason-derived confidence (v2)., status_oos() (+12 more)

### Community 8 - "리포트 발행량 시계열"
Cohesion: 0.11
Nodes (29): _ensure_effective_date(), _floor_to_unit(), DataFrame, Pandas client-side aggregation for the analytics dashboard. All functions take…, For each (bucket, report_type), return count. If include_oos is False, exclude…, For a single stock, time-bucketed count. Output columns: ['bucket', 'count'], Return a copy with an 'effective_date' column derived as: published_at if not…, Floor a datetime series to the unit: D (day), W (week), M (month). Uses period… (+21 more)

### Community 9 - "검수 결정과 되돌리기"
Cohesion: 0.11
Nodes (27): build_oos_payload(), build_pending_reset_payload(), build_verified_payload(), capture_snapshot(), Any, Payload builders for the 4 review actions, plus snapshot allowlist. Semantics…, Pick the allowlist columns out of a fetched row for later undo., Manual verified: keep LLM extraction, only flip status. (+19 more)

### Community 10 - "전체 PDF 읽기와 요약 설계"
Cohesion: 0.11
Nodes (20): LLM 요약 구현 계획 · 5월 12일, 내용 추출 후 이전 보고서 비교, 단일종목 요약·비교 설계, 요청할 때 분석하고 결과 재사용, Phase 2 — LLM 단일종목 리포트 요약 (lazy on-demand). 종목 dashboard "🤖 LLM 분석" 탭에서 click한…, _estimate_tokens(), extract_all_pages(), PDFTextResult (+12 more)

### Community 11 - "DB 구조와 분류 기준"
Cohesion: 0.12
Nodes (24): v2 보고서 분류 기준, 범위 제외·KRX 매핑 우선 규칙, failed_attempts, idx_failed_chat, idx_reports_chat_msg, idx_reports_sent_at, idx_reports_untagged, reports (+16 more)

### Community 12 - "종목 즐겨찾기"
Cohesion: 0.18
Nodes (24): add(), load(), Path, Stock favorites persisted in a JSON file. Atomic writes via tempfile +…, Read favorites list. Returns [] if file missing. On JSON corruption or…, Atomic JSON write — tempfile in same dir, then os.replace., Public: return list of stock codes from the favorites file., Idempotent — duplicate adds are no-ops; insertion order preserved. (+16 more)

### Community 13 - "범위 제외 신호와 추출 형식"
Cohesion: 0.14
Nodes (19): LLMExtraction, OOSSignals, BaseModel, Pydantic schema for the OpenAI structured-output call (v2). v2 변경 (rev-7): -…, LLM-observed primary-coverage signals., All fields the LLM populates in one structured-output call (v2)., mark_oos_reason(), mark_oos_reason node: sets is_oos + oos_reason from LLM signals + IR자료 (v2).… (+11 more)

### Community 14 - "구버전 경계 사례와 v2 정책"
Cohesion: 0.11
Nodes (18): 해외 비교기업 표본, 국내 종목·해외 언급, 미상장 IPO 표본, 공모예정 기업, 기업 자체 IR 표본, 자체 IR 자료, 비상장 기업 표본, 비상장·장외 기업 (+10 more)

### Community 15 - "태깅용 PDF 페이지 추출"
Cohesion: 0.14
Nodes (23): extract_pdf(), _has_meta_signals(), Path, extract_pdf node: PyMuPDF reads page 1, falls back up to page 3 if metadata is…, Resolve relative paths against STORAGE_BASE_DIR (read at call time so pytest…, Read PDF first page; fall back up to 3 pages if metadata is sparse., _resolve(), _sync_extract() (+15 more)

### Community 16 - "KRX 종목과 산업 연결"
Cohesion: 0.17
Nodes (22): _finalize(), _parse_iso_date(), date, resolve_krx node (v2): canonicalize+validate+enrich 통합. report_type별 KRX lookup…, entries → final 컬럼 + published_at fallback., resolve_krx(), Test resolve_krx — v2 type-aware KRX lookup., 섹터에 stock_code/company_name이 없거나 모두 미매칭이어도 정상 (decide_status가 auto로 처리). (+14 more)

### Community 17 - "파일명과 무결성 검사"
Cohesion: 0.15
Nodes (21): _process_one_message(), Any, Two-phase orchestration: retry failures (A), then fetch new (B). This module…, Download a message's PDF and write metadata to storage. Idempotent enough that…, compute_sha256(), Storage layer: Supabase metadata + local PDF filesystem. This module also…, Convert an arbitrary string into a safe filename. Rules (in order): 1. Replace…, Compute SHA-256 of a file by streaming in chunks. Returns lowercase hex digest.… (+13 more)

### Community 18 - "AI 메타데이터 추출"
Cohesion: 0.14
Nodes (21): Exception, llm_extract(), OpenAITransientError, AsyncOpenAI, llm_extract node: single OpenAI structured-output call., Wraps 429/5xx/timeout from OpenAI; orchestrator reverts row to pending., SYSTEM_PROMPT for the llm_extract node (v2). v2 변경 (rev-7): - 6종 report_types -…, Build the user message for llm_extract. (+13 more)

### Community 19 - "검수 PDF 표시"
Cohesion: 0.14
Nodes (22): open_locally(), Path, PDF I/O for the review viewer. - resolve_path: turn (storage_base_dir,…, Combine storage base + relative file_path. Absolute file_path wins. Does NOT…, Render the first n pages of pdf_path to PNG bytes via PyMuPDF. Caps at the…, Open pdf_path in the OS default PDF viewer. Server-side dispatch avoids the…, render_pages(), resolve_path() (+14 more)

### Community 20 - "태깅 결과 DB 기록"
Cohesion: 0.17
Nodes (19): _build_payload(), write node (v2): build UPDATE payload and persist via SupabaseSQL. v2 변경…, Return UPDATE_SQL bind-arg tuple matching $1..$19 in supabase_io.UPDATE_SQL., write(), Supabase Postgres direct connection (asyncpg) for atomic claim / stale lock /…, _in_scope_state(), asyncio, v2 in-scope state — uses *_final keys from resolve_krx, no topics/canon at… (+11 more)

### Community 21 - "검수 대기열 관리"
Cohesion: 0.15
Nodes (14): Any, supabase-py REST wrapper for review viewer queries. Sync (Streamlit-friendly),…, Thin facade over a supabase-py client. The client argument is intentionally…, Apply only allowlisted columns from snapshot, ignoring any leakage., ReviewDB, mark_pending must use the reset payload from…, test_count_review_queue_uses_status_filter(), test_fetch_next_review_excludes_skipped() (+6 more)

### Community 22 - "검수 DB 모의 테스트"
Cohesion: 0.10
Nodes (9): fake_sb(), FakeQueryBuilder, FakeSupabase, fixture, Path, Shared fixtures for review viewer tests., Path to a tiny 1-page PDF used by pdf.py tests. Generated once and committed to…, Tracks calls and lets a test assert on the chain. (+1 more)

### Community 23 - "수집 명령과 종료 결과"
Cohesion: 0.18
Nodes (20): Counters returned by `run()`. Used by main.py to set the exit code., RunResult, compute_exit_code(), parse_args(), Map a RunResult to an exit code per spec §5.5., Namespace, Tests for main.parse_args and main.compute_exit_code (pure functions only). The…, argparse rejects --cutoff-days + --backfill-days combination. (+12 more)

### Community 24 - "분석 차트 생성"
Cohesion: 0.19
Nodes (19): Figure, monthly_bar(), publisher_pie(), DataFrame, ranking_bar(), Plotly figure builders for the analytics dashboard. All functions take a…, One line per sector. Columns: bucket, sector, count., One line per report_type. Columns: bucket, report_type, count. (+11 more)

### Community 25 - "KRX 색인 검증"
Cohesion: 0.10
Nodes (4): Tests for KRXIndex (loading, validation, lookup, name lookup, products)., TestLoad, TestSplitProducts, TestValidate

### Community 26 - "수집 설정과 채널 식별"
Cohesion: 0.16
Nodes (16): retry_one(), Config, load_config(), Identifier for telethon fetch calls. Returns the numeric channel id if set…, Load env vars from .env (if present) and process environment. Raises SystemExit…, CHANNEL_ID 환경변수 없으면 telegram_channel_id는 None., CHANNEL_ID 환경변수가 숫자 문자열이면 int로 캐스팅., test_channel_ref_falls_back_to_username_when_id_unset() (+8 more)

### Community 27 - "텔레그램 PDF 판별"
Cohesion: 0.21
Nodes (19): _get_original_filename(), has_pdf(), Any, Return True if the message has a PDF attachment. Strategy: 1. If no document at…, Extract the Telegram-original file_name attribute, or None., _msg_text_only(), _msg_with_doc(), SimpleNamespace (+11 more)

### Community 28 - "수집 미리보기 테스트"
Cohesion: 0.12
Nodes (10): FakeStorage, Path, In-memory fake matching the Storage interface used by collector., _make_dry_run_config(), asyncio, _dry_run with backfill_days uses iter_since_date and skips IDs already in…, When telegram_channel_id is set on config, dry-run fetches via int id., Build a config-shaped object with channel_ref() for _dry_run tests. (+2 more)

### Community 29 - "분석 데이터 조회 검증"
Cohesion: 0.19
Nodes (16): AnalyticsDB, Any, Read-only DB wrapper for analytics dashboard., _make_supabase_with_pages(), Regression: empty fetches must still expose EXPECTED_COLS so the downstream…, OOS-on: server-side filter is tagging_status only. Period filter is client-side…, Build a supabase-py client mock whose .range().execute() returns pages[i] for…, OOS-on: row with published_at=NULL and sent_at < period_start must be filtered… (+8 more)

### Community 30 - "분석 범위 분기"
Cohesion: 0.22
Nodes (17): oos_gate(), oos_gate: 3-way LangGraph routing function (v2). v2 변경 (rev-7): - IR자료 분기 추가 →…, _ext(), Tests for oos_gate (3-way routing function — does NOT mutate state)., v2: IPO는 enum에서 제거됨 (단일종목으로 통합). private_company_likely 분기에 IPO 예외 없음., Defense-in-depth: snapshot before/after to confirm no mutation., test_digital_routes_to_mark_oos(), test_foreign_routes_to_mark_oos() (+9 more)

### Community 31 - "대시보드 종목 검색"
Cohesion: 0.22
Nodes (16): load_krx(), lookup(), DataFrame, Path, KRX master CSV loader + search/lookup helpers. Reads the project's…, Load KRX master CSV into a DataFrame. Normalizes Korean source columns to…, Filter df by code-prefix or name-substring (case-insensitive). Empty query…, Return (code, name, sector_major, sector_minor) for the row matching code, or… (+8 more)

### Community 32 - "전체 태깅 경로 검증"
Cohesion: 0.20
Nodes (14): datetime, build_graph(), asyncio, End-to-end graph smoke tests with mock OpenAI + mock supabase., In-scope 경로의 진짜 end-to-end. tiny PDF 합성으로 extract_pdf 통과시키고 resolve_krx →…, Missing file → status_unreadable → review_needed/low. Splits the smoke coverage…, test_in_scope_single_stock_flows_end_to_end(), test_oos_foreign_short_circuits_to_status_oos() (+6 more)

### Community 33 - "검수 화면과 설정"
Cohesion: 0.20
Nodes (12): _bootstrap(), cache_resource, Streamlit entry for the review viewer. Run via: python -m…, load_review_viewer_config(), Standalone config for the review viewer. Intentionally separate from…, ReviewViewerConfig, Viewer must run without OPENAI_API_KEY / TELEGRAM_* — those belong to tagger /…, test_does_not_require_openai_or_telegram_envs() (+4 more)

### Community 34 - "발행처 사전과 v2 전환"
Cohesion: 0.15
Nodes (8): KRX 매핑으로 태깅 단순화 · v2 계획, 태거 v2 구현 계획 · 5월 9일, Test taxonomy() — only public API in v2., Vocabulary lookup (v2: taxonomy only — publisher canon은 LLM이 직접 출력).…, Returns the loaded taxonomy.yaml content (used by prompts and tests)., _taxonomy(), 발행처 표준 이름·별칭 사전, 증권사·정보사·IR대행·기타

### Community 35 - "분석 화면과 설정"
Cohesion: 0.22
Nodes (12): _bootstrap(), cache_resource, Streamlit entry for the analytics dashboard. Run via: python -m…, AnalyticsConfig, load_analytics_config(), Standalone config for the analytics dashboard. Intentionally separate from…, Analytics must run without OPENAI_API_KEY / TELEGRAM_* / SUPABASE_DB_URL., test_does_not_require_openai_or_telegram() (+4 more)

### Community 36 - "수집 진입점과 백필"
Cohesion: 0.20
Nodes (12): 병렬·백필 구현 계획 · 5월 6일, 재시도·신규 수집의 공통 동시성 제한, 병렬 다운로드·백필 설계, 대기 시간 중첩으로 수집 가속, _amain(), _dry_run(), main(), CLI entry point. Exit codes (spec §5.5): 0 = complete success (no failures,… (+4 more)

### Community 37 - "텔레그램 접속과 다운로드"
Cohesion: 0.16
Nodes (8): Message, Path, Thin async wrapper around Telethon for our specific use case. Use as an async…, Yield messages with id > min_id, oldest first., First-run path: yield all messages since `days_ago` days ago, oldest first., Fetch a single message by id. Returns None if deleted/not found., Download the PDF attached to `msg` and return its bytes. We download into…, TelegramClient

### Community 38 - "설계 변화와 공통 설정"
Cohesion: 0.21
Nodes (9): Load environment variables into a typed, frozen Config object. Fails fast on…, 태거 v1 설계 · 과거 구조, AI 추출과 코드 판단의 역할 분리, 태거 v2 설계, KRX를 종목·산업·제품 기준으로 사용, 종목·매크로 분석 화면 설계, 명시 종목 중심의 분석 범위, 사람의 검수 화면 설계 (+1 more)

### Community 39 - "자동 확정과 검수 판단"
Cohesion: 0.32
Nodes (13): decide_status(), make_llm_extraction(), Factory for tests — v2 sane defaults overridable per test., Test decide_status — v2 simplified policy., test_llm_refusal_review_low(), test_name_code_mismatch_downgrades_to_medium(), test_pdf_unreadable_review_low(), test_type_indeterminate_review_low() (+5 more)

### Community 40 - "운영 규칙과 채널 전환"
Cohesion: 0.21
Nodes (6): LLM 동시 실행 2개, 운영 원칙, 채널 접속 ID와 저장 이름 분리, 채널 비공개 전환 대응 계획, 과거 자료 수집 명령, 텔레그램 PDF 수집기

### Community 41 - "대시보드 데이터 조회"
Cohesion: 0.23
Nodes (9): _paged_fetch(), DataFrame, supabase-py REST wrapper with paginated fetch. Fetcher pattern: - in-scope…, All in-scope rows where stock_codes contains the given code. Uses supabase-py's…, Loop .range(offset, offset+PAGE-1).execute() until a short page., Build a DataFrame that always has the expected columns, even for empty results…, In-scope rows only. tagging_status IN ('auto','verified') AND…, For Report type volume sub-tab. - include_oos=False: in-scope only, server-side… (+1 more)

### Community 42 - "수집 테스트 환경"
Cohesion: 0.20
Nodes (6): fake_client(), fake_storage(), FakeTelegramClient, fixture, Shared pytest fixtures for collector tests., In-memory fake matching the TelegramClient interface used by collector.

### Community 43 - "검수 화면 실행과 설계"
Cohesion: 0.20
Nodes (5): 확정·범위 밖·재태깅·보류, 검수 화면 구현 계획 · 5월 12일, Review viewer: Streamlit web app for manually verifying review_needed rows., Entry point: `python -m langgraph_tagger.review_viewer`. Spawns `streamlit run`…, ix_reports_review_needed_tagged

### Community 44 - "분석 테스트 표본"
Cohesion: 0.24
Nodes (10): inscope_df(), krx_csv(), DataFrame, fixture, Path, Shared fixtures for analytics tests., Minimal KRX master CSV for unit tests. Headers match the real…, Small DataFrame representing in-scope rows for aggregate tests. Every row has… (+2 more)

### Community 45 - "종목 상세 화면"
Cohesion: 0.29
Nodes (10): _fetch_stock_cached(), _open_locally(), _period_start_iso(), cache_data, Path, Stock dashboard page — header + timeseries + publisher dist + report list., Stock dashboard — 메타데이터 탭 (기존) + 🤖 LLM 분석 탭 (Phase 2)., 기존 메타데이터 view — 헤더 + 시계열 + publisher pie + 발행 리스트. (+2 more)

### Community 46 - "산업과 유형별 분석 화면"
Cohesion: 0.36
Nodes (9): _fetch_inscope_cached(), _fetch_inscope_or_oos_cached(), _period_start_iso(), cache_data, Macro page — two sub-tabs: Sector coverage + Report type volume., Render macro page with two sub-tabs., render(), _render_report_type_volume() (+1 more)

### Community 48 - "다운로드 동시성 검증"
Cohesion: 0.22
Nodes (8): FakeTelegramClient that records max concurrent download_pdf_bytes calls. Used…, TrackingFakeClient, _make_cfg(), Build a config-shaped object with channel_ref() that mirrors the cfg fixture., With N=3 and 10 messages, max concurrent downloads should be at most 3 AND at…, With N=1 (Semaphore(1)), only one download at a time., test_concurrency_n1_is_serial(), test_concurrency_respects_semaphore_limit()

### Community 49 - "수집기 역할 분리 설계"
Cohesion: 0.31
Nodes (5): DB 기반 수집 상태 · 초기 계획, 수집기 구현 계획 · 5월 5일, 수집기 모듈 설계 · 초기, 접속·저장·진행 관리의 역할 분리, Telethon wrapper + pure PDF predicates. Only the pure functions (`has_pdf`,…

### Community 50 - "분석 화면 실행과 설계"
Cohesion: 0.25
Nodes (4): 페이지별 조회 후 집계 · 화면 계획, 분석 화면 구현 계획 · 5월 12일, Analytics dashboard: Streamlit web app for sector coverage + stock dashboards., Entry point: `python -m langgraph_tagger.analytics`. Spawns `streamlit run` on…

### Community 51 - "의존성과 실행 추적"
Cohesion: 0.43
Nodes (5): Telethon·LangGraph·OpenAI·Streamlit, 실행용 의존성 목록, 개발용 의존성 목록, pytest·비동기 테스트 도구, LangSmith 실행 추적

### Community 52 - "발행처별 분포 집계"
Cohesion: 0.33
Nodes (6): publisher_dist(), Top K publishers by row count; rest grouped into '기타'. Output columns:…, For 005930 rows: 메리츠(1), 키움(1), NH(1)., If top_k < unique publishers, the rest go to '기타'., test_publisher_dist_counts_by_publisher(), test_publisher_dist_top_k_groups_into_other()

### Community 53 - "산업별 종목 순위"
Cohesion: 0.33
Nodes (6): For rows matching the sector filter, unnest stock_codes and count desc. Output…, sector_ranking(), When 반도체 selected, count stock_codes occurrences across matching rows. Rows…, No filter: count over all rows with non-empty stock_codes., test_sector_ranking_counts_unnested_stock_codes(), test_sector_ranking_empty_items_uses_full_scope()

### Community 54 - "합성 PDF 생성"
Cohesion: 0.47
Nodes (5): main(), Path, Synthesize the committed golden boundary-case PDFs (spec §6.5 rule 4 + §6.6).…, Create a one-page PDF with the given text using the built-in 'korea' font. The…, synth()

### Community 55 - "수집 설정 모의 객체"
Cohesion: 0.50
Nodes (3): cfg(), fixture, Minimal config-shaped object. channel_ref() falls back to username when…

## Knowledge Gaps
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ReviewDB` connect `검수 대기열 관리` to `검수 화면과 설정`, `검수 결정과 되돌리기`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._

## Extraction audit and scope

- Source code, design documents, and synthetic test fixtures only. Downloaded reports, sessions, local agent worktrees, and credentials were excluded.
- Historical plans are documentation, not proof of current runtime behavior. AST links and explicit documentation references are EXTRACTED; semantic inferences are labeled INFERRED.
- Health warning: 233 unresolved import edges; 1 self-loop edges; 739 relations collapsed onto shared endpoint pairs. See graph-health.json and extraction-audit.json.
- This is the default undirected relationship graph. Connection direction is not execution order.
