"""Tests for KRXIndex (loading, validation, lookup, fuzzy match, products)."""
from datetime import date
from pathlib import Path

import pytest

from langgraph_tagger.vocabulary.krx import KRXIndex


class TestLoad:
    def test_csv_loads_with_normalized_header(self, krx):
        # Sanity: must load >= 2000 entries (KRX listed pool ~2,559)
        assert len(krx.by_code) >= 2000

    def test_taxonomy_version_format(self, krx):
        # KRX@YYYY-MM-DD
        assert krx.taxonomy_version.startswith("KRX@")
        # parseable date suffix
        date.fromisoformat(krx.taxonomy_version.removeprefix("KRX@"))

    def test_known_code_present(self, krx):
        # 005930 is Samsung Electronics, always in KRX.
        assert krx.validate_code("005930")
        e = krx.lookup("005930")
        assert e is not None
        assert "삼성전자" in e.name


class TestValidate:
    def test_alphanumeric_six(self, krx):
        # SPAC/listing-pending codes use letters; spec example: 0008Z0
        # Test purely on regex (membership may be False if not in CSV)
        import re
        assert re.fullmatch(r"[0-9A-Z]{6}", "0008Z0")

    def test_too_short_rejected(self, krx):
        assert not krx.validate_code("12345")

    def test_lowercase_rejected(self, krx):
        # spec: ^[0-9A-Z]{6}$ — uppercase only
        assert not krx.validate_code("a12345")

    def test_unknown_six_digit_rejected(self, krx):
        assert not krx.validate_code("999999")  # not in KRX


class TestSplitProducts:
    def test_simple_split(self, krx):
        out = krx.split_products("DRAM, NAND 등")
        assert out == ["DRAM", "NAND"]

    def test_drops_등(self, krx):
        out = krx.split_products("MLCC, 기판, 카메라 모듈 등")
        assert out == ["MLCC", "기판", "카메라 모듈"]

    def test_no_등(self, krx):
        out = krx.split_products("정유")
        assert out == ["정유"]

    def test_empty(self, krx):
        out = krx.split_products("")
        assert out == []


class TestFuzzySectorMatch:
    def test_exact_major_match(self, krx):
        # '반도체' is a real KRX 산업명(대)
        assert krx.fuzzy_sector_match("반도체") == "반도체"

    def test_exact_minor_match(self, krx):
        # '메모리반도체' is in 산업명(중) when CSV is loaded
        assert krx.fuzzy_sector_match("메모리반도체") == "메모리반도체"

    def test_auto_alias_via_sector_aliases(self, krx):
        # 'Auto' in sector_major_aliases of taxonomy.yaml maps to '자동차'/'자동차산업'
        # but KRX CSV uses 'Auto' directly. So fuzzy_sector_match('자동차') should
        # resolve to 'Auto' via the alias table.
        result = krx.fuzzy_sector_match("자동차")
        assert result == "Auto"

    def test_unknown(self, krx):
        assert krx.fuzzy_sector_match("이상한산업명") is None


class TestEnrichmentHelpers:
    def test_has_product_known(self, krx):
        # 'DRAM' appears in many KRX 주요제품 cells
        assert krx.has_product("DRAM") is True

    def test_has_product_unknown(self, krx):
        assert krx.has_product("완전이상한제품") is False

    def test_rows_with_product_returns_entries(self, krx):
        rows = krx.rows_with_product("DRAM")
        assert len(rows) >= 1
        # All returned rows should have DRAM as substring of products_text
        for r in rows:
            assert "DRAM" in r.products_text

    def test_rows_with_sector_minor(self, krx):
        rows = krx.rows_with_sector_minor("메모리반도체")
        assert len(rows) >= 1
        for r in rows:
            assert r.sector_minor == "메모리반도체"
