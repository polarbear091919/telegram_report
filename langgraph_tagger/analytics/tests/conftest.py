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
