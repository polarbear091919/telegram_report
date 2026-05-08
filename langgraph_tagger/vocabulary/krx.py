"""KRX listed-stock index: loaded once from CSV, used for v2 resolve_krx node.

Headers (after normalization): 종목코드, 종목명, 시장, 산업명(대), 산업명(중), 주요제품
The first header cell is '종목\\n코드' in the file (multi-line). We strip newlines on load.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


@dataclass(frozen=True)
class KRXEntry:
    code: str
    name: str
    market: str           # KOSPI / KOSDAQ / KOSDAQ GLOBAL
    sector_major: str
    sector_minor: str
    products_text: str    # free text


def _normalize_name(s: str) -> str:
    """Whitespace+case insensitive key for company-name fuzzy match."""
    return "".join(s.split()).lower()


class KRXIndex:
    def __init__(self, entries: list[KRXEntry], csv_path: Path) -> None:
        self.by_code: dict[str, KRXEntry] = {e.code: e for e in entries}
        self.taxonomy_version: str = self._build_version(csv_path)
        # Pre-built name index for lookup_by_name
        self._by_name: dict[str, KRXEntry] = {}
        for e in entries:
            key = _normalize_name(e.name)
            # First-match wins on collision (rare; KRX names are unique)
            self._by_name.setdefault(key, e)

    @classmethod
    def load(cls, csv_path: Path) -> "KRXIndex":
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = [c.replace("\r", "").replace("\n", "").strip() for c in next(reader)]
            expected = ["종목코드", "종목명", "시장", "산업명(대)", "산업명(중)", "주요제품"]
            if header != expected:
                raise ValueError(f"unexpected KRX CSV header: {header} != {expected}")
            entries = []
            for row in reader:
                if len(row) < 6:
                    continue
                entries.append(KRXEntry(
                    code=row[0].strip(),
                    name=row[1].strip(),
                    market=row[2].strip(),
                    sector_major=row[3].strip(),
                    sector_minor=row[4].strip(),
                    products_text=row[5].strip(),
                ))
        return cls(entries, csv_path)

    def validate_code(self, code: str) -> bool:
        return bool(_CODE_RE.fullmatch(code)) and code in self.by_code

    def lookup(self, code: str) -> Optional[KRXEntry]:
        return self.by_code.get(code)

    def lookup_by_name(self, name: str) -> Optional[KRXEntry]:
        """Fuzzy company-name lookup (whitespace+case insensitive). None on miss."""
        if not name:
            return None
        return self._by_name.get(_normalize_name(name))

    def split_products(self, products_text: str) -> list[str]:
        """ "MLCC, 기판, 카메라 모듈 등" → ['MLCC', '기판', '카메라 모듈']
            "DRAM, NAND 등"           → ['DRAM', 'NAND']

        Trailing ' 등' 접미사도 제거해야 한다 — KRX CSV에서 마지막 토큰이
        "X 등" 형태인 경우가 빈번 (예: "DRAM, NAND 등").
        """
        out: list[str] = []
        for token in products_text.split(","):
            t = token.strip()
            if t.endswith(" 등"):
                t = t[:-2].strip()
            if not t or t == "등":
                continue
            out.append(t)
        return out

    @staticmethod
    def _build_version(csv_path: Path) -> str:
        ts = datetime.fromtimestamp(csv_path.stat().st_mtime)
        return f"KRX@{ts:%Y-%m-%d}"
