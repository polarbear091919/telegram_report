"""KRX listed-stock index: loaded once from CSV, used for validation and enrichment.

Headers (after normalization): 종목코드, 종목명, 시장, 산업명(대), 산업명(중), 주요제품
The first header cell is '종목\\n코드' in the file (multi-line). We strip newlines on load.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Optional

import yaml

_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


@dataclass(frozen=True)
class KRXEntry:
    code: str
    name: str
    market: str           # KOSPI / KOSDAQ / KOSDAQ GLOBAL
    sector_major: str
    sector_minor: str
    products_text: str    # free text


class KRXIndex:
    def __init__(self, entries: list[KRXEntry], csv_path: Path) -> None:
        self.by_code: dict[str, KRXEntry] = {e.code: e for e in entries}
        self.sectors_major: set[str] = {e.sector_major for e in entries if e.sector_major}
        self.sectors_minor: set[str] = {e.sector_minor for e in entries if e.sector_minor}
        self.taxonomy_version: str = self._build_version(csv_path)
        self._sector_aliases: dict[str, str] = self._build_sector_aliases()

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

    def split_products(self, products_text: str) -> list[str]:
        """ "MLCC, 기판, 카메라 모듈 등" → ['MLCC', '기판', '카메라 모듈']
            "DRAM, NAND 등"           → ['DRAM', 'NAND']

        Trailing ' 등' 접미사도 제거해야 한다 — KRX CSV에서 마지막 토큰이
        "X 등" 형태인 경우가 빈번 (예: "DRAM, NAND 등").
        """
        out: list[str] = []
        for token in products_text.split(","):
            t = token.strip()
            # Strip trailing ' 등' suffix (with leading space)
            if t.endswith(" 등"):
                t = t[:-2].strip()
            if not t or t == "등":
                continue
            out.append(t)
        return out

    def fuzzy_sector_match(self, value: str) -> Optional[str]:
        """alias map (e.g., '자동차'/'Auto'/'자동차산업' → 'Auto') and exact membership."""
        if not value:
            return None
        norm = "".join(value.split()).lower()
        # 1. Direct membership (case-insensitive, whitespace-insensitive)
        for s in self.sectors_major | self.sectors_minor:
            if "".join(s.split()).lower() == norm:
                return s
        # 2. Alias table from taxonomy.yaml (sector_major_aliases)
        return self._sector_aliases.get(norm)

    def has_product(self, product_token: str) -> bool:
        """True if product_token appears as substring in any KRX row's products_text.

        Used by validate node to split LLM-extracted products into
        products_valid (KRX-known) / products_unknown (review_needed/low).
        DOES NOT silently drop — caller must keep the unknown set visible
        per spec §6.6.
        """
        return any(product_token in e.products_text for e in self.by_code.values())

    def rows_with_product(self, product_token: str) -> list[KRXEntry]:
        return [e for e in self.by_code.values() if product_token in e.products_text]

    def rows_with_sector_minor(self, sector_minor: str) -> list[KRXEntry]:
        return [e for e in self.by_code.values() if e.sector_minor == sector_minor]

    @staticmethod
    def _build_version(csv_path: Path) -> str:
        ts = datetime.fromtimestamp(csv_path.stat().st_mtime)
        return f"KRX@{ts:%Y-%m-%d}"

    @staticmethod
    def _build_sector_aliases() -> dict[str, str]:
        """Normalize taxonomy.yaml sector_major_aliases into a flat lookup dict."""
        tax_path = Path(__file__).parent / "taxonomy.yaml"
        raw = yaml.safe_load(tax_path.read_text(encoding="utf-8"))
        aliases = raw.get("sector_major_aliases", {}) or {}
        out: dict[str, str] = {}
        for canonical, alias_list in aliases.items():
            for alias in alias_list:
                key = "".join(alias.split()).lower()
                out[key] = canonical
        return out
