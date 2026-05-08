# Parity fixtures

This directory holds the hand-curated regression cases that verify the
LangGraph row-graph reproduces the friendly-mclaren skill's classification
output. Each `case` in `fixtures.json` records a `(input PDF + LLM mock)
→ (expected DB UPDATE payload)` triple. `test_parity.py` runs the entire
row graph headlessly per fixture and asserts the payload columns match.

## Fixture provenance

The `claude/friendly-mclaren-815e01` branch did **not** ship with concrete
`result.json` files, so each fixture's `expected` block was derived by
applying the documented spec rules and KRX index entries. Inputs (`pdf_text`,
`caption`, `sent_at`) and `llm_mock` payloads are **hand-curated** to
exercise a single representative path per case.

The 12 cases enumerated below mirror the 14 in-scope `report_type`s plus
the 4 OOS reasons plus three boundary scenarios (`unknown_publisher`,
`unknown_product`, peer-mention). Reference docs:

- `docs/superpowers/specs/2026-05-07-report-metadata-tagging-routine-design.md`
  for §6.5 (OOS gating + rule-4 exceptions) and §6.6 (decide_status policy).
- `langgraph_tagger/vocabulary/taxonomy.yaml` for the precedence rules
  comments and report_type / publisher_type / oos_reason enums.
- `langgraph_tagger/vocabulary/publishers.yaml` for canonical publisher
  names and aliases.
- `langgraph_tagger/vocabulary/topics.yaml` for canonical topics + alias
  rollups.
- `docs/stock_data/KRX_stocks_data.csv` for KRX validation / enrichment
  source rows. Stock codes referenced (`033780` KT&G, `005930` 삼성전자,
  `107600` 새빗켐) are all present in the snapshot used by tests.

## Cases

| Case                          | Path through graph                                    | Status / Confidence  |
|-------------------------------|-------------------------------------------------------|----------------------|
| `single_stock`                | KT&G 단일종목, KRX matched, vocabulary matched        | auto/high            |
| `industry`                    | 반도체 산업                                           | auto/high            |
| `daily_market`                | 시황·데일리 (no stock/sector — topics carry signal)   | auto/high            |
| `ipo_listed`                  | KRX-matched IPO update → 단일종목 (rule 3)            | auto/high            |
| `ipo_unlisted`                | KRX-unmatched + IPO context → in-scope IPO (rule 4)   | auto/high            |
| `ir_company_self`             | publisher_raw="해당기업" → publisher_type="company"   | auto/high            |
| `domestic_with_foreign_peer`  | 005930 + foreign_primary_coverage=false (peer only)   | auto/high            |
| `foreign_primary`             | 해외 단일종목 → OOS foreign                           | auto/high            |
| `etf_lineup`                  | ETF 라인업 → OOS fund                                 | auto/high            |
| `unknown_publisher_in_scope`  | vocab-외 broker → review_needed/low                   | review_needed/low    |
| `unknown_product_in_scope`    | KRX-외 product (005930 isolates the product policy)   | review_needed/low    |
| `digital_btc`                 | BTC 분석 → OOS digital                                | auto/high            |

## Field semantics

`expected` keys ending in `_contains` assert membership rather than
equality. `enrich` auto-merges KRX rows (company_names / sectors_major /
sectors_minor / products) for single-stock-style cases, so the final
list typically has more entries than what the LLM returned.

The PDF body in each fixture is synthesized by the test driver via PyMuPDF
with `fontname="korea"` so Hangul roundtrips through `extract_pdf` cleanly.
