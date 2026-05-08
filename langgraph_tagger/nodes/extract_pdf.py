"""extract_pdf node: PyMuPDF reads page 1, falls back up to page 5 if metadata is sparse."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import fitz  # PyMuPDF

from langgraph_tagger.state import RowState

# Heuristic keywords that indicate a research PDF's first page has the metadata
# we need (analyst, publisher, investment opinion, target price, report type words).
_META_KEYWORDS = [
    "분석가", "애널리스트", "투자의견", "목표주가", "Research", "리서치",
    "증권", "FnGuide", "KIRS", "Investor Relations", "IR Material",
    "단일종목", "산업분석", "시황", "매크로", "퀀트", "전략",
]


def _has_meta_signals(text: str) -> bool:
    return any(kw in text for kw in _META_KEYWORDS)


def _resolve(file_path: str) -> Path:
    """Resolve relative paths against STORAGE_BASE_DIR (read at call time so
    pytest monkeypatch.setenv applied after module import still takes effect)."""
    p = Path(file_path)
    if p.is_absolute():
        return p
    base = Path(os.environ.get("STORAGE_BASE_DIR", "."))
    return base / p


def _sync_extract(path: Path, max_pages: int = 5) -> dict:
    if not path.exists():
        return {"pdf_text": "", "pages_used": [], "pdf_unreadable": True}
    try:
        doc = fitz.open(path)
    except Exception:
        return {"pdf_text": "", "pages_used": [], "pdf_unreadable": True}
    try:
        parts: list[str] = []
        pages_used: list[int] = []
        for i in range(min(max_pages, doc.page_count)):
            try:
                text = doc[i].get_text("text")
            except Exception:
                text = ""
            parts.append(text)
            pages_used.append(i + 1)
            # Stop early if we have meta signals on the accumulated text
            if _has_meta_signals("\n".join(parts)):
                break
        pdf_text = "\n".join(p for p in parts).strip()
    finally:
        doc.close()
    return {
        "pdf_text": pdf_text,
        "pages_used": pages_used,
        "pdf_unreadable": not pdf_text,
    }


async def extract_pdf(state: RowState) -> dict:
    """Read PDF first page; fall back up to 5 pages if metadata is sparse."""
    path = _resolve(state["file_path"])
    return await asyncio.to_thread(_sync_extract, path)
