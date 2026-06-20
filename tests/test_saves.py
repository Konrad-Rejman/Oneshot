'''
Contracts for saves.py: save-slot name sanitisation, the per-user saves/
on-disk layout, legacy-save migration, and transcript formatting/export.
Deliberately avoids the interactive menus; the file format is what must stay
stable.

CRUD tests redirect SAVES_DIR/EXPORTS_DIR to tmp_path so real player saves
are never touched.
'''
import json
import os

import pytest

import saves
from saves import (
    SAVE_VERSION,
    _sanitize_name,
    format_transcript_text,
)

USER = 'tester'

CHATLOGS = [
    {'role': 'assistant', 'content': 'You wake in a forest.'},
    {'role': 'user', 'content': 'I stand up.'},
    {'role': 'assistant', 'content': 'The trees loom.'},
]

# Same keys as backup.pkl / main.py:session_state — the save-format contract.
STATE = {
    'User': 'tester',
    'Chat Logs': CHATLOGS,
    'Context Logs': [],
    'Tokens': 123,
    'Playtime': [[0.0, 10.0]],
    'Memory': [{'role': 'assistant', 'content': 'The trees loom.'}],
    'Summary': 'OVERALL STORY: x\n\nCURRENT QUEST: y\n\nPLAYER STATUS: z',
    'Character': {'name': 'A', 'race': 'Human', 'char_class': 'Wanderer',
                  'background': 'b', 'stats': {}},
    'Progression': {'max_hp': 11, 'hp': 8, 'level': 2, 'xp': 130,
                    'inventory': ['rope'], 'features': ['Second Wind']},
}


class TestSanitizeName:
    def test_keeps_letters_digits_spaces_dashes_underscores(self):
        assert _sanitize_name('My Save_2-b') == 'My Save_2-b'

    def test_strips_filesystem_unsafe_characters(self):
        assert _sanitize_name('a/b\\c:d*e?f"g<h>i|j') == 'abcdefghij'

    def test_collapses_whitespace_and_trims(self):
        assert _sanitize_name('  spaced   out  ') == 'spaced out'

    def test_nothing_usable_returns_empty(self):
        assert _sanitize_name('///***???') == ''


@pytest.fixture
def saves_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(saves, 'SAVES_DIR', str(tmp_path / 'saves'))
    monkeypatch.setattr(saves, 'EXPORTS_DIR', str(tmp_path / 'exports'))
    return tmp_path


class TestSaveSlotCrud:
    def test_list_missing_dir_returns_empty(self, saves_dirs):
        assert saves.list_saves(USER) == []

    def test_save_then_load_round_trips(self, saves_dirs):
        saves.save_session('Heist', STATE, USER)
        loaded = saves.load_session('Heist', USER)
        # The original state keys round-trip unchanged...
        for key, value in STATE.items():
            assert loaded[key] == value
        # ...and the format metadata is added on write.
        assert loaded['Version'] == SAVE_VERSION
        assert loaded['Name'] == 'Heist'

    def test_saves_under_per_user_directory(self, saves_dirs):
        saves.save_session('Heist', STATE, USER)
        assert saves._save_path('Heist', USER) == os.path.join(
            saves.SAVES_DIR, USER, 'Heist.json')
        assert os.path.isfile(saves._save_path('Heist', USER))

    def test_one_users_save_is_invisible_to_another(self, saves_dirs):
        saves.save_session('Heist', STATE, 'alice')
        assert saves.list_saves('bob') == []
        assert saves.list_saves('alice') == ['Heist']

    def test_same_name_different_users_coexist(self, saves_dirs):
        saves.save_session('Heist', STATE, 'alice')
        saves.save_session('Heist', dict(STATE, Tokens=999), 'bob')
        assert saves.load_session('Heist', 'alice')['Tokens'] == STATE['Tokens']
        assert saves.load_session('Heist', 'bob')['Tokens'] == 999

    def test_save_same_name_overwrites(self, saves_dirs):
        saves.save_session('Heist', STATE, USER)
        saves.save_session('Heist', dict(STATE, Tokens=999), USER)
        assert saves.list_saves(USER) == ['Heist']
        assert saves.load_session('Heist', USER)['Tokens'] == 999

    def test_list_most_recent_first(self, saves_dirs):
        saves.save_session('Old', STATE, USER)
        saves.save_session('New', STATE, USER)
        # Pin mtimes: same-second writes would make recency ordering flaky.
        os.utime(saves._save_path('Old', USER), (100, 100))
        os.utime(saves._save_path('New', USER), (200, 200))
        assert saves.list_saves(USER) == ['New', 'Old']

    def test_delete_removes_and_ignores_unknown(self, saves_dirs):
        saves.save_session('Heist', STATE, USER)
        saves.delete_save('Heist', USER)
        assert saves.list_saves(USER) == []
        saves.delete_save('Heist', USER)  # unknown name: silent no-op

    def test_file_is_valid_utf8_json(self, saves_dirs):
        saves.save_session('Heist', dict(STATE, Summary='résumé…'), USER)
        with open(saves._save_path('Heist', USER), encoding='utf-8') as f:
            assert json.load(f)['Summary'] == 'résumé…'


