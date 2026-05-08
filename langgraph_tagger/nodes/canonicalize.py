"""canonicalize node: publisher and topic lookup via vocabulary YAML."""
from langgraph_tagger.state import RowState
from langgraph_tagger.vocabulary import lookup_publisher, map_topics


def canonicalize(state: RowState) -> dict:
    raw = state["llm_raw"]
    pub_canon, pub_type = lookup_publisher(raw.publisher_raw)
    topics_canon, topic_unmapped = map_topics(raw.topics)
    return {
        "publisher_canon": pub_canon,
        "publisher_type": pub_type,
        "topics_canon": topics_canon,
        "topic_unmapped": topic_unmapped,
    }
