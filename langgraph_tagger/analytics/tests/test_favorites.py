import json
from pathlib import Path

import pytest

from langgraph_tagger.analytics import favorites


def test_load_missing_file_returns_empty(tmp_path: Path):
    path = tmp_path / 'favs.json'
    result = favorites.load(path)
    assert result == []
    assert not path.exists()


def test_load_creates_parent_dir_on_add(tmp_path: Path):
    path = tmp_path / 'sub' / 'favs.json'
    favorites.add(path, '005930')
    assert path.exists()
    assert json.loads(path.read_text(encoding='utf-8')) == {'stocks': ['005930']}


def test_add_is_idempotent(tmp_path: Path):
    path = tmp_path / 'favs.json'
    favorites.add(path, '005930')
    favorites.add(path, '005930')
    favorites.add(path, '005930')
    assert favorites.load(path) == ['005930']


def test_add_preserves_order(tmp_path: Path):
    path = tmp_path / 'favs.json'
    favorites.add(path, '005930')
    favorites.add(path, '000660')
    favorites.add(path, '373220')
    assert favorites.load(path) == ['005930', '000660', '373220']


def test_remove_existing(tmp_path: Path):
    path = tmp_path / 'favs.json'
    favorites.add(path, '005930')
    favorites.add(path, '000660')
    favorites.remove(path, '005930')
    assert favorites.load(path) == ['000660']


def test_remove_absent_is_noop(tmp_path: Path):
    path = tmp_path / 'favs.json'
    favorites.add(path, '005930')
    favorites.remove(path, '999999')
    assert favorites.load(path) == ['005930']


def test_corrupted_json_backs_up_and_returns_empty(tmp_path: Path):
    path = tmp_path / 'favs.json'
    path.write_text('not valid json {', encoding='utf-8')
    result = favorites.load(path)
    assert result == []
    bak = path.with_suffix('.json.bak')
    assert bak.exists()
    assert bak.read_text(encoding='utf-8') == 'not valid json {'


def test_corrupted_then_add_recovers(tmp_path: Path):
    """After .bak backup of corrupted file, a subsequent add must work cleanly."""
    path = tmp_path / 'favs.json'
    path.write_text('bad json', encoding='utf-8')
    favorites.add(path, '005930')          # must not raise
    assert favorites.load(path) == ['005930']
    assert path.with_suffix('.json.bak').exists()


def test_load_non_dict_json_backs_up(tmp_path: Path):
    """Valid JSON but wrong shape (e.g. a list, null, int) must trigger .bak recovery."""
    path = tmp_path / 'favs.json'
    path.write_text('["005930", "000660"]', encoding='utf-8')   # list, not dict
    result = favorites.load(path)
    assert result == []
    assert path.with_suffix('.json.bak').exists()
