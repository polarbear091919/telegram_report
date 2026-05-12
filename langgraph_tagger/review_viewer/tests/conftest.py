"""Shared fixtures for review viewer tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_pdf_path() -> Path:
    """Path to a tiny 1-page PDF used by pdf.py tests.

    Generated once and committed to fixtures/. If missing, run
    tools/generate_fixture_pdf.py (see Step 4.2).
    """
    p = Path(__file__).parent / 'fixtures' / 'sample_1page.pdf'
    if not p.exists():
        # Auto-generate so first-time runners don't get stuck
        import pymupdf
        p.parent.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 80), "Sample fixture PDF", fontsize=20)
        page.insert_text((50, 120), "Used by review_viewer tests.", fontsize=12)
        doc.save(str(p))
        doc.close()
    return p
