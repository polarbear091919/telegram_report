from pathlib import Path

import pytest

from langgraph_tagger.review_viewer.config import ReviewViewerConfig, load_review_viewer_config


def test_load_happy_path(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'eyJtest')
    monkeypatch.setenv('STORAGE_BASE_DIR', '/tmp/reports')

    cfg = load_review_viewer_config()

    assert isinstance(cfg, ReviewViewerConfig)
    assert cfg.supabase_url == 'https://test.supabase.co'
    assert cfg.supabase_service_key == 'eyJtest'
    assert cfg.storage_base_dir == Path('/tmp/reports')


def test_load_storage_default(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.delenv('STORAGE_BASE_DIR', raising=False)

    cfg = load_review_viewer_config()
    assert cfg.storage_base_dir == Path('./reports')


def test_missing_supabase_url_exits(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')

    with pytest.raises(SystemExit) as exc_info:
        load_review_viewer_config()
    assert 'SUPABASE_URL' in str(exc_info.value)


def test_missing_supabase_key_exits(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.delenv('SUPABASE_SERVICE_KEY', raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_review_viewer_config()
    assert 'SUPABASE_SERVICE_KEY' in str(exc_info.value)


def test_does_not_require_openai_or_telegram_envs(monkeypatch):
    """Viewer must run without OPENAI_API_KEY / TELEGRAM_* — those belong to tagger / collector."""
    monkeypatch.setattr('langgraph_tagger.review_viewer.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    for k in ('OPENAI_API_KEY', 'TELEGRAM_API_ID', 'TELEGRAM_API_HASH',
              'TELEGRAM_CHANNEL', 'SUPABASE_DB_URL'):
        monkeypatch.delenv(k, raising=False)

    cfg = load_review_viewer_config()
    assert cfg.supabase_url == 'u'
