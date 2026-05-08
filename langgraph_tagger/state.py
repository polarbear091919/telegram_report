"""LangGraph row-graph state.

TypedDict with all keys total=False — each node sets only the keys it owns.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional, TYPE_CHECKING

from typing_extensions import Literal, TypedDict

if TYPE_CHECKING:
    from langgraph_tagger.llm_schemas import LLMExtraction


class RowState(TypedDict, total=False):
    # Input (populated at claim time)
    id: int
    file_path: str
    file_name: str
    sent_at: datetime
    caption: Optional[str]
    chat_username: str
    worker_id: str
    model: str

    # extract_pdf output
    pdf_text: str
    pages_used: list[int]
    pdf_unreadable: bool

    # llm_extract output
    llm_raw: Optional["LLMExtraction"]
    llm_refusal: Optional[str]

    # oos_gate output
    is_oos: bool
    oos_reason: Optional[Literal["foreign", "fund", "digital", "private"]]

    # canonicalize output
    publisher_canon: Optional[str]
    publisher_type: Optional[Literal["broker", "company", "data_provider", "ir_agency", "other"]]
    topics_canon: list[str]
    topic_unmapped: list[str]

    # validate output
    stock_codes_valid: list[str]
    stock_codes_unknown: list[str]
    sectors_major_valid: list[str]
    sectors_minor_valid: list[str]
    sectors_unknown: list[str]
    products_valid: list[str]
    products_unknown: list[str]

    # enrich output
    company_names_final: list[str]
    sectors_major_final: list[str]
    sectors_minor_final: list[str]
    products_final: list[str]
    published_at_final: Optional[date]
    used_sent_at_fallback: bool

    # decide_status / status_oos / status_unreadable output
    tagging_status: Literal["auto", "review_needed"]
    tagging_confidence: Literal["high", "medium", "low"]
    tagging_notes: Optional[str]
