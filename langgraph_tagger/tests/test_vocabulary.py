"""Tests for vocabulary.lookup_publisher and map_topics."""
import pytest
from langgraph_tagger.vocabulary import lookup_publisher, map_topics


class TestLookupPublisher:
    def test_canonical_match(self):
        canon, ptype = lookup_publisher("키움증권")
        assert canon == "키움증권"
        assert ptype == "broker"

    def test_alias_match(self):
        canon, ptype = lookup_publisher("키움")
        assert canon == "키움증권"
        assert ptype == "broker"

    def test_alias_match_with_whitespace(self):
        canon, ptype = lookup_publisher("  Kiwoom  ")
        assert canon == "키움증권"
        assert ptype == "broker"

    def test_data_provider(self):
        canon, ptype = lookup_publisher("FnGuide")
        assert canon == "FnGuide"
        assert ptype == "data_provider"

    def test_data_provider_alias(self):
        canon, ptype = lookup_publisher("에프앤가이드")
        assert canon == "FnGuide"
        assert ptype == "data_provider"

    def test_ir_agency(self):
        canon, ptype = lookup_publisher("IRKUDOS")
        assert canon == "IRKUDOS"
        assert ptype == "ir_agency"

    def test_ir_agency_alias(self):
        canon, ptype = lookup_publisher("IR쿠도스")
        assert canon == "IRKUDOS"
        assert ptype == "ir_agency"

    def test_other_with_company_override(self):
        canon, ptype = lookup_publisher("해당기업")
        assert canon == "해당기업"
        assert ptype == "company"  # publisher_type_override applied

    def test_other_canonical(self):
        canon, ptype = lookup_publisher("한국은행")
        assert canon == "한국은행"
        assert ptype == "other"

    def test_unknown_returns_none_pair(self):
        canon, ptype = lookup_publisher("Random Boutique LLC")
        assert canon is None
        assert ptype is None

    def test_none_input_returns_none_pair(self):
        canon, ptype = lookup_publisher(None)
        assert canon is None
        assert ptype is None

    def test_empty_input_returns_none_pair(self):
        canon, ptype = lookup_publisher("")
        assert canon is None
        assert ptype is None


class TestMapTopics:
    def test_canonical_passthrough(self):
        canon, unmapped = map_topics(["FOMC"])
        assert canon == ["FOMC"]
        assert unmapped == []

    def test_alias_normalized(self):
        canon, unmapped = map_topics(["연준"])
        assert canon == ["FOMC"]
        assert unmapped == []

    def test_multiple_mixed(self):
        canon, unmapped = map_topics(["연준", "AI", "이상한신규토픽"])
        assert "FOMC" in canon
        assert "AI수혜" in canon
        assert unmapped == ["이상한신규토픽"]

    def test_empty_input(self):
        canon, unmapped = map_topics([])
        assert canon == []
        assert unmapped == []

    def test_dedup_canonical(self):
        # Both 'Fed' and 'FOMC' map to FOMC; dedup expected.
        canon, unmapped = map_topics(["Fed", "FOMC"])
        assert canon == ["FOMC"]
        assert unmapped == []
