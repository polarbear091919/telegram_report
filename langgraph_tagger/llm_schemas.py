"""Pydantic schema for the OpenAI structured-output call.

Used as response_format in client.chat.completions.parse(...).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from typing_extensions import Literal

REPORT_TYPES = Literal[
    "단일종목", "산업", "섹터", "시황·데일리", "거시·매크로", "퀀트·전략",
    "전략·테마", "IPO", "ESG", "부동산·리츠", "파생·원자재", "채권·크레딧",
    "IR자료", "기타",
]


class OOSSignals(BaseModel):
    """LLM-observed primary-coverage signals. Code re-validates before final OOS marking.

    중요: 'primary coverage'를 강조해 국내 단일종목/산업 리포트가 AAPL/NVDA/TSMC 같은
    해외 peer를 단순 언급하는 경우는 false로 표시해야 한다.
    """
    foreign_primary_coverage: bool = Field(
        description="**리포트의 primary coverage가 해외 상장사**일 때만 true. "
                    "국내 종목/산업 리포트가 외국 티커를 peer/벨류체인/수요처로 "
                    "단순 언급하는 경우는 false."
    )
    etf_or_fund: bool = Field(
        description="ETF 라인업 / 펀드평가 / 펀드비교 (primary coverage가 펀드/ETF)"
    )
    digital_asset: bool = Field(
        description="가상자산·디지털자산·BTC·ETH·코인 (primary coverage가 디지털자산)"
    )
    private_company_likely: bool = Field(
        description="KRX 미등록 + 명백한 비상장/장외 컨텍스트. 자체 IR이면 false. "
                    "공모·IPO·상장예정 컨텍스트(KRX 미매칭이지만 in-scope IPO 후보)도 false."
    )


class LLMExtraction(BaseModel):
    """All fields the LLM populates in one structured-output call."""
    report_type: REPORT_TYPES
    title: Optional[str] = Field(default=None, max_length=120)
    published_at: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD or null if not present on first page"
    )

    stock_codes_raw: list[str] = Field(
        default_factory=list,
        description="KRX 6자리 후보 (영문 포함). 검증은 코드가 함."
    )
    company_names: list[str] = Field(default_factory=list)
    sectors_major: list[str] = Field(
        default_factory=list,
        description="LLM이 본 산업(대). KRX 도메인 검증은 코드가."
    )
    sectors_minor: list[str] = Field(default_factory=list)
    products: list[str] = Field(
        default_factory=list,
        description="원시 제품 토큰. KRX substring 매칭은 코드가."
    )

    publisher_raw: Optional[str] = Field(
        default=None,
        description="자유 텍스트 발행 주체. canonical은 코드가."
    )
    analysts: list[str] = Field(default_factory=list)
    topics: list[str] = Field(
        default_factory=list,
        description="자유 토픽. alias 매핑은 코드가."
    )

    oos_signals: OOSSignals
    self_confidence: Literal["high", "medium", "low"] = Field(
        description="LLM이 자체 판단한 추출 신뢰도"
    )
    notes: Optional[str] = Field(
        default=None,
        description="모호함·특이사항 메모 (한 줄)"
    )
