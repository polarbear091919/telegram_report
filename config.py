"""Load environment variables into a typed, frozen Config object.

Fails fast on missing required keys.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_channel: str
    telegram_session_path: Path
    supabase_url: str
    supabase_service_key: str
    storage_base_dir: Path
    initial_cutoff_days: int
    max_concurrent_downloads: int
    log_level: str


def load_config() -> Config:
    """Load env vars from .env (if present) and process environment.

    Raises SystemExit (with a descriptive message) if any required key is missing.
    """
    load_dotenv()

    def required(key: str) -> str:
        v = os.getenv(key)
        if not v:
            raise SystemExit(f"Missing required env var: {key}")
        return v

    session_name = os.getenv('TELEGRAM_SESSION_NAME', 'samstudy')

    return Config(
        telegram_api_id=int(required('TELEGRAM_API_ID')),
        telegram_api_hash=required('TELEGRAM_API_HASH'),
        telegram_channel=required('TELEGRAM_CHANNEL'),
        telegram_session_path=Path('sessions') / session_name,
        supabase_url=required('SUPABASE_URL'),
        supabase_service_key=required('SUPABASE_SERVICE_KEY'),
        storage_base_dir=Path(os.getenv('STORAGE_BASE_DIR', './reports')),
        initial_cutoff_days=int(os.getenv('INITIAL_CUTOFF_DAYS', '30')),
        max_concurrent_downloads=int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '4')),
        log_level=os.getenv('LOG_LEVEL', 'INFO'),
    )
