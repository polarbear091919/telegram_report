"""Plotly figure builders for the analytics dashboard.

All functions take a DataFrame and return a plotly.graph_objects.Figure.
No DB calls, no Streamlit calls — pure.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def timeseries_line(df: pd.DataFrame, title: str = '') -> go.Figure:
    """One line per sector. Columns: bucket, sector, count."""
    if df.empty:
        return go.Figure(layout={'title': title})
    fig = px.line(df, x='bucket', y='count', color='sector', title=title, markers=True)
    fig.update_layout(legend_title_text='산업', xaxis_title='', yaxis_title='발행 건수')
    return fig


def report_type_lines(df: pd.DataFrame) -> go.Figure:
    """One line per report_type. Columns: bucket, report_type, count."""
    if df.empty:
        return go.Figure(layout={'title': 'Report type volume'})
    fig = px.line(df, x='bucket', y='count', color='report_type',
                   title='Report type volume', markers=True)
    fig.update_layout(legend_title_text='유형', xaxis_title='', yaxis_title='발행 건수')
    return fig


def monthly_bar(df: pd.DataFrame, title: str = '') -> go.Figure:
    """Bar chart per bucket. Columns: bucket, count."""
    if df.empty:
        return go.Figure(layout={'title': title})
    fig = px.bar(df, x='bucket', y='count', title=title)
    fig.update_layout(xaxis_title='', yaxis_title='발행 건수')
    return fig


def publisher_pie(df: pd.DataFrame) -> go.Figure:
    """Pie chart. Columns: publisher, count."""
    if df.empty:
        return go.Figure(layout={'title': '발행처 분포'})
    fig = px.pie(df, names='publisher', values='count', title='발행처 분포')
    return fig


def ranking_bar(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar of stock ranking. Columns: code, count.

    Caller may join name before passing for nicer labels (label='code name').
    """
    if df.empty:
        return go.Figure(layout={'title': 'Coverage volume'})
    label_col = 'label' if 'label' in df.columns else 'code'
    fig = px.bar(df, y=label_col, x='count', orientation='h',
                  title='Coverage volume')
    fig.update_layout(yaxis={'categoryorder': 'total ascending'},
                       xaxis_title='건수', yaxis_title='')
    return fig
