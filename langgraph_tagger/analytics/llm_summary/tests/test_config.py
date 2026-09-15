from langgraph_tagger.analytics.llm_summary.config import (
    LLMSummaryConfig, load_llm_summary_config, require_openai_key,
)
import pytest


def test_load_happy_path(monkeypatch):
    monkeypatch.setattr(
        'langgraph_tagger.analytics.llm_summary.config.load_dotenv',
        lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_DB_URL', 'postgres://x')
    for k in ('OPENAI_MODEL_PHASE2', 'PHASE2_MAX_CONCURRENT',
              'PHASE2_PER_REPORT_TIMEOUT_S', 'PHASE2_MAX_INPUT_TOKENS',
              'PHASE2_SUMMARY_VERSION', 'OPENAI_API_KEY'):
        monkeypatch.delenv(k, raising=False)

    cfg = load_llm_summary_config()

    assert isinstance(cfg, LLMSummaryConfig)
    assert cfg.openai_model == 'gpt-5.6-luna'
    assert cfg.max_concurrent == 2
    assert cfg.per_report_timeout_s == 90
    assert cfg.max_input_tokens == 30000
    assert cfg.summary_version == 'llm-summary@1.0'
    assert cfg.supabase_db_url == 'postgres://x'
    assert cfg.openai_api_key is None  # lazy: load 시점엔 안 채움


def test_load_overrides(monkeypatch):
    monkeypatch.setattr(
        'langgraph_tagger.analytics.llm_summary.config.load_dotenv',
        lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_DB_URL', 'postgres://x')
    monkeypatch.setenv('OPENAI_MODEL_PHASE2', 'gpt-5.4')
    monkeypatch.setenv('PHASE2_MAX_CONCURRENT', '3')
    monkeypatch.setenv('PHASE2_MAX_INPUT_TOKENS', '15000')
    monkeypatch.setenv('PHASE2_SUMMARY_VERSION', 'llm-summary@2.0')

    cfg = load_llm_summary_config()
    assert cfg.openai_model == 'gpt-5.4'
    assert cfg.max_concurrent == 3
    assert cfg.max_input_tokens == 15000
    assert cfg.summary_version == 'llm-summary@2.0'


def test_missing_db_url_exits(monkeypatch):
    monkeypatch.setattr(
        'langgraph_tagger.analytics.llm_summary.config.load_dotenv',
        lambda *a, **k: False)
    monkeypatch.delenv('SUPABASE_DB_URL', raising=False)
    with pytest.raises(SystemExit) as e:
        load_llm_summary_config()
    assert 'SUPABASE_DB_URL' in str(e.value)


def test_require_openai_key_lazy_success(monkeypatch):
    """load_config 시점이 아닌 require_openai_key() 시점에 검증."""
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    cfg = LLMSummaryConfig(
        openai_model='m', max_concurrent=2, per_report_timeout_s=90,
        max_input_tokens=30000, summary_version='v', supabase_db_url='u',
        openai_api_key=None,
    )
    key = require_openai_key(cfg)
    assert key == 'sk-test'


def test_require_openai_key_missing_raises(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    cfg = LLMSummaryConfig(
        openai_model='m', max_concurrent=2, per_report_timeout_s=90,
        max_input_tokens=30000, summary_version='v', supabase_db_url='u',
        openai_api_key=None,
    )
    with pytest.raises(RuntimeError) as e:
        require_openai_key(cfg)
    assert 'OPENAI_API_KEY' in str(e.value)
