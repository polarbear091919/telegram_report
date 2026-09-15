"""Manual review actions with server-owned undo snapshots."""
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException

from langgraph_tagger.review_viewer.actions import (
    build_oos_payload, build_pending_reset_payload, build_verified_payload,
    capture_snapshot,
)
from langgraph_tagger.review_viewer.db import ReviewDB


class ReviewService:
    def __init__(self, sb):
        self.sb = sb
        self.db = ReviewDB(sb)
        self.lock = Lock()
        self.undo_records = {}

    def queue(self, skipped):
        row = self.db.fetch_next_review(skipped)
        if row:
            row = {k: v for k, v in row.items() if k not in ('file_path', 'file_hash')}
            row['pdf_url'] = f"/api/review/{row['id']}/pdf"
        return {'remaining': self.db.count_review_queue(), 'report': row}

    def row(self, rid):
        rows = self.sb.table('reports').select('*').eq('id', rid).execute().data
        if not rows:
            raise HTTPException(404, '검토할 보고서가 없습니다.')
        return rows[0]

    def act(self, rid, action, reason=None):
        with self.lock:
            row = self.row(rid)
            if row['tagging_status'] != 'review_needed':
                raise HTTPException(409, '다른 작업에서 처리한 보고서입니다. 목록을 새로고침해 주세요.')
            if action == 'verify':
                payload = build_verified_payload(row)
            elif action == 'oos':
                payload = build_oos_payload(row, reason)
            else:
                payload = build_pending_reset_payload()
            result = (self.sb.table('reports').update(payload).eq('id', rid)
                      .eq('tagging_status', 'review_needed').execute())
            if not result.data:
                raise HTTPException(409, '보고서 상태가 바뀌었습니다. 새로고침해 주세요.')
            token = uuid4().hex
            self.undo_records[token] = {'id': rid, 'snapshot': capture_snapshot(row),
                                        'after': capture_snapshot(result.data[0])}
            # Keep a small session history; no report content comes from the browser on undo.
            if len(self.undo_records) > 100:
                self.undo_records.pop(next(iter(self.undo_records)))
            return {'undo_token': token, 'report_id': rid}

    def undo(self, token):
        with self.lock:
            saved = self.undo_records.get(token)
            if not saved:
                raise HTTPException(409, '되돌릴 작업이 없거나 서버가 재시작되었습니다.')
            current = self.row(saved['id'])
            if capture_snapshot(current) != saved['after']:
                raise HTTPException(409, '후속 작업이 처리한 보고서라 되돌릴 수 없습니다.')
            query = self.sb.table('reports').update(saved['snapshot']).eq('id', saved['id'])
            # Compare-and-set avoids overwriting a tagger that acquired a pending row.
            for key in ('tagging_status', 'tagged_at', 'tagging_locked_at', 'tagging_worker_id'):
                value = saved['after'].get(key)
                query = query.is_(key, 'null') if value is None else query.eq(key, value)
            if not query.execute().data:
                raise HTTPException(409, '후속 작업이 시작되어 되돌릴 수 없습니다.')
            self.undo_records.pop(token)
            return {'report_id': saved['id']}
