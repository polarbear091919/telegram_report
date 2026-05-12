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


class FakeQueryBuilder:
    """Tracks calls and lets a test assert on the chain."""

    def __init__(self, sink: list[dict]):
        self._sink = sink
        self._spec: dict = {'eqs': []}

    def select(self, cols, count=None):
        self._spec['select'] = cols
        if count is not None:
            self._spec['count_mode'] = count
        return self

    def eq(self, col, val):
        self._spec['eqs'].append((col, val))
        return self

    def order(self, col, desc=False):
        self._spec['order'] = (col, desc)
        return self

    def limit(self, n):
        self._spec['limit'] = n
        return self

    def not_(self):
        self._spec.setdefault('not_', []).append(True)
        return self

    def in_(self, col, values):
        self._spec.setdefault('not_in', []).append((col, list(values)))
        return self

    def update(self, payload):
        self._spec['update'] = dict(payload)
        return self

    def execute(self):
        self._sink.append(self._spec)
        return type('R', (), {
            'data': self._spec.get('_canned_data', []),
            'count': self._spec.get('_canned_count', None),
        })()


class FakeSupabase:
    def __init__(self):
        self.calls: list[dict] = []
        self._canned: dict[str, list | int] = {}

    def table(self, name):
        qb = FakeQueryBuilder(self.calls)
        qb._spec['table'] = name
        return qb

    def set_canned(self, key, value):
        self._canned[key] = value


@pytest.fixture
def fake_sb():
    return FakeSupabase()
