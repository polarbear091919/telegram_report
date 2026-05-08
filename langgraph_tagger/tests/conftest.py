"""Shared test fixtures for langgraph_tagger."""
from pathlib import Path

import pytest

from langgraph_tagger.vocabulary.krx import KRXIndex


@pytest.fixture(scope="session")
def krx() -> KRXIndex:
    """Real KRX index loaded once per session."""
    return KRXIndex.load(Path("docs/stock_data/KRX_stocks_data.csv"))
