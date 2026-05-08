"""CLI: ``python -m langgraph_tagger run|inspect|escalate``."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
from datetime import datetime, timezone

from openai import AsyncOpenAI

from langgraph_tagger.config import load_config
from langgraph_tagger.orchestrator import run_batch
from langgraph_tagger.supabase_io import (
    ESCALATION_PICK_SQL, INSPECT_SUMMARY_SQL, SupabaseSQL,
)
from langgraph_tagger.vocabulary.krx import KRXIndex


def _make_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(2)}"


def _parse_row_ids(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x.strip()]


async def _cmd_run(args, cfg):
    sb = await SupabaseSQL.from_env()
    client = AsyncOpenAI(api_key=cfg.openai_api_key, max_retries=2, timeout=60.0)
    krx = KRXIndex.load(cfg.krx_csv_path)
    try:
        report = await run_batch(
            sb=sb, client=client, krx=krx,
            taxonomy_version=krx.taxonomy_version,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            row_ids=_parse_row_ids(args.row_ids) if args.row_ids else [],
            model=args.model or cfg.model_default,
            max_concurrent_llm=args.max_concurrent_llm or cfg.max_concurrent_llm,
            worker_id=_make_worker_id(),
            lock_ttl_minutes=cfg.lock_ttl_minutes,
            per_row_deadline_s=cfg.per_row_deadline_s,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    finally:
        await sb.close()
        await client.close()


async def _cmd_inspect(args, cfg):
    sb = await SupabaseSQL.from_env()
    try:
        rows = await sb.fetch(INSPECT_SUMMARY_SQL)
        print(json.dumps(rows[0] if rows else {}, indent=2, ensure_ascii=False, default=str))
    finally:
        await sb.close()


async def _cmd_escalate(args, cfg):
    sb = await SupabaseSQL.from_env()
    client = AsyncOpenAI(api_key=cfg.openai_api_key, max_retries=2, timeout=60.0)
    krx = KRXIndex.load(cfg.krx_csv_path)
    try:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        rows = await sb.fetch(ESCALATION_PICK_SQL, [since])
        ids = [r["id"] for r in rows]
        if not ids:
            print(json.dumps({"escalated": 0, "since": args.since}))
            return
        report = await run_batch(
            sb=sb, client=client, krx=krx,
            taxonomy_version=krx.taxonomy_version,
            batch_size=len(ids),
            dry_run=False,
            row_ids=ids,
            model=args.model or cfg.model_escalation,
            max_concurrent_llm=args.max_concurrent_llm or cfg.max_concurrent_llm,
            worker_id=_make_worker_id(),
            lock_ttl_minutes=cfg.lock_ttl_minutes,
            per_row_deadline_s=cfg.per_row_deadline_s,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    finally:
        await sb.close()
        await client.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="langgraph_tagger")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="claim + tag a batch of pending rows")
    p_run.add_argument("--batch-size", type=int, default=None)
    p_run.add_argument("--model", type=str, default=None)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--row-ids", type=str, default=None,
                       help="comma-separated ids; skips atomic claim")
    p_run.add_argument("--max-concurrent-llm", type=int, default=None)

    sub.add_parser("inspect", help="print queue distribution")

    p_esc = sub.add_parser("escalate", help="re-tag rows in review_needed since a timestamp")
    p_esc.add_argument("--since", type=str, required=True,
                       help="ISO timestamp, e.g. 2026-05-08T09:00")
    p_esc.add_argument("--model", type=str, default=None)
    p_esc.add_argument("--max-concurrent-llm", type=int, default=None)

    args = p.parse_args(argv)
    cfg = load_config()
    args.batch_size = getattr(args, "batch_size", None) or cfg.batch_size_default

    if args.cmd == "run":
        asyncio.run(_cmd_run(args, cfg))
    elif args.cmd == "inspect":
        asyncio.run(_cmd_inspect(args, cfg))
    elif args.cmd == "escalate":
        asyncio.run(_cmd_escalate(args, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
