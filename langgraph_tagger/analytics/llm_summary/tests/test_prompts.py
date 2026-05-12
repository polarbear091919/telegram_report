from langgraph_tagger.analytics.llm_summary.prompts import (
    render_extraction_messages, render_diff_messages,
)


def test_extraction_includes_normalization_rules():
    msgs = render_extraction_messages(
        report_metadata={'publisher': '삼성증권', 'stock_codes': ['005930'],
                         'published_at': '2026-05-05', 'title': 'X'},
        pages_text='--- Page 1 ---\n본문 ...',
    )
    sys = ''.join(m['content'] for m in msgs if m['role'] == 'system')
    user = ''.join(m['content'] for m in msgs if m['role'] == 'user')
    # 핵심 룰들이 prompt에 들어가 있는지 sanity check
    assert 'target_price' in sys.lower() or '목표주가' in sys
    assert 'BUY' in sys or '매수' in sys  # recommendation mapping
    assert 'Trading Buy' in sys             # 한국 sell-side 표현 포함
    assert 'Outperform' in sys
    assert 'metadata' in sys.lower()         # trust metadata 한 줄
    assert '005930' in user                  # metadata가 user msg에
    assert '--- Page 1 ---' in user          # page-numbered text 포함


def test_extraction_traps_section():
    msgs = render_extraction_messages(
        report_metadata={}, pages_text='--- Page 1 ---\n')
    sys = ''.join(m['content'] for m in msgs if m['role'] == 'system')
    assert 'current price' in sys.lower() or '현재가' in sys
    assert 'market cap' in sys.lower() or '시가총액' in sys


def test_diff_same_publisher_framing():
    prev_summary = {'target_price_new': 70000, 'recommendation': '매수',
                    'one_line_summary': '이전 view', 'positive_points': [],
                    'risk_points': [], 'target_price_dir': '신규',
                    'recommendation_dir': '신규',
                    'target_price_raw': '7만원', 'recommendation_raw': 'Buy'}
    curr_summary = {'target_price_new': 85000, 'recommendation': '매수',
                    'one_line_summary': '현재 view', 'positive_points': [],
                    'risk_points': [], 'target_price_dir': '상향',
                    'recommendation_dir': '유지',
                    'target_price_raw': '8.5만원', 'recommendation_raw': 'Buy'}
    msgs = render_diff_messages(
        prev_summary, curr_summary, prev_match_type='same_publisher',
        prev_report_id=1, prev_publisher='삼성증권', curr_publisher='삼성증권',
    )
    sys = ''.join(m['content'] for m in msgs if m['role'] == 'system')
    assert 'same' in sys.lower() or '동일' in sys or '시계열' in sys


def test_diff_cross_publisher_framing():
    prev_summary = {'target_price_new': 70000, 'recommendation': '매수',
                    'one_line_summary': 'A view', 'positive_points': [],
                    'risk_points': [], 'target_price_dir': '신규',
                    'recommendation_dir': '신규',
                    'target_price_raw': '7만원', 'recommendation_raw': 'Buy'}
    curr_summary = {'target_price_new': 85000, 'recommendation': '매수',
                    'one_line_summary': 'B view', 'positive_points': [],
                    'risk_points': [], 'target_price_dir': '신규',
                    'recommendation_dir': '신규',
                    'target_price_raw': '8.5만원', 'recommendation_raw': 'Buy'}
    msgs = render_diff_messages(
        prev_summary, curr_summary, prev_match_type='cross_publisher',
        prev_report_id=2, prev_publisher='삼성증권', curr_publisher='미래에셋',
    )
    sys = ''.join(m['content'] for m in msgs if m['role'] == 'system')
    # cross-publisher 분기: revision 아니라 두 애널리스트 비교 framing
    assert 'revision' in sys.lower() or '비교' in sys or '다른' in sys
    assert '삼성증권' in sys or '미래에셋' in sys


def test_diff_defensive_null_guard():
    """prompt에 'no previous → null' 방어줄 유지."""
    msgs = render_diff_messages(
        prev_summary={}, curr_summary={},
        prev_match_type='same_publisher',
        prev_report_id=1, prev_publisher='', curr_publisher='',
    )
    sys = ''.join(m['content'] for m in msgs if m['role'] == 'system')
    assert 'null' in sys.lower() or 'no previous' in sys.lower()