class TestMigrateSaves:
    def _write_flat(self, name):
        # A pre-ownership save sitting directly in SAVES_DIR.
        os.makedirs(saves.SAVES_DIR, exist_ok=True)
        with open(os.path.join(saves.SAVES_DIR, name + '.json'), 'w', encoding='utf-8') as f:
            json.dump(dict(STATE, Name=name, Version=SAVE_VERSION), f)

    def test_flat_save_is_claimed_by_first_user(self, saves_dirs):
        self._write_flat('Heist')
        saves.migrate_saves('alice')
        assert saves.list_saves('alice') == ['Heist']
        # No flat save left behind in the top-level directory.
        assert [f for f in os.listdir(saves.SAVES_DIR)
                if os.path.isfile(os.path.join(saves.SAVES_DIR, f))] == []

    def test_migrate_is_noop_without_flat_saves(self, saves_dirs):
        saves.save_session('Heist', STATE, 'alice')
        saves.migrate_saves('bob')
        assert saves.list_saves('bob') == []
        assert saves.list_saves('alice') == ['Heist']

    def test_migrate_missing_dir_is_noop(self, saves_dirs):
        saves.migrate_saves('alice')  # no SAVES_DIR yet: silent no-op
        assert saves.list_saves('alice') == []


class TestTranscriptText:
    def test_gm_and_player_blocks(self):
        assert format_transcript_text(CHATLOGS) == (
            'GM:\n\nYou wake in a forest.\n\n'
            'PLAYER:\n\nI stand up.\n\n'
            'GM:\n\nThe trees loom.\n\n'
        )

    def test_system_role_renders_as_gm(self):
        text = format_transcript_text([{'role': 'system', 'content': 'rules'}])
        assert text == 'GM:\n\nrules\n\n'


class TestTranscriptMarkdown:
    def test_title_heading_and_speaker_sections(self):
        assert saves.format_transcript_markdown(CHATLOGS, 'Heist') == (
            '# Heist\n'
            '\n### GM:\n\nYou wake in a forest.\n'
            '\n### PLAYER:\n\nI stand up.\n'
            '\n### GM:\n\nThe trees loom.\n'
        )

    def test_system_role_renders_as_gm(self):
        md = saves.format_transcript_markdown([{'role': 'system', 'content': 'rules'}], 'T')
        assert md == '# T\n\n### GM:\n\nrules\n'


class TestExportTranscript:
    def test_txt_export_writes_file_and_returns_path(self, saves_dirs):
        path = saves.export_transcript(CHATLOGS, 'Heist', 'txt')
        assert path == os.path.join(saves.EXPORTS_DIR, 'Heist.txt')
        with open(path, encoding='utf-8') as f:
            assert f.read() == format_transcript_text(CHATLOGS)

    def test_md_export_writes_file_and_returns_path(self, saves_dirs):
        path = saves.export_transcript(CHATLOGS, 'Heist', 'md')
        assert path == os.path.join(saves.EXPORTS_DIR, 'Heist.md')
        with open(path, encoding='utf-8') as f:
            assert f.read() == saves.format_transcript_markdown(CHATLOGS, 'Heist')

    def test_unknown_format_raises_valueerror(self, saves_dirs):
        with pytest.raises(ValueError):
            saves.export_transcript(CHATLOGS, 'Heist', 'pdf')
