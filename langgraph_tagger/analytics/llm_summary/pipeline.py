"""Phase 2 orchestration — 2-pass (extract → diff) + pool lifecycle.

Spec §8. 메인 함수 `analyze_stock`은 Task 11/12에서 추가.
"""
from __future__ import annotations

from langgraph_tagger.analytics.llm_summary.schemas import ExtractionResult


def normalize_target_price_dir(r: ExtractionResult) -> ExtractionResult:
    """deterministic 산수로 target_price_dir 덮어씀 (LLM 판단보다 산수 우선).

    Spec §6.3 — old/new 둘 다 int면 부호 비교, 한쪽만이면 LLM 판단 유지,
    둘 다 None이면 'N/A' 강제.
    """
    new, old = r.target_price_new, r.target_price_old
    if new is not None and old is not None:
        if new > old:    forced = '상향'
        elif new < old:  forced = '하향'
        else:            forced = '불변'
    elif new is None and old is None:
        forced = 'N/A'
    else:
        # 한쪽만 있음 → LLM 판단 유지 (신규/N/A 등)
        return r
    if r.target_price_dir == forced:
        return r
    return r.model_copy(update={'target_price_dir': forced})


import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Optional

import asyncpg
import pandas as pd
from openai import AsyncOpenAI

from langgraph_tagger.analytics.llm_summary import summary_store
from langgraph_tagger.analytics.llm_summary.config import (
    LLMSummaryConfig, load_llm_summary_config, require_openai_key,
)
from langgraph_tagger.analytics.llm_summary.llm import (
    diff_one, extract_one, TransientLLMError,
)
from langgraph_tagger.analytics.llm_summary.pdf_text import extract_all_pages

logger = logging.getLogger(__name__)


# ── wrappers (테스트 mock 용 — module 레벨 함수로 빼서 monkeypatch 쉽게) ─

extract_one_safe = extract_one
find_prev_for_diff_safe = summary_store.find_prev_for_diff


def extract_pdf_pages(path: Path, max_tokens: int):
    r = extract_all_pages(path, max_tokens)
    return r.text, r.pages_used, r.total_pages, r.input_truncated


def _call_summary_store_upsert(sb, payload):
    summary_store.upsert_summary(sb, payload)


def _call_summary_store_update_diff(sb, **kwargs):
    summary_store.update_diff(sb, **kwargs)


@asynccontextmanager
async def open_pool(db_url: str, max_size: int = 2):
    """매 호출 새 pool 열고 닫음 — Streamlit rerun event loop mismatch 회피."""
    pool = await asyncpg.create_pool(db_url, max_size=max_size)
    try:
        yield pool
    finally:
        await pool.close()


# ── 메인 함수 ────────────────────────────────────────────────────────────

async def analyze_stock(
    *,
    analytics_db,                       # langgraph_tagger.analytics.db.AnalyticsDB
    storage_base_dir: Path,
    stock_code: str,
    period_start_iso: str,
    progress_cb: Callable[..., None],
    cfg: Optional[LLMSummaryConfig] = None,
) -> list[dict[str, Any]]:
    cfg = cfg or load_llm_summary_config()
    sb = analytics_db._sb                # supabase-py REST client (analytics에서 재사용)

    # Step A — fetch + 단일종목 필터
    df = analytics_db.fetch_stock_rows(stock_code, period_start_iso)
    if df.empty:
        return []
    df = df[df['report_type'] == '단일종목'].copy()
    if df.empty:
        return []

    report_ids = df['id'].astype(int).tolist()

    # Step B — cache lookup
    cached = summary_store.fetch_summaries(sb, report_ids, cfg.summary_version)
    miss_ids = [rid for rid in report_ids if rid not in cached]

    # Step C — OpenAI client는 cache miss가 있을 때만 필요 (lazy)
    if miss_ids:
        api_key = require_openai_key(cfg)
        client = AsyncOpenAI(api_key=api_key)
    else:
        client = None

    async with open_pool(cfg.supabase_db_url, max_size=cfg.max_concurrent) as pool:
        # Pass 1 — extract cache misses
        if miss_ids:
            sem = asyncio.Semaphore(cfg.max_concurrent)
            miss_df = df[df['id'].isin(miss_ids)]
            tasks = [
                _process_extract_one(
                    row=row.to_dict(), client=client, cfg=cfg, sb=sb,
                    storage_base_dir=storage_base_dir, sem=sem,
                )
                for _, row in miss_df.iterrows()
            ]
            done = 0
            for coro in asyncio.as_completed(tasks):
                await coro
                done += 1
                progress_cb(1, done, len(tasks))

        # Pass 2 — diff for rows where prev_match_type IS NULL or 'none'
        # (added in Task 12)

    # Step D — final fetch + 카드 빌드
    final = summary_store.fetch_summaries(sb, report_ids, cfg.summary_version)
    cards: list[dict[str, Any]] = []
    for _, row in df.sort_values('published_at', ascending=False).iterrows():
        rid = int(row['id'])
        s = final.get(rid)
        if s is None:
            cards.append({'report_id': rid, 'error': 'extract', 'meta': row.to_dict()})
        else:
            cards.append({'report_id': rid, 'summary': s, 'meta': row.to_dict()})
    return cards


async def _process_extract_one(
    *,
    row: dict[str, Any],
    client: AsyncOpenAI,
    cfg: LLMSummaryConfig,
    sb,
    storage_base_dir: Path,
    sem: asyncio.Semaphore,
) -> None:
    """row-level failure 격리 — 예외 잡아 카드만 error 표시."""
    rid = int(row['id'])
    try:
        async with sem:
            file_path = storage_base_dir / row['file_path']
            text, pages_used, total_pages, truncated = extract_pdf_pages(
                file_path, cfg.max_input_tokens,
            )
            if not text:
                logger.warning("PDF empty/missing for report_id=%d", rid)
                return  # row 미생성 → final fetch에서 error 카드

            metadata = {
                'publisher': row.get('publisher'),
                'stock_codes': row.get('stock_codes', []),
                'published_at': row.get('published_at'),
                'title': row.get('title'),
            }
            extracted, tokens_in, tokens_out = await extract_one_safe(
                client=client, model=cfg.openai_model,
                metadata=metadata, pages_text=text,
                timeout_s=cfg.per_report_timeout_s,
            )
            extracted = normalize_target_price_dir(extracted)

            payload = {
                'report_id': rid,
                **extracted.model_dump(),
                'input_truncated': truncated,
                'input_pages_used': pages_used,
                'input_total_pages': total_pages,
                'summary_version': cfg.summary_version,
                'llm_model': cfg.openai_model,
                'llm_tokens_input': tokens_in,
                'llm_tokens_output': tokens_out,
                # diff fields 의무 reset (spec §10)
                'prev_report_id': None,
                'prev_match_type': None,
                'diff_narrative': None,
            }
            _call_summary_store_upsert(sb, payload)
    except TransientLLMError as e:
        logger.warning("Extract permanent fail report_id=%d: %s", rid, e)
    except Exception as e:
        logger.exception("Extract unexpected error report_id=%d: %s", rid, e)
