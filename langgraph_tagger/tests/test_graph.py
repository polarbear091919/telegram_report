"""End-to-end graph smoke tests with mock OpenAI + mock supabase."""
from datetime import datetime, timezone

import pytest

from langgraph_tagger.graph import build_graph
from langgraph_tagger.tests.conftest import make_llm_extraction


@pytest.mark.asyncio
async def test_in_scope_single_stock_flows_end_to_end(krx, mock_openai_client, mock_supabase, tmp_path, monkeypatch):
    """In-scope 경로의 진짜 end-to-end. tiny PDF 합성으로 extract_pdf 통과시키고
    canonicalize → validate → enrich → decide_status → write까지 검증."""
    import fitz
    pdf = tmp_path / "samsung.pdf"
    doc = fitz.open()
    doc.new_page().insert_text(
        (72, 72),
        "키움증권 리서치센터\n분석가 홍길동\n삼성전자 [005930]\n투자의견 매수 목표주가 100,000원",
        fontsize=11,
    )
    doc.save(pdf)
    doc.close()
    monkeypatch.setenv("STORAGE_BASE_DIR", str(tmp_path))

    mock_openai_client.set_response(make_llm_extraction(
        report_type="단일종목",
        stock_codes_raw=["005930"],
        sectors_major=["반도체"],
        sectors_minor=["메모리반도체"],
        publisher_raw="키움",
        topics=["연준"],
    ))
    app = build_graph(mock_openai_client, mock_supabase, krx=krx,
                      dry_run=False, taxonomy_version="KRX@2026-05-08")

    init = {
        "id": 1,
        "file_path": "samsung.pdf",
        "file_name": "samsung.pdf",
        "sent_at": datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        "caption": None,
        "chat_username": "x",
        "worker_id": "test",
        "model": "gpt-5.4-mini",
    }
    final = await app.ainvoke(init)

    # In-scope path: not OOS, not unreadable
    assert final["tagging_status"] == "auto"
    assert final.get("is_oos") is not True
    # write was called once with the expected canonicalized payload
    assert len(mock_supabase.executed) == 1
    sql, args = mock_supabase.executed[0]
    assert args[2] == "단일종목"          # report_type
    assert args[3] == "키움증권"           # publisher canonical
    assert args[4] == "broker"             # publisher_type
    assert "005930" in args[7]             # stock_codes
    assert args[13] is None                # out_of_scope_reason


@pytest.mark.asyncio
async def test_unreadable_pdf_routes_to_status_unreadable(krx, mock_openai_client, mock_supabase, monkeypatch, tmp_path):
    """Missing file → status_unreadable → review_needed/low. Splits the
    smoke coverage so the in-scope test above can't accidentally fall
    back to this path again."""
    monkeypatch.setenv("STORAGE_BASE_DIR", str(tmp_path))   # empty dir
    app = build_graph(mock_openai_client, mock_supabase, krx=krx,
                      dry_run=False, taxonomy_version="KRX@2026-05-08")

    init = {
        "id": 99,
        "file_path": "missing.pdf",
        "file_name": "missing.pdf",
        "sent_at": datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        "caption": None,
        "chat_username": "x",
        "worker_id": "test",
        "model": "gpt-5.4-mini",
    }
    final = await app.ainvoke(init)

    assert final["tagging_status"] == "review_needed"
    assert final["tagging_confidence"] == "low"
    assert final["tagging_notes"] == "first_page_unreadable"
    # llm_extract should NOT have been called for an unreadable PDF
    mock_openai_client.chat.completions.parse.assert_not_called()


@pytest.mark.asyncio
async def test_oos_foreign_short_circuits_to_status_oos(krx, mock_openai_client, mock_supabase, tmp_path, monkeypatch):
    # Make a tiny PDF so extract_pdf succeeds
    import fitz
    pdf = tmp_path / "x.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "키움증권 분석가 홍길동", fontsize=12)
    doc.save(pdf)
    doc.close()
    monkeypatch.setenv("STORAGE_BASE_DIR", str(tmp_path))

    # Mock OpenAI to return foreign primary coverage signal
    from langgraph_tagger.llm_schemas import OOSSignals
    mock_openai_client.set_response(make_llm_extraction(
        report_type="기타",
        oos_signals=OOSSignals(
            foreign_primary_coverage=True, etf_or_fund=False,
            digital_asset=False, private_company_likely=False,
        ),
    ))

    app = build_graph(mock_openai_client, mock_supabase, krx=krx,
                      dry_run=False, taxonomy_version="KRX@2026-05-08")

    init = {
        "id": 2,
        "file_path": "x.pdf",
        "file_name": "x.pdf",
        "sent_at": datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        "caption": None,
        "chat_username": "x",
        "worker_id": "test",
        "model": "gpt-5.4-mini",
    }
    final = await app.ainvoke(init)

    assert final["tagging_status"] == "auto"
    assert final["tagging_confidence"] == "high"
    assert final["oos_reason"] == "foreign"
    # write was called once with report_type=기타 + oos_reason=foreign
    assert len(mock_supabase.executed) == 1
    sql, args = mock_supabase.executed[0]
    assert args[2] == "기타"
    assert args[13] == "foreign"
