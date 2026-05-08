"""Assemble the row-graph from the 10 node modules."""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from langgraph_tagger.nodes.canonicalize import canonicalize
from langgraph_tagger.nodes.decide_status import decide_status
from langgraph_tagger.nodes.enrich import enrich
from langgraph_tagger.nodes.extract_pdf import extract_pdf
from langgraph_tagger.nodes.llm_extract import llm_extract
from langgraph_tagger.nodes.mark_oos_reason import mark_oos_reason
from langgraph_tagger.nodes.oos_gate import oos_gate
from langgraph_tagger.nodes.status_oos import status_oos
from langgraph_tagger.nodes.status_unreadable import status_unreadable
from langgraph_tagger.nodes.validate import validate
from langgraph_tagger.nodes.write import write
from langgraph_tagger.state import RowState
from langgraph_tagger.vocabulary.krx import KRXIndex


def build_graph(client, sb, *, krx: KRXIndex, dry_run: bool, taxonomy_version: str):
    g = StateGraph(RowState)

    g.add_node("extract_pdf", extract_pdf)
    g.add_node("llm_extract", partial(llm_extract, client=client))
    g.add_node("mark_oos_reason", mark_oos_reason)
    g.add_node("status_oos", status_oos)
    g.add_node("status_unreadable", status_unreadable)
    g.add_node("canonicalize", canonicalize)
    g.add_node("validate", partial(validate, krx=krx))
    g.add_node("enrich", partial(enrich, krx=krx))
    g.add_node("decide_status", decide_status)
    g.add_node("write", partial(write, sb=sb, dry_run=dry_run, taxonomy_version=taxonomy_version))

    g.add_edge(START, "extract_pdf")
    g.add_edge("extract_pdf", "llm_extract")
    # oos_gate is routing-only — uses partial to inject KRX. mark_oos_reason
    # is a separate state-mutating node that sets is_oos / oos_reason.
    g.add_conditional_edges(
        "llm_extract",
        partial(oos_gate, krx=krx),
        {
            "mark_oos_reason":   "mark_oos_reason",
            "status_unreadable": "status_unreadable",
            "canonicalize":      "canonicalize",
        },
    )
    g.add_edge("mark_oos_reason", "status_oos")
    g.add_edge("status_oos", "write")
    g.add_edge("status_unreadable", "write")
    g.add_edge("canonicalize", "validate")
    g.add_edge("validate", "enrich")
    g.add_edge("enrich", "decide_status")
    g.add_edge("decide_status", "write")
    g.add_edge("write", END)

    return g.compile()
