from pathlib import Path

import pytest

from langgraph_tagger.analytics.config import AnalyticsConfig, load_analytics_config


def test_load_happy_path(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'eyJtest')
    monkeypatch.setenv('STORAGE_BASE_DIR', '/tmp/reports')
    monkeypatch.setenv('KRX_CSV_PATH', 'docs/stock_data/KRX_stocks_data.csv')

    cfg = load_analytics_config()

    assert isinstance(cfg, AnalyticsConfig)
    assert cfg.supabase_url == 'https://test.supabase.co'
    assert cfg.supabase_service_key == 'eyJtest'
    assert cfg.storage_base_dir == Path('/tmp/reports')
    assert cfg.krx_csv_path == Path('docs/stock_data/KRX_stocks_data.csv')


def test_load_defaults(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    for k in ('STORAGE_BASE_DIR', 'KRX_CSV_PATH'):
        monkeypatch.delenv(k, raising=False)

    cfg = load_analytics_config()
    assert cfg.storage_base_dir == Path('./reports')
    assert cfg.krx_csv_path == Path('docs/stock_data/KRX_stocks_data.csv')


def test_missing_supabase_url_exits(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    with pytest.raises(SystemExit) as e:
        load_analytics_config()
    assert 'SUPABASE_URL' in str(e.value)


def test_missing_supabase_key_exits(monkeypatch):
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.delenv('SUPABASE_SERVICE_KEY', raising=False)
    with pytest.raises(SystemExit) as e:
        load_analytics_config()
    assert 'SUPABASE_SERVICE_KEY' in str(e.value)


def test_does_not_require_openai_or_telegram(monkeypatch):
    """Analytics must run without OPENAI_API_KEY / TELEGRAM_* / SUPABASE_DB_URL."""
    monkeypatch.setattr('langgraph_tagger.analytics.config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    for k in ('OPENAI_API_KEY', 'TELEGRAM_API_ID', 'TELEGRAM_API_HASH',
              'TELEGRAM_CHANNEL', 'SUPABASE_DB_URL'):
        monkeypatch.delenv(k, raising=False)
    cfg = load_analytics_config()
    assert cfg.supabase_url == 'u'
