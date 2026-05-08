"""validate node: KRX stock_code regex + membership; sector fuzzy match;
products substring membership.

Spec §6.6 정책 보존: stock_codes/sectors/products 셋 다 KRX 도메인 외면
review_needed/low (decide_status에서 처리). silent drop 안 함.
"""
from __future__ import annotations

import re

from langgraph_tagger.state import RowState
from langgraph_tagger.vocabulary.krx import KRXIndex

_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


def validate(state: RowState, *, krx: KRXIndex) -> dict:
    raw = state["llm_raw"]
    valid_codes: list[str] = []
    unknown_codes: list[str] = []
    for c in raw.stock_codes_raw:
        if not _CODE_RE.fullmatch(c):
            unknown_codes.append(c)
            continue
        if krx.validate_code(c):
            valid_codes.append(c)
        else:
            unknown_codes.append(c)

    smajor_valid: list[str] = []
    sminor_valid: list[str] = []
    s_unknown: list[str] = []
    for s in raw.sectors_major:
        m = krx.fuzzy_sector_match(s)
        if m and m in krx.sectors_major:
            smajor_valid.append(m)
        else:
            s_unknown.append(s)
    for s in raw.sectors_minor:
        m = krx.fuzzy_sector_match(s)
        if m and m in krx.sectors_minor:
            sminor_valid.append(m)
        else:
            s_unknown.append(s)

    # products: KRX substring 멤버십 검증 (spec §6.6 unknown_product → review_needed/low)
    # has_product()는 silent drop 안 함 — products_unknown 분리해서 decide_status가 처리.
    products_valid: list[str] = []
    products_unknown: list[str] = []
    for p in raw.products:
        if krx.has_product(p):
            products_valid.append(p)
        else:
            products_unknown.append(p)

    return {
        "stock_codes_valid": valid_codes,
        "stock_codes_unknown": unknown_codes,
        "sectors_major_valid": smajor_valid,
        "sectors_minor_valid": sminor_valid,
        "sectors_unknown": s_unknown,
        "products_valid": products_valid,
        "products_unknown": products_unknown,
    }
