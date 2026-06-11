'''Contracts for saves.py: save-slot name sanitisation, the saves/ on-disk
format, and transcript formatting/export. Deliberately avoids the interactive
menus — ROADMAP Phase 2.4 reworks the UI; the file format is what must stay
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
        assert saves.list_saves() == []

    def test_save_then_load_round_trips(self, saves_dirs):
        saves.save_session('Heist', STATE)
        loaded = saves.load_session('Heist')
        # The original state keys round-trip unchanged...
        for key, value in STATE.items():
            assert loaded[key] == value
        # ...and the format metadata is added on write.
        assert loaded['Version'] == SAVE_VERSION
        assert loaded['Name'] == 'Heist'

    def test_save_same_name_overwrites(self, saves_dirs):
        saves.save_session('Heist', STATE)
        saves.save_session('Heist', dict(STATE, Tokens=999))
        assert saves.list_saves() == ['Heist']
        assert saves.load_session('Heist')['Tokens'] == 999

    def test_list_most_recent_first(self, saves_dirs):
        saves.save_session('Old', STATE)
        saves.save_session('New', STATE)
        # Pin mtimes: same-second writes would make recency ordering flaky.
        os.utime(saves._save_path('Old'), (100, 100))
        os.utime(saves._save_path('New'), (200, 200))
        assert saves.list_saves() == ['New', 'Old']

    def test_delete_removes_and_ignores_unknown(self, saves_dirs):
        saves.save_session('Heist', STATE)
        saves.delete_save('Heist')
        assert saves.list_saves() == []
        saves.delete_save('Heist')  # unknown name: silent no-op

    def test_file_is_valid_utf8_json(self, saves_dirs):
        saves.save_session('Heist', dict(STATE, Summary='résumé…'))
        with open(saves._save_path('Heist'), encoding='utf-8') as f:
            assert json.load(f)['Summary'] == 'résumé…'


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
