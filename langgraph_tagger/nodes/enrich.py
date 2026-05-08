"""enrich node: KRX-driven industry merge, single-stock auto-fill, published_at fallback."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from langgraph_tagger.state import RowState
from langgraph_tagger.vocabulary.krx import KRXIndex

KST = timezone(timedelta(hours=9))


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def enrich(state: RowState, *, krx: KRXIndex) -> dict:
    raw = state["llm_raw"]
    company_names = list(raw.company_names)
    sectors_major = list(state["sectors_major_valid"])
    sectors_minor = list(state["sectors_minor_valid"])
    # validate already enforced KRX substring membership and split unknowns aside.
    products = list(state.get("products_valid", []))

    # 1. Single-stock auto-enrichment (단일종목/IR자료/IPO + KRX-matched code)
    if raw.report_type in ("단일종목", "IR자료", "IPO"):
        for code in state.get("stock_codes_valid", []):
            entry = krx.lookup(code)
            if not entry:
                continue
            if entry.name and entry.name not in company_names:
                company_names.append(entry.name)
            if entry.sector_major and entry.sector_major not in sectors_major:
                sectors_major.append(entry.sector_major)
            if entry.sector_minor and entry.sector_minor not in sectors_minor:
                sectors_minor.append(entry.sector_minor)
            for tok in krx.split_products(entry.products_text):
                if tok not in products:
                    products.append(tok)

    # 2. validate already filtered products. No double-filter here.

    # 3. Depth roll-up: products → minor/major; minor → major
    for p in products:
        for entry in krx.rows_with_product(p):
            if entry.sector_minor and entry.sector_minor not in sectors_minor:
                sectors_minor.append(entry.sector_minor)
            if entry.sector_major and entry.sector_major not in sectors_major:
                sectors_major.append(entry.sector_major)
    for sm in list(sectors_minor):
        for entry in krx.rows_with_sector_minor(sm):
            if entry.sector_major and entry.sector_major not in sectors_major:
                sectors_major.append(entry.sector_major)

    # 4. published_at fallback
    pub = _parse_iso_date(raw.published_at)
    used_fallback = False
    if pub is None:
        sent_at = state["sent_at"]
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        pub = sent_at.astimezone(KST).date()
        used_fallback = True

    return {
        "company_names_final": company_names,
        "sectors_major_final": sectors_major,
        "sectors_minor_final": sectors_minor,
        "products_final": products,
        "published_at_final": pub,
        "used_sent_at_fallback": used_fallback,
    }
