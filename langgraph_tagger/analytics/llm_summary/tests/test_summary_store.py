from unittest.mock import MagicMock

import pytest

from langgraph_tagger.analytics.llm_summary import summary_store as store


class FakeQuery:
    """Chainable supabase-py REST query mock."""
    def __init__(self, response_data):
        self._response_data = response_data
        self.calls = []
    def select(self, cols):
        self.calls.append(('select', cols)); return self
    def in_(self, col, vals):
        self.calls.append(('in_', col, list(vals))); return self
    def eq(self, col, val):
        self.calls.append(('eq', col, val)); return self
    def update(self, payload):
        self.calls.append(('update', payload)); return self
    def upsert(self, payload, on_conflict=None):
        self.calls.append(('upsert', payload, on_conflict)); return self
    def execute(self):
        resp = MagicMock()
        resp.data = self._response_data
        return resp


class FakeSupabase:
    def __init__(self, response_data=None):
        self.last_query = None
        self._response_data = response_data or []
    def table(self, name):
        self.last_query = FakeQuery(self._response_data)
        return self.last_query


def test_fetch_summaries_filters_active_version():
    rows = [{'report_id': 1, 'summary_version': 'llm-summary@1.0'}]
    sb = FakeSupabase(rows)
    out = store.fetch_summaries(sb, [1, 2, 3], active_version='llm-summary@1.0')
    assert isinstance(out, dict)
    assert 1 in out
    calls = sb.last_query.calls
    assert ('in_', 'report_id', [1, 2, 3]) in calls
    assert ('eq', 'summary_version', 'llm-summary@1.0') in calls


def test_upsert_summary_includes_null_diff_fields():
    """diff reset 의무: payload엔 항상 prev_*, diff_narrative NULL 포함."""
    sb = FakeSupabase()
    store.upsert_summary(sb, {
        'report_id': 1,
        'target_price_new': 85000, 'target_price_old': 70000,
        'target_price_dir': '상향', 'recommendation': '매수',
        'recommendation_dir': '유지',
        'one_line_summary': 'X', 'positive_points': [], 'risk_points': [],
        'target_price_raw': '8.5만원', 'recommendation_raw': 'Buy',
        'source_pages': [1], 'extraction_confidence': 'high',
        'input_truncated': False, 'input_pages_used': 5, 'input_total_pages': 5,
        'summary_version': 'llm-summary@1.0', 'llm_model': 'gpt-5.4-mini',
        'llm_tokens_input': 1000, 'llm_tokens_output': 200,
        'prev_report_id': None,
        'prev_match_type': None,
        'diff_narrative': None,
    })
    upsert_call = [c for c in sb.last_query.calls if c[0] == 'upsert'][0]
    payload = upsert_call[1]
    assert payload['prev_report_id'] is None
    assert payload['prev_match_type'] is None
    assert payload['diff_narrative'] is None
    assert upsert_call[2] == 'report_id'  # on_conflict


def test_update_diff_sets_match_and_narrative():
    sb = FakeSupabase()
    store.update_diff(
        sb, report_id=42, prev_report_id=10,
        match_type='same_publisher', narrative='이전 대비 ...',
    )
    update_call = [c for c in sb.last_query.calls if c[0] == 'update'][0]
    payload = update_call[1]
    assert payload['prev_report_id'] == 10
    assert payload['prev_match_type'] == 'same_publisher'
    assert payload['diff_narrative'].startswith('이전')


def test_update_diff_marks_none_when_no_prev():
    sb = FakeSupabase()
    store.update_diff(
        sb, report_id=42, prev_report_id=None,
        match_type='none', narrative=None,
    )
    update_call = [c for c in sb.last_query.calls if c[0] == 'update'][0]
    payload = update_call[1]
    assert payload['prev_report_id'] is None
    assert payload['prev_match_type'] == 'none'
    assert payload['diff_narrative'] is None


# -- asyncpg cascade tests ----------------------------------------------------

class FakeRecord(dict):
    """asyncpg.Record-like dict."""


class FakeConn:
    def __init__(self, fetchrow_result=None):
        self.fetchrow_result = fetchrow_result
        self.queries = []
    async def fetchrow(self, sql, *args):
        self.queries.append((sql, args))
        return self.fetchrow_result


class FakePool:
    def __init__(self, fetchrow_result=None):
        self.conn = FakeConn(fetchrow_result)
    def acquire(self):
        outer = self
        class _Ctx:
            async def __aenter__(self_): return outer.conn
            async def __aexit__(self_, *a): return False
        return _Ctx()


@pytest.mark.asyncio
async def test_find_prev_same_publisher_hit():
    record = FakeRecord({
        'prev_report_id': 10, 'prev_publisher': '삼성증권',
        'prev_published_at': '2026-03-15', 'is_same_pub': True,
        'target_price_new': 70000, 'target_price_old': None,
        'target_price_dir': '신규', 'recommendation': '매수',
        'recommendation_dir': '신규', 'one_line_summary': '이전 view',
        'positive_points': [], 'risk_points': [],
        'target_price_raw': '7만원', 'recommendation_raw': 'Buy',
        'match_type': 'same_publisher',
    })
    pool = FakePool(fetchrow_result=record)
    r = await store.find_prev_for_diff(
        pool, stock_code='005930', publisher='삼성증권',
        current_published_at='2026-05-05', active_version='llm-summary@1.0',
    )
    assert r is not None
    assert r.prev_report_id == 10
    assert r.match_type == 'same_publisher'
    assert r.summary['target_price_new'] == 70000


@pytest.mark.asyncio
async def test_find_prev_none():
    pool = FakePool(fetchrow_result=None)
    r = await store.find_prev_for_diff(
        pool, stock_code='005930', publisher='X',
        current_published_at='2026-05-05', active_version='llm-summary@1.0',
    )
    assert r is None


@pytest.mark.asyncio
async def test_find_prev_passes_correct_sql_args():
    pool = FakePool(fetchrow_result=None)
    await store.find_prev_for_diff(
        pool, stock_code='005930', publisher='삼성증권',
        current_published_at='2026-05-05', active_version='llm-summary@1.0',
    )
    sql, args = pool.conn.queries[0]
    assert '005930' in args
    assert '삼성증권' in args
    assert '2026-05-05' in args
    assert 'llm-summary@1.0' in args
    assert 'INNER JOIN report_summaries' in sql
    assert 'r.published_at < ' in sql  # 같은 날짜 제외
