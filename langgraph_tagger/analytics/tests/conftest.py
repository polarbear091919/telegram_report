"""Shared fixtures for analytics tests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def krx_csv(tmp_path: Path) -> Path:
    """Minimal KRX master CSV for unit tests.

    Headers match the real docs/stock_data/KRX_stocks_data.csv:
    '종목\\n코드, 종목명, 시장, 산업명(대), 산업명(중), 주요제품'.
    """
    p = tmp_path / 'krx_test.csv'
    p.write_text(
        '"종목\n코드",종목명,시장,산업명(대),산업명(중),주요제품\n'
        '005930,삼성전자,KOSPI,반도체,메모리반도체,DRAM/NAND\n'
        '000660,SK하이닉스,KOSPI,반도체,메모리반도체,DRAM/NAND\n'
        '373220,LG에너지솔루션,KOSPI,2차전지,셀,리튬이온배터리\n'
        '035720,카카오,KOSPI,IT,플랫폼,메신저\n'
        '042660,한화오션,KOSPI,조선,상선,LNG선\n',
        encoding='utf-8',
    )
    return p


@pytest.fixture
def inscope_df() -> pd.DataFrame:
    """Small DataFrame representing in-scope rows for aggregate tests.

    Every row has both published_at and sent_at. effective_date will be
    derived from these by db.py / aggregate._ensure_effective_date.
    """
    return pd.DataFrame([
        # 단일종목 + 단일 stock_code
        {'published_at': '2026-05-01', 'sent_at': '2026-05-01T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': '메리츠',
         'stock_codes': ['005930'], 'sectors_major': ['반도체'],
         'sectors_minor': ['메모리반도체'], 'products': ['DRAM'],
         'out_of_scope_reason': None},
        # 단일종목 + 같은 종목, 다른 발행처
        {'published_at': '2026-05-02', 'sent_at': '2026-05-02T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': '키움',
         'stock_codes': ['005930'], 'sectors_major': ['반도체'],
         'sectors_minor': ['메모리반도체'], 'products': ['DRAM', 'NAND'],
         'out_of_scope_reason': None},
        # 단일종목 — 다른 종목
        {'published_at': '2026-05-03', 'sent_at': '2026-05-03T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': '키움',
         'stock_codes': ['000660'], 'sectors_major': ['반도체'],
         'sectors_minor': ['메모리반도체'], 'products': ['DRAM'],
         'out_of_scope_reason': None},
        # 섹터 — multi-stock
        {'published_at': '2026-05-04', 'sent_at': '2026-05-04T08:00:00+00:00',
         'report_type': '섹터', 'publisher': 'NH',
         'stock_codes': ['005930', '000660'], 'sectors_major': ['반도체'],
         'sectors_minor': ['메모리반도체'], 'products': ['DRAM'],
         'out_of_scope_reason': None},
        # 산업 — 빈 stock_codes/sectors
        {'published_at': '2026-05-05', 'sent_at': '2026-05-05T08:00:00+00:00',
         'report_type': '산업', 'publisher': '메리츠',
         'stock_codes': [], 'sectors_major': [],
         'sectors_minor': [], 'products': [],
         'out_of_scope_reason': None},
        # 2차전지 — 다른 sector
        {'published_at': '2026-05-06', 'sent_at': '2026-05-06T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': 'NH',
         'stock_codes': ['373220'], 'sectors_major': ['2차전지'],
         'sectors_minor': ['셀'], 'products': ['리튬이온배터리'],
         'out_of_scope_reason': None},
    ])


@pytest.fixture
def with_oos_df(inscope_df: pd.DataFrame) -> pd.DataFrame:
    """inscope + 2 OOS rows. OOS rows mirror writer semantics: published_at
    is None (writer sets it NULL for OOS), so effective_date must fall back
    to sent_at. This is the test case that exercises the fallback path."""
    extra = pd.DataFrame([
        {'published_at': None, 'sent_at': '2026-05-07T08:00:00+00:00',
         'report_type': 'IR자료', 'publisher': '한국기업평가',
         'stock_codes': ['005930'], 'sectors_major': [],
         'sectors_minor': [], 'products': [],
         'out_of_scope_reason': 'ir_self'},
        {'published_at': None, 'sent_at': '2026-05-08T08:00:00+00:00',
         'report_type': '단일종목', 'publisher': 'Reuters',
         'stock_codes': ['005930'], 'sectors_major': [],
         'sectors_minor': [], 'products': [],
         'out_of_scope_reason': 'foreign'},
    ])
    return pd.concat([inscope_df, extra], ignore_index=True)
