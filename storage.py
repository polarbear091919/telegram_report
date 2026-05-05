"""Storage layer: Supabase metadata + local PDF filesystem.

This module also exports two pure helpers:
- sanitize_filename: make a Telegram-supplied name safe for the filesystem.
- compute_sha256: chunked file hash for integrity tracking.

The Storage class (Supabase + filesystem operations) is added in later tasks.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Windows-forbidden filename chars + ASCII control chars (\x00–\x1f)
_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, max_len: int = 100) -> str:
    """Convert an arbitrary string into a safe filename.

    Rules (in order):
      1. Replace OS-forbidden chars with '_'
      2. Strip leading/trailing dots and spaces (Windows quirk)
      3. Ensure name is non-empty (fallback to 'unnamed')
      4. Ensure '.pdf' extension
      5. Truncate to max_len, preserving '.pdf' suffix
    """
    # 1. Remove forbidden chars
    name = _FORBIDDEN_CHARS.sub('_', name)
    # 2. Strip dots/spaces from edges
    name = name.strip('. ')
    # 3. Empty fallback
    if not name:
        name = 'unnamed'
    # 4. Ensure .pdf
    if not name.lower().endswith('.pdf'):
        name = name + '.pdf'
    # 5. Truncate (keep .pdf suffix)
    if len(name) > max_len:
        name = name[: max_len - 4] + '.pdf'
    return name


def compute_sha256(file_path: Path, chunk_size: int = 64 * 1024) -> str:
    """Compute SHA-256 of a file by streaming in chunks.

    Returns lowercase hex digest. Avoids loading the whole file into memory.
    """
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
