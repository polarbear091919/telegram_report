"""Vocabulary lookup (publishers, topics, taxonomy).

Loads YAML once per process; exposes lookup_publisher and map_topics.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import yaml

_VOCAB_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def _publishers_table() -> dict:
    """Returns flat alias→(canonical, publisher_type) dict + canonical→type dict."""
    raw = yaml.safe_load((_VOCAB_DIR / "publishers.yaml").read_text(encoding="utf-8"))
    alias_map: dict[str, tuple[str, str]] = {}
    for ptype, entries in raw.items():
        for entry in entries:
            canon = entry["canonical"]
            # publisher_type_override (e.g., 해당기업 in 'other:' block → 'company')
            effective_type = entry.get("publisher_type_override", ptype)
            # canonical itself is also a valid alias
            alias_map[_normalize(canon)] = (canon, effective_type)
            for alias in entry.get("aliases", []) or []:
                alias_map[_normalize(alias)] = (canon, effective_type)
    return alias_map


@lru_cache(maxsize=1)
def _topics_table() -> dict[str, str]:
    """Returns alias→canonical dict (canonical itself included as alias)."""
    raw = yaml.safe_load((_VOCAB_DIR / "topics.yaml").read_text(encoding="utf-8"))
    table: dict[str, str] = {}
    for entry in raw:
        canon = entry["canonical"]
        table[_normalize(canon)] = canon
        for alias in entry.get("aliases", []) or []:
            table[_normalize(alias)] = canon
    return table


@lru_cache(maxsize=1)
def _taxonomy() -> dict:
    return yaml.safe_load((_VOCAB_DIR / "taxonomy.yaml").read_text(encoding="utf-8"))


def _normalize(s: str) -> str:
    """Strip + lowercase + remove all whitespace for fuzzy alias key."""
    return "".join(s.split()).lower()


def lookup_publisher(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """raw publisher string → (canonical, publisher_type) or (None, None) on miss."""
    if not raw:
        return None, None
    return _publishers_table().get(_normalize(raw), (None, None))


def map_topics(raw_topics: list[str]) -> Tuple[list[str], list[str]]:
    """raw topics → (canonical_dedup_in_order, unmapped_in_order)."""
    table = _topics_table()
    canonical: list[str] = []
    unmapped: list[str] = []
    seen: set[str] = set()
    for t in raw_topics:
        c = table.get(_normalize(t))
        if c is None:
            unmapped.append(t)
        elif c not in seen:
            canonical.append(c)
            seen.add(c)
    return canonical, unmapped


def taxonomy() -> dict:
    """Returns the loaded taxonomy.yaml content (for prompts and CHECK constraints)."""
    return _taxonomy()


__all__ = ["lookup_publisher", "map_topics", "taxonomy"]
