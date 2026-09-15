"""Env loader for tagger."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda *a, **k: False


@dataclass(frozen=True)
class TaggerConfig:
    openai_api_key: str
    model_default: str
    model_escalation: str
    max_concurrent_llm: int
    batch_size_default: int
    krx_csv_path: Path
    supabase_db_url: str
    # Concurrency / lock safety knobs (spec §9.5)
    lock_ttl_minutes: int
    per_row_deadline_s: float
    # Heartbeat: reserved for v2. Loaded from env for forward-compat but
    # orchestrator does NOT consume these in v1 — see spec §9.2 note.
    heartbeat_enabled: bool
    heartbeat_interval_s: int


def load_config() -> TaggerConfig:
    load_dotenv()
    def _req(name: str) -> str:
        v = os.environ.get(name)
        if not v:
            raise RuntimeError(f"{name} is required")
        return v
    return TaggerConfig(
        openai_api_key=_req("OPENAI_API_KEY"),
        model_default=os.environ.get("OPENAI_MODEL_DEFAULT", "gpt-5.6-luna"),
        model_escalation=os.environ.get("OPENAI_MODEL_ESCALATION", "gpt-5.4"),
        max_concurrent_llm=int(os.environ.get("MAX_CONCURRENT_LLM", "10")),
        batch_size_default=int(os.environ.get("TAGGER_BATCH_SIZE_DEFAULT", "10")),
        krx_csv_path=Path(os.environ.get("KRX_CSV_PATH", "docs/stock_data/KRX_stocks_data.csv")),
        supabase_db_url=_req("SUPABASE_DB_URL"),
        lock_ttl_minutes=int(os.environ.get("LOCK_TTL_MINUTES", "30")),
        per_row_deadline_s=float(os.environ.get("PER_ROW_DEADLINE_S", "90")),
        heartbeat_enabled=os.environ.get("HEARTBEAT_ENABLED", "false").lower() == "true",
        heartbeat_interval_s=int(os.environ.get("HEARTBEAT_INTERVAL_S", "30")),
    )
