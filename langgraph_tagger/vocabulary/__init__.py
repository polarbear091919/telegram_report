"""Vocabulary lookup (v2: taxonomy only — publisher canon은 LLM이 직접 출력).

topics.yaml은 삭제됨. publishers.yaml은 prompts.py가 본문 그대로 LLM에게 주입.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_VOCAB_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def _taxonomy() -> dict:
    return yaml.safe_load((_VOCAB_DIR / "taxonomy.yaml").read_text(encoding="utf-8"))


def taxonomy() -> dict:
    """Returns the loaded taxonomy.yaml content (used by prompts and tests)."""
    return _taxonomy()


__all__ = ["taxonomy"]
