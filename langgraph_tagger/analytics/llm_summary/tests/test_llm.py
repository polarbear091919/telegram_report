import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from langgraph_tagger.analytics.llm_summary.llm import (
    extract_one, diff_one, TransientLLMError,
)
from langgraph_tagger.analytics.llm_summary.schemas import (
    ExtractionResult, DiffResult,
)


def _fake_openai_response(parsed_obj):
    msg = MagicMock()
    msg.parsed = parsed_obj
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    usage = MagicMock()
    usage.prompt_tokens = 1000
    usage.completion_tokens = 200
    resp.usage = usage
    return resp


def _valid_extraction_obj():
    return ExtractionResult(
        target_price_new=85000, target_price_old=70000,
        target_price_dir='상향', recommendation='매수',
        recommendation_dir='유지',
        one_line_summary='메모리 가격 반등으로 25년 영업이익 ...',
        positive_points=['포인트 1', '포인트 2'],
        risk_points=['리스크 1'],
        target_price_raw='8.5만원', recommendation_raw='Buy',
        source_pages=[1], extraction_confidence='high',
    )


@pytest.mark.asyncio
async def test_extract_one_happy_path():
    fake = AsyncMock()
    fake.beta.chat.completions.parse = AsyncMock(
        return_value=_fake_openai_response(_valid_extraction_obj())
    )
    r, tokens_in, tokens_out = await extract_one(
        client=fake, model='gpt-5.4-mini',
        metadata={'publisher': 'X'}, pages_text='--- Page 1 ---\nbody',
        timeout_s=10,
    )
    assert isinstance(r, ExtractionResult)
    assert r.target_price_new == 85000
    assert tokens_in == 1000
    assert tokens_out == 200


@pytest.mark.asyncio
async def test_extract_one_retry_on_transient():
    """첫 호출 transient fail, 두 번째는 성공 → 결과 반환."""
    call_count = {'n': 0}
    async def flaky_parse(**kwargs):
        call_count['n'] += 1
        if call_count['n'] == 1:
            raise TransientLLMError("rate limit")
        return _fake_openai_response(_valid_extraction_obj())
    fake = AsyncMock()
    fake.beta.chat.completions.parse = flaky_parse
    r, _, _ = await extract_one(
        client=fake, model='gpt-5.4-mini',
        metadata={}, pages_text='', timeout_s=10, backoff_s=0,  # 빠른 테스트
    )
    assert isinstance(r, ExtractionResult)
    assert call_count['n'] == 2


@pytest.mark.asyncio
async def test_extract_one_permanent_fail_raises():
    """재시도 1회 후도 fail → TransientLLMError 그대로 raise."""
    async def always_fail(**kwargs):
        raise TransientLLMError("persistent")
    fake = AsyncMock()
    fake.beta.chat.completions.parse = always_fail
    with pytest.raises(TransientLLMError):
        await extract_one(
            client=fake, model='gpt-5.4-mini',
            metadata={}, pages_text='', timeout_s=10, backoff_s=0,
        )


@pytest.mark.asyncio
async def test_extract_one_retries_on_wait_for_timeout():
    """asyncio.wait_for timeout이 transient로 분류되어 재시도."""
    call_count = {'n': 0}
    async def slow_then_succeeds(**kwargs):
        call_count['n'] += 1
        if call_count['n'] == 1:
            # Simulate a hang that wait_for would catch
            await asyncio.sleep(0.05)  # > timeout_s=0.01
            return _fake_openai_response(_valid_extraction_obj())
        return _fake_openai_response(_valid_extraction_obj())
    fake = AsyncMock()
    fake.beta.chat.completions.parse = slow_then_succeeds
    r, _, _ = await extract_one(
        client=fake, model='gpt-5.4-mini',
        metadata={}, pages_text='',
        timeout_s=0.01,  # First call exceeds; second is instant after sleep ended
        backoff_s=0,
    )
    assert isinstance(r, ExtractionResult)
    assert call_count['n'] == 2  # retried


@pytest.mark.asyncio
async def test_diff_one_happy_path():
    fake = AsyncMock()
    fake.beta.chat.completions.parse = AsyncMock(
        return_value=_fake_openai_response(
            DiffResult(diff_narrative='이전 리포트 대비 ...')
        )
    )
    r, _, _ = await diff_one(
        client=fake, model='gpt-5.4-mini',
        prev_summary={}, curr_summary={},
        prev_match_type='same_publisher', prev_report_id=1,
        prev_publisher='X', curr_publisher='X', timeout_s=10,
    )
    assert isinstance(r, DiffResult)
    assert r.diff_narrative.startswith('이전')


@pytest.mark.asyncio
async def test_diff_one_returns_null_narrative():
    fake = AsyncMock()
    fake.beta.chat.completions.parse = AsyncMock(
        return_value=_fake_openai_response(DiffResult(diff_narrative=None))
    )
    r, _, _ = await diff_one(
        client=fake, model='gpt-5.4-mini',
        prev_summary={}, curr_summary={},
        prev_match_type='cross_publisher', prev_report_id=1,
        prev_publisher='', curr_publisher='', timeout_s=10,
    )
    assert r.diff_narrative is None
