from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from langgraph_tagger.workspace.api import app, get_service
from langgraph_tagger.workspace.service import comparison, public_report, resolve_pdf


def report(rid, published, publisher='KB', code='016360', summary=None):
    return {'id': rid, 'published_at': published, 'publisher': publisher,
            'stock_codes': [code], 'summary': summary}


def test_comparison_orders_chronologically_and_uses_exact_narrative():
    old = report(1, '2026-02-09')
    new = report(2, '2026-05-11', summary={'prev_report_id': 1, 'diff_narrative': '실적 추정 상향'})
    result = comparison(new, old)
    assert result['left']['id'] == 1
    assert result['right']['id'] == 2
    assert result['same_publisher'] is True
    assert result['narrative'] == '실적 추정 상향'
    # A third report must not inherit an unrelated pair's saved narrative.
    other = report(3, '2026-03-01', publisher='NH')
    result = comparison(other, new)
    assert result['narrative'] is None
    assert result['same_publisher'] is False


@pytest.mark.parametrize('other', [report(1, '2026-02-09'), report(2, '2026-05-11', code='005930')])
def test_comparison_rejects_same_document_and_different_company(other):
    with pytest.raises(HTTPException) as exc:
        comparison(report(1, '2026-02-09'), other)
    assert exc.value.status_code == 422


def test_unknown_publishers_do_not_imply_same_desk():
    assert comparison(report(1, '2026-01-01', publisher=None), report(2, '2026-02-01', publisher=None))['same_publisher'] is False


def test_target_price_change_uses_selected_reports_not_embedded_previous_target():
    old = report(1, '2026-02-09', summary={'target_price_new': 123000})
    new = report(2, '2026-05-11', summary={'target_price_new': 165000, 'target_price_old': 133000})
    change = comparison(old, new)['target_price_change']
    assert change['delta'] == 42000
    assert change['change_pct'] == pytest.approx(34.14634146)
    assert comparison(old, report(3, '2026-05-12'))['target_price_change'] is None


def test_pdf_is_confined_to_storage(tmp_path):
    root = tmp_path / 'reports'
    root.mkdir()
    (root / 'good.pdf').write_bytes(b'%PDF-1.4')
    (tmp_path / 'outside.pdf').write_bytes(b'%PDF-1.4')
    assert resolve_pdf(root, 'good.pdf') == root / 'good.pdf'
    for path in ('../outside.pdf', str(tmp_path / 'outside.pdf'), '../.env', 'missing.pdf'):
        with pytest.raises(HTTPException) as exc:
            resolve_pdf(root, path)
        assert exc.value.status_code == 404


def test_browser_report_omits_internal_paths():
    row = report(4, '2026-05-11') | {'file_path': 'private/location.pdf', 'caption': 'internal metadata'}
    value = public_report(row, None)
    assert 'file_path' not in value and 'caption' not in value
    assert value['pdf_url'] == '/api/reports/4/pdf'


@pytest.fixture
def client():
    class Service:
        def report(self, rid):
            return report(rid, f'2026-0{rid}-01')

        def bootstrap(self):
            return {'stocks': [], 'favorites': []}

        def set_favorite(self, code, enabled):
            return {'favorites': [code] if enabled else []}

        async def analyze(self, rid):
            return self.report(rid) | {'summary': {'one_line_summary': '검증된 응답'}}

    app.dependency_overrides[get_service] = Service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_routes_and_explicit_analysis(client):
    assert client.get('/api/health').json() == {'status': 'ok'}
    assert client.get('/api/workspace').json() == {'stocks': [], 'favorites': []}
    result = client.get('/api/compare?left=2&right=1').json()
    assert result['left']['id'] == 1 and result['right']['id'] == 2
    assert client.get('/api/compare?left=1&right=1').status_code == 422
    assert client.post('/api/reports/1/analyze').json()['summary']['one_line_summary'] == '검증된 응답'


def test_cross_origin_writes_are_rejected(client):
    response = client.put('/api/favorites/016360', json={'enabled': True}, headers={'Origin': 'https://example.com'})
    assert response.status_code == 403
    response = client.put('/api/favorites/016360', json={'enabled': True}, headers={'Origin': 'http://127.0.0.1:8520'})
    assert response.json() == {'favorites': ['016360']}
