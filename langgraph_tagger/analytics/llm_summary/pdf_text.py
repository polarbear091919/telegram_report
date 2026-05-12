"""PDF 텍스트 추출 (PyMuPDF) — 전체 페이지 + token cap truncation."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PDFTextResult:
    text: str                     # page-numbered concat
    pages_used: int               # 실제 추출에 포함된 페이지 수
    total_pages: int              # 원본 PDF의 총 페이지 수
    input_truncated: bool         # max_tokens cap에 걸려 잘렸나
    estimated_input_tokens: int   # 추출된 text의 token 추정


def _estimate_tokens(text: str) -> int:
    """대략 1 token ≈ 3 chars (한국어 mixed text 가정). overcount는 안전 방향."""
    return max(1, len(text) // 3)


def extract_all_pages(path: Path, max_tokens: int) -> PDFTextResult:
    """PDF를 페이지별로 추출 + page-numbered concat. cap 넘으면 truncate.

    파일 부재·읽기 실패는 빈 결과 반환 (pipeline이 PDF 실패로 처리).
    """
    if not path.exists():
        logger.warning("PDF not found: %s", path)
        return PDFTextResult('', 0, 0, False, 0)

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        logger.warning("PDF open failed: %s — %s", path, e)
        return PDFTextResult('', 0, 0, False, 0)

    total = doc.page_count
    parts: list[str] = []
    cumulative = 0
    pages_used = 0
    truncated = False

    for i in range(total):
        page = doc.load_page(i)
        body = page.get_text() or ''
        chunk = f"--- Page {i + 1} ---\n{body}\n"
        chunk_tokens = _estimate_tokens(chunk)

        if cumulative + chunk_tokens > max_tokens:
            truncated = True
            logger.warning(
                "PDF truncated at page %d/%d (cap=%d tokens, used=%d): %s",
                i, total, max_tokens, cumulative, path.name,
            )
            break

        parts.append(chunk)
        cumulative += chunk_tokens
        pages_used += 1

    doc.close()
    text = ''.join(parts)
    return PDFTextResult(
        text=text,
        pages_used=pages_used,
        total_pages=total,
        input_truncated=truncated,
        estimated_input_tokens=cumulative,
    )
