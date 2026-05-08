"""Test taxonomy() — only public API in v2."""
from langgraph_tagger.vocabulary import taxonomy


def test_taxonomy_has_six_report_types():
    tax = taxonomy()
    assert tax["report_types"] == [
        "단일종목", "산업", "섹터", "IR자료", "전략·시황", "기타",
    ]


def test_taxonomy_oos_reasons_includes_ir_self():
    assert "ir_self" in taxonomy()["oos_reasons"]
    assert taxonomy()["oos_reasons"] == [
        "foreign", "fund", "digital", "private", "ir_self",
    ]


def test_taxonomy_publisher_types_drops_company():
    pt = taxonomy()["publisher_types"]
    assert "company" not in pt
    assert pt == ["broker", "data_provider", "ir_agency", "other"]


def test_lookup_publisher_no_longer_exported():
    import langgraph_tagger.vocabulary as v
    assert not hasattr(v, "lookup_publisher")
    assert not hasattr(v, "map_topics")
