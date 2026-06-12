'''
Contracts for character.py: Character validation, dict round-trip, and
the characters.json on-disk format. Deliberately avoids the interactive
menus; the dataclass and file format are what must stay stable.

CRUD tests redirect CHARACTERS_FILE to tmp_path so a real characters.json
is never touched.
'''
import json

import pytest

import character
from character import (
    DEFAULT_CHARACTER,
    STAT_MAX,
    STAT_MIN,
    STAT_NAMES,
    STAT_POOL,
    Character,
    describe_stat,
)


def make_stats(**overrides):
    stats = {stat: 5 for stat in STAT_NAMES}
    stats.update(overrides)
    return stats


class TestCharacterValidation:
    def test_valid_character_constructs(self):
        c = Character('A', 'Human', 'Rogue', 'bg', make_stats())
        assert c.stats['Strength'] == 5

    def test_missing_stat_raises(self):
        stats = make_stats()
        del stats['Wisdom']
        with pytest.raises(ValueError, match='Wisdom'):
            Character('A', 'Human', 'Rogue', 'bg', stats)

    def test_unknown_stat_raises(self):
        with pytest.raises(ValueError, match='Luck'):
            Character('A', 'Human', 'Rogue', 'bg', make_stats(Luck=5))

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            Character('A', 'Human', 'Rogue', 'bg', make_stats(Strength=STAT_MAX + 1))
        with pytest.raises(ValueError):
            Character('A', 'Human', 'Rogue', 'bg', make_stats(Strength=STAT_MIN - 1))

    def test_non_integer_raises(self):
        with pytest.raises(ValueError):
            Character('A', 'Human', 'Rogue', 'bg', make_stats(Strength=5.5))
        # bool is an int subclass; True must not pass as a stat value of 1
        with pytest.raises(ValueError):
            Character('A', 'Human', 'Rogue', 'bg', make_stats(Strength=True))


class TestDictRoundTrip:
    def test_round_trip_preserves_fields(self):
        c = Character('A', 'Elf', 'Wizard', 'bg', make_stats(Intelligence=9))
        restored = Character.from_dict(c.to_dict())
        assert restored == c

    def test_to_dict_copies_stats(self):
        # Mutating the exported dict must not reach back into the Character.
        c = Character('A', 'Elf', 'Wizard', 'bg', make_stats())
        c.to_dict()['stats']['Strength'] = 1
        assert c.stats['Strength'] == 5


class TestDescribeStat:
    def test_every_valid_value_has_a_phrase(self):
        for value in range(STAT_MIN, STAT_MAX + 1):
            phrase = describe_stat(value)
            assert isinstance(phrase, str) and phrase

    def test_average_anchor(self):
        # The rules prompt tells the model "5 is an average person"; the
        # phrase for 5 must agree with that anchor.
        assert describe_stat(5) == 'average'


class TestToPrompt:
    def test_contains_identity_and_all_stats(self):
        c = Character('Kira', 'Elf', 'Ranger', 'a quiet tracker', make_stats(Dexterity=8))
        prompt = c.to_prompt()
        assert 'CHARACTER SHEET' in prompt
        for fragment in ['Kira', 'Elf', 'Ranger', 'a quiet tracker']:
            assert fragment in prompt
        for stat in STAT_NAMES:
            assert f'{stat} {c.stats[stat]}/{STAT_MAX} ({describe_stat(c.stats[stat])})' in prompt


class TestDefaultCharacter:
    def test_default_is_valid_and_sums_to_pool(self):
        assert set(DEFAULT_CHARACTER.stats) == set(STAT_NAMES)
        assert sum(DEFAULT_CHARACTER.stats.values()) == STAT_POOL


@pytest.fixture
def character_file(tmp_path, monkeypatch):
    path = tmp_path / 'characters.json'
    monkeypatch.setattr(character, 'CHARACTERS_FILE', str(path))
    return path


class TestCharacterCrud:
    def test_load_missing_file_returns_empty(self, character_file):
        assert character.load_characters() == {}

    def test_add_then_load_round_trips(self, character_file):
        c = Character('Kira', 'Elf', 'Ranger', 'bg', make_stats())
        character.add_character('Kira', c)
        loaded = character.load_characters()
        # {name: character_dict} is the on-disk format contract.
        assert loaded == {'Kira': c.to_dict()}
        assert Character.from_dict(loaded['Kira']) == c

    def test_file_is_valid_utf8_json(self, character_file):
        c = Character('Kira…', 'Elf', 'Ranger', 'résumé', make_stats())
        character.add_character('Kira…', c)
        with open(character_file, encoding='utf-8') as f:
            assert 'Kira…' in json.load(f)

    def test_delete_removes_and_ignores_unknown(self, character_file):
        c = Character('Kira', 'Elf', 'Ranger', 'bg', make_stats())
        character.add_character('Kira', c)
        character.delete_character('Kira')
        assert character.load_characters() == {}
        character.delete_character('Kira')  # unknown name: silent no-op
