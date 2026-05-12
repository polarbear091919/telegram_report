import pytest

from langgraph_tagger.analytics.krx import load_krx, search_stocks, lookup


def test_load_krx_returns_dataframe_with_known_columns(krx_csv):
    df = load_krx(krx_csv)
    assert 'code' in df.columns
    assert 'name' in df.columns
    assert 'sector_major' in df.columns
    assert 'sector_minor' in df.columns
    assert len(df) == 5


def test_search_by_code_prefix(krx_csv):
    df = load_krx(krx_csv)
    result = search_stocks(df, '005')
    codes = result['code'].tolist()
    assert '005930' in codes
    assert '000660' not in codes


def test_search_by_name_substring(krx_csv):
    df = load_krx(krx_csv)
    result = search_stocks(df, '삼성')
    codes = result['code'].tolist()
    assert '005930' in codes


def test_search_empty_query_returns_all(krx_csv):
    df = load_krx(krx_csv)
    result = search_stocks(df, '')
    assert len(result) == 5


def test_lookup_returns_tuple(krx_csv):
    df = load_krx(krx_csv)
    info = lookup(df, '005930')
    assert info == ('005930', '삼성전자', '반도체', '메모리반도체')


def test_lookup_missing_returns_none(krx_csv):
    df = load_krx(krx_csv)
    assert lookup(df, '999999') is None


def test_load_krx_missing_file(tmp_path):
    missing = tmp_path / 'nope.csv'
    with pytest.raises(FileNotFoundError):
        load_krx(missing)
