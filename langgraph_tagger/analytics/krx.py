"""KRX master CSV loader + search/lookup helpers.

Reads the project's KRX_stocks_data.csv into a DataFrame with
normalized columns: code, name, sector_major, sector_minor.

Real CSV headers: '종목\\n코드', '종목명', '시장', '산업명(대)',
'산업명(중)', '주요제품'. We use the first 5 (주요제품 is too granular
for the analytics dashboard).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_CODE_COL = '종목\n코드'   # literal newline inside the header — same as real CSV


def load_krx(csv_path: Path) -> pd.DataFrame:
    """Load KRX master CSV into a DataFrame.

    Normalizes Korean source columns to (code, name, sector_major, sector_minor).
    Raises FileNotFoundError if path missing.
    """
    if not csv_path.exists():
        raise FileNotFoundError(str(csv_path))
    raw = pd.read_csv(csv_path, dtype=str, encoding='utf-8-sig')
    # Real CSV (and the fixture on Windows) embeds CRLF inside the quoted header
    # '종목\r\n코드'. Strip carriage returns so the column key matches _CODE_COL.
    raw.columns = [c.replace('\r', '') for c in raw.columns]
    _empty_series = pd.Series([''] * len(raw), index=raw.index)
    df = pd.DataFrame({
        'code': raw[_CODE_COL].astype(str).str.zfill(6),
        'name': raw['종목명'].astype(str),
        'sector_major': raw.get('산업명(대)', _empty_series).astype(str),
        'sector_minor': raw.get('산업명(중)', _empty_series).astype(str),
    })
    return df


def search_stocks(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Filter df by code-prefix or name-substring (case-insensitive).

    Empty query returns all rows.
    """
    q = (query or '').strip()
    if not q:
        return df
    mask = (
        df['code'].str.startswith(q)
        | df['name'].str.contains(q, case=False, na=False, regex=False)
    )
    return df[mask].reset_index(drop=True)


def lookup(df: pd.DataFrame, code: str) -> tuple[str, str, str, str] | None:
    """Return (code, name, sector_major, sector_minor) for the row matching code, or None."""
    rows = df[df['code'] == str(code).zfill(6)]
    if len(rows) == 0:
        return None
    r = rows.iloc[0]
    return (r['code'], r['name'], r['sector_major'], r['sector_minor'])
