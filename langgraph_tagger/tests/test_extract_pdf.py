"""Tests for extract_pdf node."""
from __future__ import annotations

import asyncio
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from langgraph_tagger.nodes.extract_pdf import extract_pdf, _has_meta_signals


GOLDEN = Path(__file__).parent / "golden"


def _make_pdf(path: Path, pages_text: list[str]) -> None:
    """Synthesize a tiny PDF with given text on each page.

    Uses the built-in 'korea' CJK font so Hangul roundtrips through
    PyMuPDF's text extraction (the default Helvetica face cannot encode
    Hangul codepoints and would emit placeholder glyphs).
    """
    doc = fitz.open()
    for txt in pages_text:
        page = doc.new_page()
        if txt:
            page.insert_text((72, 72), txt, fontname="korea", fontsize=12)
    doc.save(path)
    doc.close()


@pytest.fixture(autouse=True)
def _ensure_golden(tmp_path_factory):
    """Create synthetic PDFs once per session."""
    GOLDEN.mkdir(exist_ok=True)
    if not (GOLDEN / "single_page_with_meta.pdf").exists():
        _make_pdf(
            GOLDEN / "single_page_with_meta.pdf",
            ["키움증권 리서치센터\n분석가: 홍길동\n투자의견: 매수\n목표주가: 100,000원"],
        )
    if not (GOLDEN / "page1_blank_meta_on_p2.pdf").exists():
        _make_pdf(
            GOLDEN / "page1_blank_meta_on_p2.pdf",
            ["", "키움증권 리서치센터\n분석가: 김철수\n투자의견: 매수"],
        )
    if not (GOLDEN / "no_meta_anywhere.pdf").exists():
        _make_pdf(GOLDEN / "no_meta_anywhere.pdf", ["하나", "둘", "셋", "넷", "다섯", "여섯"])


@pytest.mark.asyncio
async def test_first_page_with_meta_stops_at_p1():
    state = {"file_path": str(GOLDEN / "single_page_with_meta.pdf")}
    out = await extract_pdf(state)
    assert out["pages_used"] == [1]
    assert "키움증권" in out["pdf_text"]
    assert out["pdf_unreadable"] is False


@pytest.mark.asyncio
async def test_blank_first_page_falls_back_to_p2():
    state = {"file_path": str(GOLDEN / "page1_blank_meta_on_p2.pdf")}
    out = await extract_pdf(state)
    assert out["pages_used"] == [1, 2]
    assert "김철수" in out["pdf_text"]
    assert out["pdf_unreadable"] is False


@pytest.mark.asyncio
async def test_no_meta_walks_all_5_then_returns_text():
    state = {"file_path": str(GOLDEN / "no_meta_anywhere.pdf")}
    out = await extract_pdf(state)
    # No meta signals found → walked up to 5 pages
    assert out["pages_used"] == [1, 2, 3, 4, 5]
    # Text is non-empty (so pdf_unreadable False) but extraction is incomplete
    assert out["pdf_text"]
    assert out["pdf_unreadable"] is False


@pytest.mark.asyncio
async def test_corrupt_path_marks_unreadable():
    state = {"file_path": "/nonexistent/garbage.pdf"}
    out = await extract_pdf(state)
    assert out["pdf_unreadable"] is True
    assert out["pdf_text"] == ""
    assert out["pages_used"] == []


def test_meta_signals_detector():
    assert _has_meta_signals("분석가 김민수 투자의견 매수 목표주가") is True
    assert _has_meta_signals("키움증권 Research") is True
    assert _has_meta_signals("그냥 평범한 텍스트입니다") is False
