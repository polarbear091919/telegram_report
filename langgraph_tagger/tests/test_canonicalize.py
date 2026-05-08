from langgraph_tagger.nodes.canonicalize import canonicalize
from langgraph_tagger.tests.conftest import make_llm_extraction


def test_known_publisher_resolved():
    state = {"llm_raw": make_llm_extraction(
        publisher_raw="키움", topics=["연준"]
    )}
    out = canonicalize(state)
    assert out["publisher_canon"] == "키움증권"
    assert out["publisher_type"] == "broker"
    assert out["topics_canon"] == ["FOMC"]
    assert out["topic_unmapped"] == []


def test_unknown_publisher_returns_none_pair():
    state = {"llm_raw": make_llm_extraction(
        publisher_raw="UnknownBoutique LLC", topics=[]
    )}
    out = canonicalize(state)
    assert out["publisher_canon"] is None
    assert out["publisher_type"] is None


def test_topic_unmapped_kept_separate():
    state = {"llm_raw": make_llm_extraction(
        publisher_raw="삼성", topics=["연준", "이상한새토픽"]
    )}
    out = canonicalize(state)
    assert "FOMC" in out["topics_canon"]
    assert out["topic_unmapped"] == ["이상한새토픽"]


def test_publisher_raw_none_handled():
    state = {"llm_raw": make_llm_extraction(publisher_raw=None, topics=[])}
    out = canonicalize(state)
    assert out["publisher_canon"] is None
    assert out["publisher_type"] is None
