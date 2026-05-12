import pandas as pd
import plotly.graph_objects as go

from langgraph_tagger.analytics.charts import (
    timeseries_line,
    report_type_lines,
    monthly_bar,
    publisher_pie,
    ranking_bar,
)


def test_timeseries_line_returns_figure():
    df = pd.DataFrame({
        'bucket': pd.to_datetime(['2026-05-01', '2026-05-02', '2026-05-01']),
        'sector': ['반도체', '반도체', '2차전지'],
        'count': [1, 2, 1],
    })
    fig = timeseries_line(df, title='Test')
    assert isinstance(fig, go.Figure)
    # One trace per sector
    assert len(fig.data) == 2


def test_report_type_lines_returns_figure():
    df = pd.DataFrame({
        'bucket': pd.to_datetime(['2026-05-01', '2026-05-02']),
        'report_type': ['단일종목', '산업'],
        'count': [3, 1],
    })
    fig = report_type_lines(df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


def test_monthly_bar_returns_figure():
    df = pd.DataFrame({
        'bucket': pd.to_datetime(['2026-05-01', '2026-05-02']),
        'count': [3, 5],
    })
    fig = monthly_bar(df, title='월별')
    assert isinstance(fig, go.Figure)


def test_publisher_pie_returns_figure():
    df = pd.DataFrame({
        'publisher': ['NH', '키움', '기타'],
        'count': [10, 5, 3],
    })
    fig = publisher_pie(df)
    assert isinstance(fig, go.Figure)


def test_ranking_bar_returns_figure():
    df = pd.DataFrame({
        'code': ['005930', '000660'],
        'count': [42, 38],
    })
    fig = ranking_bar(df)
    assert isinstance(fig, go.Figure)


def test_empty_df_still_returns_figure():
    df = pd.DataFrame(columns=['bucket', 'sector', 'count'])
    fig = timeseries_line(df, title='Empty')
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0
