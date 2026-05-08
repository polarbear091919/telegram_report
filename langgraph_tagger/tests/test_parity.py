"""Parity regression: run the row graph headlessly per fixture and assert
the DB UPDATE payload matches the expected snapshot from friendly-mclaren
skill outputs (or hand-curated equivalents).

This is the primary check that environment-change-only is honoured.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from langgraph_tagger.graph import build_graph
from langgraph_tagger.llm_schemas import LLMExtraction, OOSSignals
from langgraph_tagger.supabase_io import UPDATE_SQL


FIXTURES = Path(__file__).parent / "parity" / "fixtures.json"


def _load_fixtures() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _make_llm_mock(payload: dict) -> LLMExtraction:
    payload = dict(payload)
    payload["oos_signals"] = OOSSignals(**payload["oos_signals"])
    return LLMExtraction(**payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("fix", _load_fixtures(), ids=lambda f: f["case"])
async def test_parity(fix, krx, mock_openai_client, mock_supabase, monkeypatch, tmp_path):
    # Stub PDF on disk — extract_pdf reads STORAGE_BASE_DIR/<file_path>.
    # Use the built-in 'korea' CJK font so Hangul roundtrips through PyMuPDF.
    pdf = tmp_path / fix["input"]["file_name"]
    doc = fitz.open()
    doc.new_page().insert_text(
        (72, 72), fix["input"]["pdf_text"], fontname="korea", fontsize=11
    )
    doc.save(pdf)
    doc.close()
    monkeypatch.setenv("STORAGE_BASE_DIR", str(tmp_path))

    mock_openai_client.set_response(_make_llm_mock(fix["llm_mock"]))

    app = build_graph(
        mock_openai_client, mock_supabase, krx=krx,
        dry_run=False, taxonomy_version="KRX@parity-test",
    )
    init = {
        "id": 1,
        "file_path": fix["input"]["file_name"],
        "file_name": fix["input"]["file_name"],
        "sent_at": datetime.fromisoformat(fix["input"]["sent_at"]),
        "caption": fix["input"]["caption"],
        "chat_username": "x",
        "worker_id": "parity",
        "model": "gpt-5.4-mini",
    }
    await app.ainvoke(init)

    # Inspect the recorded UPDATE payload
    assert len(mock_supabase.executed) == 1
    sql, args = mock_supabase.executed[0]
    assert sql == UPDATE_SQL

    # Map UPDATE bind args to dict for readable assertions
    columns = [
        "id", "published_at", "report_type", "publisher", "publisher_type",
        "analysts", "title", "stock_codes", "company_names",
        "sectors_major", "sectors_minor", "products", "topics",
        "out_of_scope_reason", "tagging_status", "tagging_confidence",
        "tagging_notes", "taxonomy_version",
    ]
    actual = dict(zip(columns, args))

    expected = fix["expected"]
    for k, v in expected.items():
        if k.endswith("_contains"):
            base = k[: -len("_contains")]
            for item in v:
                assert item in actual[base], (
                    f"{base} missing {item} (got {actual[base]})"
                )
        else:
            assert actual[k] == v, f"{k}: expected {v!r}, got {actual[k]!r}"
