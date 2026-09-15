"""Same-origin API and production frontend for the local research desk."""
import logging
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse, Response
import pymupdf
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .service import WorkspaceService, comparison, resolve_pdf

app = FastAPI(title='Research Desk', docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


_service = None
_service_lock = Lock()


def get_service():
    global _service
    with _service_lock:
        if _service is None:
            _service = WorkspaceService()
        return _service


@app.middleware('http')
async def local_writes(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and urlparse(origin).netloc not in ('127.0.0.1:8520', 'localhost:8520', '127.0.0.1:5173', 'localhost:5173'):
            return JSONResponse({'detail': '허용되지 않은 요청입니다.'}, status_code=403)
    return await call_next(request)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logging.getLogger(__name__).exception('Workspace request failed', exc_info=exc)
    return JSONResponse({'detail': '데이터를 불러오거나 분석하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.'}, status_code=503)


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.get('/api/workspace')
def bootstrap(service=Depends(get_service)):
    return service.bootstrap()


@app.get('/api/stocks/{code}/reports')
def stock_reports(code: str, service=Depends(get_service)):
    return service.stock_reports(code)


@app.get('/api/reports/{rid}/pdf')
def pdf(rid: int, service=Depends(get_service)):
    return FileResponse(service.pdf(rid), media_type='application/pdf')


@app.get('/api/compare')
def compare(left: int, right: int, service=Depends(get_service)):
    return comparison(service.report(left), service.report(right))


@app.post('/api/reports/{rid}/analyze')
async def analyze(rid: int, service=Depends(get_service)):
    return await service.analyze(rid)


def period_start(days):
    return (datetime.now(ZoneInfo('Asia/Seoul')) - timedelta(days=days)).date().isoformat()


@app.get('/api/market')
def market(days: int = Query(36500, ge=1, le=36500),
           unit: Literal['D', 'W', 'M'] = 'W',
           level: Literal['sectors_major', 'sectors_minor', 'products'] = 'sectors_major',
           items: list[str] = Query(default=[]), include_oos: bool = False,
           service=Depends(get_service)):
    return service.market(period_start(days), level, items, unit, include_oos)


@app.get('/api/stocks/{code}/activity')
def activity(code: str, days: int = Query(36500, ge=1, le=36500),
             unit: Literal['D', 'W', 'M'] = 'W', service=Depends(get_service)):
    return service.activity(code, period_start(days), unit)


@app.get('/api/review')
def review(skipped: list[int] = Query(default=[]), service=Depends(get_service)):
    return service.review.queue(skipped)


@app.get('/api/review/{rid}/pdf')
def review_pdf(rid: int, service=Depends(get_service)):
    row = service.review.row(rid)
    return FileResponse(resolve_pdf(service.cfg.storage_base_dir, row['file_path']), media_type='application/pdf')


@app.get('/api/review/{rid}/preview')
def review_preview(rid: int, service=Depends(get_service)):
    row = service.review.row(rid)
    path = resolve_pdf(service.cfg.storage_base_dir, row['file_path'])
    with pymupdf.open(path) as doc:
        return {'page_count': doc.page_count, 'preview_pages': min(3, doc.page_count)}


@app.get('/api/review/{rid}/pages/{page}')
def review_page(rid: int, page: int, service=Depends(get_service)):
    if page < 1 or page > 3:
        raise HTTPException(404, '미리보기는 첫 3페이지까지 제공됩니다.')
    row = service.review.row(rid)
    path = resolve_pdf(service.cfg.storage_base_dir, row['file_path'])
    with pymupdf.open(path) as doc:
        if page > doc.page_count:
            raise HTTPException(404, '페이지가 없습니다.')
        png = doc[page - 1].get_pixmap(matrix=pymupdf.Matrix(120 / 72, 120 / 72), alpha=False).tobytes('png')
    return Response(png, media_type='image/png', headers={'Cache-Control': 'private, max-age=300'})


class ReviewAction(BaseModel):
    action: Literal['verify', 'oos', 'retag']
    reason: Literal['foreign', 'fund', 'digital', 'private', 'ir_self'] | None = None


@app.post('/api/review/{rid}/action')
def review_action(rid: int, body: ReviewAction, service=Depends(get_service)):
    if body.action == 'oos' and not body.reason:
        raise HTTPException(422, '분석 대상 제외 사유를 선택해 주세요.')
    result = service.review.act(rid, body.action, body.reason)
    service.coverage_cache.clear()
    return result


@app.post('/api/review/undo/{token}')
def review_undo(token: str, service=Depends(get_service)):
    result = service.review.undo(token)
    service.coverage_cache.clear()
    return result


class ComparisonBody(BaseModel):
    left: int
    right: int


@app.post('/api/compare/analyze')
async def comparison_analysis(body: ComparisonBody, service=Depends(get_service)):
    return await service.analyze_comparison(body.left, body.right)


class FavoriteBody(BaseModel):
    enabled: bool


@app.put('/api/favorites/{code}')
def favorite(code: str, body: FavoriteBody, service=Depends(get_service)):
    return service.set_favorite(code, body.enabled)


# workspace -> langgraph_tagger -> repository
DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if DIST.exists():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')


@app.get('/')
def index():
    if not (DIST / 'index.html').exists():
        raise HTTPException(503, '프론트엔드를 먼저 빌드해 주세요: cd frontend && npm run build')
    return FileResponse(DIST / 'index.html', headers={'Cache-Control': 'no-cache'})
