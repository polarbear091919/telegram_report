from langgraph_tagger.nodes.validate import validate
from langgraph_tagger.tests.conftest import make_llm_extraction


def test_valid_krx_codes_only(krx):
    state = {"llm_raw": make_llm_extraction(
        stock_codes_raw=["005930"],  # Samsung
        sectors_major=["반도체"],
        sectors_minor=["메모리반도체"],
    )}
    out = validate(state, krx=krx)
    assert out["stock_codes_valid"] == ["005930"]
    assert out["stock_codes_unknown"] == []
    assert out["sectors_major_valid"] == ["반도체"]
    assert out["sectors_minor_valid"] == ["메모리반도체"]
    assert out["sectors_unknown"] == []


def test_unknown_six_digit_code_split_correctly(krx):
    state = {"llm_raw": make_llm_extraction(
        stock_codes_raw=["005930", "999999"],
        sectors_major=[],
        sectors_minor=[],
    )}
    out = validate(state, krx=krx)
    assert out["stock_codes_valid"] == ["005930"]
    assert out["stock_codes_unknown"] == ["999999"]


def test_invalid_format_goes_to_unknown(krx):
    state = {"llm_raw": make_llm_extraction(
        stock_codes_raw=["abc"],   # not 6 chars
        sectors_major=[],
        sectors_minor=[],
    )}
    out = validate(state, krx=krx)
    assert out["stock_codes_valid"] == []
    assert out["stock_codes_unknown"] == ["abc"]


def test_auto_alias_resolves_to_canonical(krx):
    state = {"llm_raw": make_llm_extraction(
        stock_codes_raw=[],
        sectors_major=["자동차"],   # alias for 'Auto'
        sectors_minor=[],
    )}
    out = validate(state, krx=krx)
    assert out["sectors_major_valid"] == ["Auto"]
    assert out["sectors_unknown"] == []


def test_unknown_sector_goes_to_unknown(krx):
    state = {"llm_raw": make_llm_extraction(
        stock_codes_raw=[],
        sectors_major=["완전이상한산업"],
        sectors_minor=[],
    )}
    out = validate(state, krx=krx)
    assert out["sectors_major_valid"] == []
    assert "완전이상한산업" in out["sectors_unknown"]


def test_known_product_goes_to_valid(krx):
    state = {"llm_raw": make_llm_extraction(
        stock_codes_raw=[], sectors_major=[], sectors_minor=[],
        products=["DRAM", "NAND"],
    )}
    out = validate(state, krx=krx)
    # Both DRAM and NAND appear in many KRX 주요제품 cells
    assert "DRAM" in out["products_valid"]
    assert "NAND" in out["products_valid"]
    assert out["products_unknown"] == []


def test_unknown_product_goes_to_unknown(krx):
    """Spec §6.6: unknown_product → review_needed/low (no silent drop)."""
    state = {"llm_raw": make_llm_extraction(
        stock_codes_raw=[], sectors_major=[], sectors_minor=[],
        products=["완전이상한제품"],
    )}
    out = validate(state, krx=krx)
    assert out["products_valid"] == []
    assert "완전이상한제품" in out["products_unknown"]


def test_mixed_known_and_unknown_products(krx):
    state = {"llm_raw": make_llm_extraction(
        stock_codes_raw=[], sectors_major=[], sectors_minor=[],
        products=["DRAM", "완전이상한제품", "NAND"],
    )}
    out = validate(state, krx=krx)
    assert out["products_valid"] == ["DRAM", "NAND"]
    assert out["products_unknown"] == ["완전이상한제품"]
