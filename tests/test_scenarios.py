'''
Contracts for scenarios.py: summary parsing and the scenarios.json on-disk
format (a list of owner-tagged records). Deliberately avoids the interactive
menus; the file format and parsing are what must stay stable.

CRUD tests redirect SCENARIOS_FILE to tmp_path so the real (gitignored)
scenarios.json is never touched.
'''
import json

import pytest

import ownership
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
        assert scenarios.load_scenarios() == []

    def test_add_then_load_round_trips(self, scenario_file):
        scenarios.add_scenario('Heist', 'You case the vault.', 'a summary', 'alice')
        # A list of {'name','owner','startMessage','summary'} records is the contract.
        assert scenarios.load_scenarios() == [{
            'name': 'Heist', 'owner': 'alice',
            'startMessage': 'You case the vault.', 'summary': 'a summary',
        }]

    def test_duplicate_names_across_owners_coexist(self, scenario_file):
        scenarios.add_scenario('Heist', 'a', 's', 'alice')
        scenarios.add_scenario('Heist', 'b', 's', 'bob')
        owners = sorted(r['owner'] for r in scenarios.load_scenarios())
        assert owners == ['alice', 'bob']

    def test_file_is_valid_utf8_json(self, scenario_file):
        scenarios.add_scenario('Heist', 'Vault…', 'résumé', 'alice')
        with open(scenario_file, encoding='utf-8') as f:
            assert json.load(f)[0]['name'] == 'Heist'

    def test_edit_existing_own(self, scenario_file):
        scenarios.add_scenario('Heist', 'old', 'old summary', 'alice')
        scenarios.edit_scenario('Heist', 'new', 'new summary', 'alice')
        assert scenarios.load_scenarios()[0]['startMessage'] == 'new'

    def test_edit_unknown_raises_keyerror(self, scenario_file):
        with pytest.raises(KeyError):
            scenarios.edit_scenario('Nope', 'x', 'y', 'alice')

    def test_edit_other_users_scenario_raises_keyerror(self, scenario_file):
        scenarios.add_scenario('Heist', 'a', 's', 'alice')
        # bob owns no 'Heist'; editing as bob must not touch alice's record.
        with pytest.raises(KeyError):
            scenarios.edit_scenario('Heist', 'hacked', 's', 'bob')
        assert scenarios.load_scenarios()[0]['startMessage'] == 'a'

    def test_delete_removes_own_and_ignores_unknown(self, scenario_file):
        scenarios.add_scenario('Heist', 'a', 'b', 'alice')
        scenarios.delete_scenario('Heist', 'alice')
        assert scenarios.load_scenarios() == []
        scenarios.delete_scenario('Heist', 'alice')  # unknown name: silent no-op

    def test_delete_leaves_other_users_records(self, scenario_file):
        scenarios.add_scenario('Heist', 'a', 's', 'alice')
        scenarios.add_scenario('Heist', 'b', 's', 'bob')
        scenarios.delete_scenario('Heist', 'bob')
        remaining = scenarios.load_scenarios()
        assert [r['owner'] for r in remaining] == ['alice']


class TestScenarioMigration:
    def test_legacy_dict_is_read_as_unowned_records(self, scenario_file):
        legacy = {'Heist': {'startMessage': 'a', 'summary': 'b'}}
        scenario_file.write_text(json.dumps(legacy), encoding='utf-8')
        assert scenarios.load_scenarios() == [{
            'name': 'Heist', 'owner': ownership.UNOWNED,
            'startMessage': 'a', 'summary': 'b',
        }]

    def test_migrate_claims_legacy_for_first_user(self, scenario_file):
        legacy = {'Heist': {'startMessage': 'a', 'summary': 'b'}}
        scenario_file.write_text(json.dumps(legacy), encoding='utf-8')
        scenarios.migrate_scenarios('alice')
        assert scenarios.load_scenarios()[0]['owner'] == 'alice'

    def test_migrate_missing_file_is_noop(self, scenario_file):
        scenarios.migrate_scenarios('alice')
        assert scenarios.load_scenarios() == []
