from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from langgraph_tagger.review_viewer.pdf import (
    resolve_path,
    render_pages,
    open_locally,
)


# === resolve_path ===

def test_resolve_path_joins_relative(tmp_path):
    storage = tmp_path
    (storage / 'foo.pdf').write_bytes(b'%PDF-1.4\n')
    result = resolve_path(storage, 'foo.pdf')
    assert result == storage / 'foo.pdf'
    assert result.is_file()


def test_resolve_path_absolute_in_file_path(tmp_path):
    """file_path can be absolute (legacy rows); resolve_path should respect it."""
    abs_path = tmp_path / 'abs.pdf'
    abs_path.write_bytes(b'%PDF-1.4\n')
    result = resolve_path(Path('/other/storage'), str(abs_path))
    assert result == abs_path


def test_resolve_path_missing_returns_path_anyway(tmp_path):
    """Caller (UI) decides how to render missing-file placeholder."""
    result = resolve_path(tmp_path, 'does_not_exist.pdf')
    assert result == tmp_path / 'does_not_exist.pdf'
    assert not result.exists()


# === render_pages ===

def test_render_pages_returns_n_png_bytes(sample_pdf_path):
    pages = render_pages(sample_pdf_path, n=1)
    assert len(pages) == 1
    assert pages[0][:8] == b'\x89PNG\r\n\x1a\n'   # PNG magic header


def test_render_pages_caps_at_doc_page_count(sample_pdf_path):
    """Asking for more pages than the PDF has should not raise."""
    pages = render_pages(sample_pdf_path, n=10)
    assert 1 <= len(pages) <= 10


def test_render_pages_dpi_changes_size(sample_pdf_path):
    low = render_pages(sample_pdf_path, n=1, dpi=72)
    high = render_pages(sample_pdf_path, n=1, dpi=200)
    assert len(high[0]) > len(low[0]), "Higher DPI should yield a larger PNG"


def test_render_pages_missing_file_raises(tmp_path):
    bad = tmp_path / 'nope.pdf'
    with pytest.raises(FileNotFoundError):
        render_pages(bad, n=1)


# === open_locally ===

@patch('langgraph_tagger.review_viewer.pdf.sys')
@patch('langgraph_tagger.review_viewer.pdf.os')
def test_open_locally_windows_uses_startfile(mock_os, mock_sys, tmp_path):
    pdf = tmp_path / 'a.pdf'
    pdf.write_bytes(b'%PDF-1.4\n')
    mock_sys.platform = 'win32'
    open_locally(pdf)
    mock_os.startfile.assert_called_once_with(str(pdf))


@patch('langgraph_tagger.review_viewer.pdf.subprocess')
@patch('langgraph_tagger.review_viewer.pdf.sys')
def test_open_locally_macos_uses_open(mock_sys, mock_subprocess, tmp_path):
    pdf = tmp_path / 'a.pdf'
    pdf.write_bytes(b'%PDF-1.4\n')
    mock_sys.platform = 'darwin'
    open_locally(pdf)
    mock_subprocess.run.assert_called_once_with(['open', str(pdf)], check=False)


@patch('langgraph_tagger.review_viewer.pdf.subprocess')
@patch('langgraph_tagger.review_viewer.pdf.sys')
def test_open_locally_linux_uses_xdg_open(mock_sys, mock_subprocess, tmp_path):
    pdf = tmp_path / 'a.pdf'
    pdf.write_bytes(b'%PDF-1.4\n')
    mock_sys.platform = 'linux'
    open_locally(pdf)
    mock_subprocess.run.assert_called_once_with(['xdg-open', str(pdf)], check=False)
