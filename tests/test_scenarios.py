'''Contracts for scenarios.py: summary parsing and the scenarios.json
on-disk format. Deliberately avoids the interactive menus — ROADMAP Phase 2
reworks the UI; the file format and parsing are what must stay stable.

CRUD tests redirect SCENARIOS_FILE to tmp_path so the real (gitignored)
scenarios.json is never touched.
'''
import json

import pytest

import scenarios
from scenarios import DEFAULT_SCENARIO, _split_summary


class TestSplitSummary:
    def test_default_scenario_summary_parses(self):
        sections = _split_summary(DEFAULT_SCENARIO['summary'])
        assert sections is not None
        assert set(sections) == {'OVERALL STORY', 'CURRENT QUEST', 'PLAYER STATUS'}

    def test_free_text_returns_none(self):
        assert _split_summary('just some words with no headers') is None

    def test_case_insensitive(self):
        text = ('overall story: A.\n\ncurrent quest: B.\n\nplayer status: C.')
        sections = _split_summary(text)
        assert sections is not None


@pytest.fixture
def scenario_file(tmp_path, monkeypatch):
    path = tmp_path / 'scenarios.json'
    monkeypatch.setattr(scenarios, 'SCENARIOS_FILE', str(path))
    return path


class TestScenarioCrud:
    def test_load_missing_file_returns_empty(self, scenario_file):
        assert scenarios.load_scenarios() == {}

    def test_add_then_load_round_trips(self, scenario_file):
        scenarios.add_scenario('Heist', 'You case the vault.', 'a summary')
        loaded = scenarios.load_scenarios()
        # {name: {'startMessage', 'summary'}} is the on-disk format contract.
        assert loaded == {
            'Heist': {'startMessage': 'You case the vault.', 'summary': 'a summary'}
        }

    def test_file_is_valid_utf8_json(self, scenario_file):
        scenarios.add_scenario('Heist', 'Vault…', 'résumé')
        with open(scenario_file, encoding='utf-8') as f:
            assert 'Heist' in json.load(f)

    def test_edit_existing(self, scenario_file):
        scenarios.add_scenario('Heist', 'old', 'old summary')
        scenarios.edit_scenario('Heist', 'new', 'new summary')
        assert scenarios.load_scenarios()['Heist']['startMessage'] == 'new'

    def test_edit_unknown_raises_keyerror(self, scenario_file):
        with pytest.raises(KeyError):
            scenarios.edit_scenario('Nope', 'x', 'y')

    def test_delete_removes_and_ignores_unknown(self, scenario_file):
        scenarios.add_scenario('Heist', 'a', 'b')
        scenarios.delete_scenario('Heist')
        assert scenarios.load_scenarios() == {}
        scenarios.delete_scenario('Heist')  # unknown name: silent no-op
