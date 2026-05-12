"""PDF I/O for the review viewer.

- resolve_path: turn (storage_base_dir, file_path) into an absolute Path
- render_pages: render the first N pages as PNG bytes via PyMuPDF
- open_locally: hand the file to the OS default viewer (Windows/macOS/Linux)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pymupdf


def resolve_path(storage_base_dir: Path, file_path: str) -> Path:
    """Combine storage base + relative file_path. Absolute file_path wins.

    Does NOT check existence — caller decides how to render a missing-file
    placeholder.
    """
    p = Path(file_path)
    if p.is_absolute():
        return p
    return Path(storage_base_dir) / p


def render_pages(pdf_path: Path, n: int = 3, dpi: int = 120) -> list[bytes]:
    """Render the first n pages of pdf_path to PNG bytes via PyMuPDF.

    Caps at the actual page count when the document has fewer pages.
    Raises FileNotFoundError if pdf_path does not exist.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))
    doc = pymupdf.open(str(pdf_path))
    try:
        out: list[bytes] = []
        zoom = dpi / 72  # PyMuPDF default is 72 DPI
        matrix = pymupdf.Matrix(zoom, zoom)
        for i in range(min(n, doc.page_count)):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out.append(pix.tobytes('png'))
        return out
    finally:
        doc.close()


def open_locally(pdf_path: Path) -> None:
    """Open pdf_path in the OS default PDF viewer.

    Server-side dispatch avoids the http->file:// browser block.
    Does not raise if the path is missing; the OS viewer will silently
    no-op (Windows os.startfile) or surface to the user (subprocess
    open/xdg-open with check=False).
    """
    path_str = str(pdf_path)
    if sys.platform == 'win32':
        os.startfile(path_str)   # type: ignore[attr-defined]
    elif sys.platform == 'darwin':
        subprocess.run(['open', path_str], check=False)
    else:
        subprocess.run(['xdg-open', path_str], check=False)
