from pathlib import Path

import fitz  # PyMuPDF
import pytest

from langgraph_tagger.analytics.llm_summary.pdf_text import (
    PDFTextResult, extract_all_pages,
)


@pytest.fixture
def make_pdf(tmp_path):
    """Helper to write a PDF with N pages of given text.

    PyMuPDF's default font (Helvetica) cannot embed CJK glyphs via insert_text,
    so we use ASCII bodies for round-trippability. The pipeline reads real
    Korean PDFs (which embed their own CJK fonts) — that path is exercised by
    integration tests, not these unit fixtures.
    """
    def _make(num_pages: int, text_per_page: str = 'body text') -> Path:
        path = tmp_path / f'test_{num_pages}p.pdf'
        doc = fitz.open()
        for _ in range(num_pages):
            page = doc.new_page()
            page.insert_text((72, 72), text_per_page)
        doc.save(str(path))
        doc.close()
        return path
    return _make


def test_extract_simple_no_truncate(make_pdf):
    pdf = make_pdf(3, 'simple body')
    r = extract_all_pages(pdf, max_tokens=100000)
    assert isinstance(r, PDFTextResult)
    assert r.total_pages == 3
    assert r.pages_used == 3
    assert r.input_truncated is False
    assert '--- Page 1 ---' in r.text
    assert '--- Page 2 ---' in r.text
    assert '--- Page 3 ---' in r.text
    assert 'simple body' in r.text


def test_extract_truncate_when_cap_low(make_pdf):
    # 페이지마다 ~50 chars body + ~16 chars header ≈ ~22 tokens/page.
    # max_tokens=50 → page 1, 2는 들어가고 page 3부터 truncate.
    body = 'x' * 50  # 50 chars body → ~22 tokens per chunk including header
    pdf = make_pdf(10, body)
    r = extract_all_pages(pdf, max_tokens=50)
    assert r.input_truncated is True
    assert r.pages_used < r.total_pages
    assert r.pages_used > 0  # 최소 1페이지는 들어감
    assert r.total_pages == 10
    assert r.estimated_input_tokens > 0


def test_extract_missing_file_returns_empty(tmp_path):
    fake = tmp_path / 'nope.pdf'
    r = extract_all_pages(fake, max_tokens=10000)
    assert r.text == ''
    assert r.pages_used == 0
    assert r.total_pages == 0
    assert r.input_truncated is False


def test_extract_total_pages_correct(make_pdf):
    pdf = make_pdf(7)
    r = extract_all_pages(pdf, max_tokens=100000)
    assert r.total_pages == 7
    assert r.pages_used == 7
