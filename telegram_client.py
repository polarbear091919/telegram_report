"""Telethon wrapper + pure PDF predicates.

Only the pure functions (`has_pdf`, `_get_original_filename`) are in this initial cut.
The async TelegramClient class is added in Task 8.
"""
from __future__ import annotations

from typing import Any


def has_pdf(msg: Any) -> bool:
    """Return True if the message has a PDF attachment.

    Strategy:
      1. If no document at all → False
      2. If document.mime_type == 'application/pdf' → True (most reliable)
      3. Else, scan attributes for any file_name ending in .pdf (case-insensitive)
      4. Else → False
    """
    if not getattr(msg, 'document', None):
        return False
    if msg.document.mime_type == 'application/pdf':
        return True
    for attr in getattr(msg.document, 'attributes', []):
        file_name = getattr(attr, 'file_name', None)
        if file_name and file_name.lower().endswith('.pdf'):
            return True
    return False


def _get_original_filename(msg: Any) -> str | None:
    """Extract the Telegram-original file_name attribute, or None."""
    if not getattr(msg, 'document', None):
        return None
    for attr in getattr(msg.document, 'attributes', []):
        file_name = getattr(attr, 'file_name', None)
        if file_name:
            return file_name
    return None
