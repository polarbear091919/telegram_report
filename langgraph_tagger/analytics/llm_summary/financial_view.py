"""Financial research sections inside the existing summary card."""
from __future__ import annotations

import streamlit as st

from langgraph_tagger.analytics.llm_summary.financials import (
    has_financial_details, numeric_change,
)


def _number(value) -> str:
    return '—' if value is None else f'{value:,.4f}'.rstrip('0').rstrip('.')


def _sources(items: list[dict]) -> None:
    seen = set()
    with st.expander('원문 근거'):
        for item in items:
            evidence = item.get('evidence') or {}
            key = (evidence.get('page'), evidence.get('quote'))
            if key in seen or not key[1]:
                continue
            seen.add(key)
            st.caption(f"p.{key[0]} · {key[1]}")


def render_financial_details(summary: dict) -> None:
    if not has_financial_details(summary):
        st.caption('이 보고서는 기본 요약입니다. 상단에서 금융 정보 확장을 실행할 수 있습니다.')
        return

    details = summary['financial_details']
    outlook, valuation_tab, thesis_tab, comparison_tab = st.tabs([
        '실적 전망', '밸류에이션', '투자 논리·촉매', '보고서 비교',
    ])
    with outlook:
        if details.get('unsupported_numeric_values'):
            st.caption(f"원문 근거와 일치하지 않은 수치 {details['unsupported_numeric_values']}개는 표시에서 제외했습니다.")
        metrics = details.get('metrics') or []
        if not metrics:
            st.info('문서에서 구조화할 실적 수치를 찾지 못했습니다.')
        else:
            rows = []
            for m in metrics:
                change = numeric_change(m.get('previous_value'), m.get('value'),
                                        m['unit'], m['metric'])
                rows.append({
                    '지표': m['metric'], '대상기간': m.get('fiscal_period') or '미기재',
                    '현재': _number(m.get('value')),
                    '이전 추정': _number(m.get('previous_value')),
                    '단위': ' '.join(filter(None, [m.get('currency'), m['unit']])),
                    '문서 내 수정': change['change_label'],
                    '구분': m['value_type'],
                    '기준': f"{m['accounting_basis']} · {m['scenario']}",
                    '근거': f"p.{m['evidence']['page']}",
                })
            st.dataframe(rows, hide_index=True, width='stretch')
            st.caption('이전 추정은 이 문서에 명시된 동일 기간의 수정 전 값입니다. 전년 실적과 구분합니다.')
            _sources(metrics + [{'evidence': m.get('previous_evidence')} for m in metrics])

    with valuation_tab:
        valuation = details.get('valuation') or {}
        st.markdown(f"**평가방식: {valuation.get('method', '미기재')}**")
        if valuation.get('target_horizon'):
            st.caption(f"목표기간 · {valuation['target_horizon']}")
        if valuation.get('explanation'):
            st.write(valuation['explanation'])
        assumptions = valuation.get('assumptions') or []
        if assumptions:
            st.dataframe([{
                '가정': a['name'], '적용기간': a.get('fiscal_period') or '미기재',
                '이전': a.get('previous') or '—', '현재': a['current'],
                '근거': f"p.{a['evidence']['page']}",
            } for a in assumptions], hide_index=True, width='stretch')
        st.markdown('**목표주가 변경 이유**')
        drivers = valuation.get('change_drivers') or []
        for driver in drivers:
            st.write(f"• {driver['category']} — {driver['explanation']}")
        if not drivers:
            st.caption('변경 이유가 명시되지 않았거나 목표주가 변경이 없습니다.')
        rating = details.get('rating') or {}
        if rating.get('current_label'):
            st.markdown('**투자의견 원문**')
            st.write(f"{rating.get('previous_label') or '이전 미기재'} → {rating['current_label']}")
            if rating.get('definition'):
                st.caption(rating['definition'])
            if rating.get('horizon'):
                st.caption(f"평가기간 · {rating['horizon']}")
        _sources(assumptions + drivers + [rating])

    with thesis_tab:
        st.markdown('**투자 논리와 확인할 지표**')
        theses = details.get('theses') or []
        for thesis in theses:
            with st.container(border=True):
                st.markdown(f"**{thesis['claim']}**")
                st.caption(f"{thesis['support_type']} · p.{thesis['evidence']['page']}")
                st.write(thesis['mechanism'])
                st.write(f"확인할 지표: {thesis.get('monitoring_metric') or '문서에 미기재'}")
                condition = thesis.get('invalidation_condition')
                basis = thesis.get('invalidation_basis', '논리에서 도출')
                st.write(f"가설 재검토 조건: {condition or '미기재'}")
                if condition:
                    st.caption(f'조건의 근거 · {basis}')
        if not theses:
            st.caption('문서에서 확인된 투자 논리가 없습니다.')
        st.markdown('**촉매와 예상 시기**')
        catalysts = details.get('catalysts') or []
        for catalyst in catalysts:
            st.write(f"• {catalyst['event']} · {catalyst.get('expected_timing') or '시기 미기재'}")
            if catalyst.get('condition'):
                st.caption(f"조건: {catalyst['condition']}")
        if not catalysts:
            st.caption('구체적인 촉매가 명시되지 않았습니다.')
        _sources(theses + catalysts)

    with comparison_tab:
        comparison = summary.get('comparison_details') or {}
        match = summary.get('prev_match_type')
        label = '동일 발행처의 전망 변화' if match == 'same_publisher' else '다른 발행처와의 의견 차이'
        if match not in ('same_publisher', 'cross_publisher'):
            st.info('비교할 이전 분석 보고서가 없습니다.')
            return
        st.markdown(f'**{label}**')
        st.caption(f"비교 문서 #{summary.get('prev_report_id')} · "
                   f"{comparison.get('previous_publisher') or '발행처 미기재'} · "
                   f"{comparison.get('previous_published_at') or '날짜 미기재'}")
        if summary.get('diff_narrative'):
            st.write(summary['diff_narrative'])
        metrics = comparison.get('metrics') or []
        if metrics:
            st.dataframe([{
                '지표': m['metric'],
                '이전': _number(m['previous']), '현재': _number(m['current']),
                '차이': m['change_label'],
                '기간': m['fiscal_period'],
                '단위': ' '.join(filter(None, [m.get('currency'), m['unit']])),
                '기준': f"{m['accounting_basis']} · {m['value_type']} · {m['scenario']}",
            } for m in metrics], hide_index=True, width='stretch')
            _sources([{'evidence': m.get(key)} for m in metrics
                      for key in ('previous_evidence', 'current_evidence')])
        else:
            st.caption('동일 기간·단위·회계기준·시나리오로 비교할 전망 수치가 없습니다.')
        st.caption('저장된 이전 분석과 비교합니다. 타 발행처의 차이는 동일 애널리스트의 수정이나 시장 컨센서스가 아닙니다.')
