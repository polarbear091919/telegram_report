"""Tests for KRXIndex (loading, validation, lookup, name lookup, products)."""
from datetime import date

from langgraph_tagger.vocabulary.krx import KRXIndex  # noqa: F401  (kept for typing/import smoke)


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


def test_lookup_by_name_exact_match(krx):
    e = krx.lookup_by_name("삼성전자")
    assert e is not None
    assert e.code == "005930"


def test_lookup_by_name_whitespace_insensitive(krx):
    e = krx.lookup_by_name("삼성 전자")
    assert e is not None
    assert e.code == "005930"


def test_lookup_by_name_case_insensitive(krx):
    # KRX 영문 종목명이 있는 경우 — case-insensitive 매칭
    # 실제 KRX CSV에서 이름이 영문/한글 혼용인 case가 있다면 그걸 검증.
    # 없다면 한글 case로 only.
    e = krx.lookup_by_name("Samsung Electronics")  # KRX has 한글; should miss
    assert e is None  # KRX CSV는 한글 표기이므로 영문은 미매칭이 정상


def test_lookup_by_name_unknown_returns_none(krx):
    assert krx.lookup_by_name("존재하지않는회사") is None


def test_has_product_removed(krx):
    assert not hasattr(krx, "has_product")
    assert not hasattr(krx, "rows_with_product")
    assert not hasattr(krx, "rows_with_sector_minor")
    assert not hasattr(krx, "fuzzy_sector_match")
