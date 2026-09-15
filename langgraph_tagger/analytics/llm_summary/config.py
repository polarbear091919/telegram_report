"""Lazy config — OPENAI_API_KEY는 첫 analyze 호출 시점에만 검증.

메타데이터 탭은 OPENAI 키 없이도 정상 동작해야 하므로 load 시 검증 X.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class LLMSummaryConfig:
    openai_model: str
    max_concurrent: int
    per_report_timeout_s: int
    max_input_tokens: int
    summary_version: str
    supabase_db_url: str
    openai_api_key: Optional[str]  # lazy: load 시점엔 None일 수 있음


def load_llm_summary_config() -> LLMSummaryConfig:
    load_dotenv()

    db_url = os.getenv('SUPABASE_DB_URL')
    if not db_url:
        raise SystemExit("Missing required env var: SUPABASE_DB_URL")

    return LLMSummaryConfig(
        openai_model=os.getenv('OPENAI_MODEL_PHASE2', 'gpt-5.6-luna'),
        max_concurrent=int(os.getenv('PHASE2_MAX_CONCURRENT', '2')),
        per_report_timeout_s=int(os.getenv('PHASE2_PER_REPORT_TIMEOUT_S', '90')),
        max_input_tokens=int(os.getenv('PHASE2_MAX_INPUT_TOKENS', '30000')),
        summary_version=os.getenv('PHASE2_SUMMARY_VERSION', 'llm-summary@1.0'),
        supabase_db_url=db_url,
        openai_api_key=os.getenv('OPENAI_API_KEY'),  # None OK at load time
    )


def require_openai_key(cfg: LLMSummaryConfig) -> str:
    """첫 analyze 호출 시점에 호출. 키 없으면 RuntimeError."""
    key = cfg.openai_api_key or os.getenv('OPENAI_API_KEY')
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY가 설정되지 않았습니다. .env에 추가 후 분석 다시 시도하세요."
        )
    return key
