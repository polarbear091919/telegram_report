from pathlib import Path

import pytest

from config import Config, load_config


def test_load_config_happy_path(monkeypatch):
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'abcdef0123456789')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'sunstudy1004')
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'eyJtest')
    # Don't set optional vars — they should pick up defaults

    cfg = load_config()

    assert isinstance(cfg, Config)
    assert cfg.telegram_api_id == 12345
    assert cfg.telegram_api_hash == 'abcdef0123456789'
    assert cfg.telegram_channel == 'sunstudy1004'
    assert cfg.supabase_url == 'https://test.supabase.co'
    assert cfg.supabase_service_key == 'eyJtest'
    # Defaults
    assert cfg.telegram_session_path == Path('sessions') / 'samstudy'
    assert cfg.storage_base_dir == Path('./reports')
    assert cfg.initial_cutoff_days == 30
    assert cfg.max_concurrent_downloads == 4
    assert cfg.log_level == 'INFO'


def test_load_config_missing_required_var_exits(monkeypatch):
    # Suppress load_dotenv() so a real .env in the project root doesn't
    # repopulate the env vars we just deleted.
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)

    # Only set some of the required vars
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.delenv('TELEGRAM_API_HASH', raising=False)
    monkeypatch.delenv('TELEGRAM_CHANNEL', raising=False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_KEY', raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_config()
    # Message should mention which key is missing
    assert 'TELEGRAM_API_HASH' in str(exc_info.value)


def test_load_config_optional_overrides(monkeypatch):
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'c')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.setenv('TELEGRAM_SESSION_NAME', 'mysess')
    monkeypatch.setenv('STORAGE_BASE_DIR', '/tmp/my_reports')
    monkeypatch.setenv('INITIAL_CUTOFF_DAYS', '7')
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')

    cfg = load_config()

    assert cfg.telegram_session_path == Path('sessions') / 'mysess'
    assert cfg.storage_base_dir == Path('/tmp/my_reports')
    assert cfg.initial_cutoff_days == 7
    assert cfg.log_level == 'DEBUG'


def test_load_config_max_concurrent_downloads_default(monkeypatch):
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'c')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.delenv('MAX_CONCURRENT_DOWNLOADS', raising=False)

    cfg = load_config()

    assert cfg.max_concurrent_downloads == 4


def test_load_config_max_concurrent_downloads_override(monkeypatch):
    monkeypatch.setattr('config.load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('TELEGRAM_API_ID', '12345')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'h')
    monkeypatch.setenv('TELEGRAM_CHANNEL', 'c')
    monkeypatch.setenv('SUPABASE_URL', 'u')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'k')
    monkeypatch.setenv('MAX_CONCURRENT_DOWNLOADS', '8')

    cfg = load_config()

    assert cfg.max_concurrent_downloads == 8
