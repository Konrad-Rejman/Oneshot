'''
Contracts for progression.py: Progression validation, dict round-trip,
the XP/level curve, level-up and death/resurrection mechanics, and STATE-line
parsing/application (ROADMAP 2.3). Deliberately avoids the interactive
prompts; the dataclass, the STATE-line grammar and the clamping rules are
what must stay stable.
'''
import json

import pytest

from character import STAT_MAX, STAT_NAMES, Character
from progression import (
    HP_PER_LEVEL,
    MAX_LEVEL,
    RESURRECTION_XP_PENALTY,
    STARTING_HP_BASE,
    XP_PER_LEVEL,
    Progression,
    apply_state_changes,
    grant_feature,
    increase_stat,
    is_dead,
    level_for_xp,
    level_up,
    new_progression,
    parse_state_changes,
    pending_level_ups,
    resurrect,
    starting_max_hp,
    xp_for_level,
)


def make_progression(**overrides):
    fields = dict(max_hp=10, hp=10, level=1, xp=0, inventory=[], features=[])
    fields.update(overrides)
    return Progression(**fields)


def make_character(**stat_overrides):
    stats = {stat: 5 for stat in STAT_NAMES}
    stats.update(stat_overrides)
    return Character('A', 'Human', 'Rogue', 'bg', stats)


class TestProgressionValidation:
    def test_valid_constructs(self):
        p = make_progression(inventory=['rope'], features=['Second Wind'])
        assert p.hp == 10

    def test_hp_out_of_range_raises(self):
        with pytest.raises(ValueError):
            make_progression(hp=11)
        with pytest.raises(ValueError):
            make_progression(hp=-1)

    def test_non_integer_and_bool_raise(self):
        with pytest.raises(ValueError):
            make_progression(hp=5.5)
        # bool is an int subclass; True must not pass as hp 1
        with pytest.raises(ValueError):
            make_progression(hp=True)

    def test_level_out_of_range_raises(self):
        with pytest.raises(ValueError):
            make_progression(level=0)
        with pytest.raises(ValueError):
            make_progression(level=MAX_LEVEL + 1)

    def test_negative_xp_raises(self):
        with pytest.raises(ValueError):
            make_progression(xp=-1)

    def test_empty_inventory_entry_raises(self):
        with pytest.raises(ValueError):
            make_progression(inventory=[''])


class TestDictRoundTrip:
    def test_round_trip_preserves_fields(self):
        p = make_progression(hp=7, level=3, xp=230,
                             inventory=['rope', 'torch'], features=['Second Wind'])
        assert Progression.from_dict(p.to_dict()) == p

    def test_dict_is_json_safe(self):
        # Save slots are JSON; the dict must survive a JSON round-trip
        # unchanged (plain lists, ints).
        p = make_progression(inventory=['rope'], features=['Second Wind'])
        assert json.loads(json.dumps(p.to_dict())) == p.to_dict()

    def test_from_dict_ignores_legacy_keys(self):
        # Early version-2 saves carried spell-slot keys inside Progression;
        # from_dict must still load them by ignoring the extras.
        data = make_progression(hp=7).to_dict()
        data['spell_slots'] = {'1': 2}
        data['spell_slots_max'] = {'1': 3}
        assert Progression.from_dict(data) == make_progression(hp=7)

    def test_to_dict_copies_containers(self):
        # Mutating the exported dict must not reach back into the Progression.
        p = make_progression(inventory=['rope'])
        p.to_dict()['inventory'].append('torch')
        assert p.inventory == ['rope']


class TestNewProgression:
    def test_max_hp_from_constitution(self):
        p = new_progression(make_character(Constitution=7))
        assert p.max_hp == starting_max_hp(7) == STARTING_HP_BASE + 7
        assert p.hp == p.max_hp
        assert p.level == 1 and p.xp == 0

    def test_starts_with_empty_inventory_and_features(self):
        p = new_progression(make_character())
        assert p.inventory == [] and p.features == []


class TestXpCurve:
    def test_levels_at_flat_thresholds(self):
        assert xp_for_level(1) == 0
        assert xp_for_level(2) == XP_PER_LEVEL
        assert level_for_xp(0) == 1
        assert level_for_xp(XP_PER_LEVEL - 1) == 1
        assert level_for_xp(XP_PER_LEVEL) == 2

    def test_level_capped_at_max(self):
        assert level_for_xp(10 * MAX_LEVEL * XP_PER_LEVEL) == MAX_LEVEL

    def test_pending_level_ups(self):
        p = make_progression(xp=2 * XP_PER_LEVEL)
        assert pending_level_ups(p) == 2
        assert pending_level_ups(make_progression()) == 0


class TestLevelUp:
    def test_level_up_heals_and_raises_max_hp(self):
        p = make_progression(hp=3)
        level_up(p)
        assert p.level == 2
        assert p.max_hp == 10 + HP_PER_LEVEL
        assert p.hp == p.max_hp

    def test_increase_stat_caps_at_max(self):
        c = make_character(Strength=STAT_MAX)
        assert not increase_stat(c, 'Strength')
        assert c.stats['Strength'] == STAT_MAX
        assert increase_stat(c, 'Wisdom')
        assert c.stats['Wisdom'] == 6
        assert not increase_stat(c, 'Luck')

    def test_grant_feature(self):
        p = make_progression()
        grant_feature(p, 'Second Wind')
        assert p.features == ['Second Wind']


class TestDeathAndResurrection:
    def test_is_dead_at_zero_hp(self):
        assert is_dead(make_progression(hp=0))
        assert not is_dead(make_progression(hp=1))

    def test_resurrect_restores_half_hp_minimum_one(self):
        p = make_progression(hp=0)
        resurrect(p)
        assert p.hp == 5
        tiny = make_progression(max_hp=1, hp=0)
        resurrect(tiny)
        assert tiny.hp == 1

    def test_resurrect_xp_penalty_never_loses_a_level(self):
        p = make_progression(level=2, xp=XP_PER_LEVEL + 10, hp=0)
        resurrect(p)
        # Penalty would drop below the level floor; floor wins.
        assert p.xp == xp_for_level(2)
        rich = make_progression(level=2, xp=XP_PER_LEVEL + RESURRECTION_XP_PENALTY + 30, hp=0)
        resurrect(rich)
        assert rich.xp == XP_PER_LEVEL + 30


class TestParseStateChanges:
    def test_no_state_line_returns_unchanged(self):
        text = 'The corridor stretches into darkness.'
        clean, changes = parse_state_changes(text)
        assert clean == text
        assert changes == []

    def test_state_line_stripped_and_parsed(self):
        clean, changes = parse_state_changes(
            'The goblin slashes you.\n\nSTATE: HP -3; XP +25; GAIN torch; LOSE rope')
        assert clean == 'The goblin slashes you.'
        assert changes == [('hp', -3), ('xp', 25), ('gain', 'torch'),
                           ('lose', 'rope')]

    def test_none_state_line(self):
        clean, changes = parse_state_changes('You look around.\n\nSTATE: none')
        assert clean == 'You look around.'
        assert changes == []

    def test_markdown_decorated_state_line(self):
        # The model decorates despite being told not to (same failure mode
        # as the summary headers); decoration must not hide the line.
        clean, changes = parse_state_changes('You drink deep.\n\n**STATE:** HP +2**')
        assert clean == 'You drink deep.'
        assert changes == [('hp', 2)]

    def test_colon_and_comma_tolerated(self):
        _, changes = parse_state_changes('Hit.\n\nSTATE: HP: -3, XP: +10')
        assert changes == [('hp', -3), ('xp', 10)]

    def test_unparseable_entries_skipped(self):
        _, changes = parse_state_changes('Hm.\n\nSTATE: HP -2; the goblin flees; MANA -5')
        assert changes == [('hp', -2)]

    def test_multiple_state_lines_last_wins_all_stripped(self):
        clean, changes = parse_state_changes(
            'STATE: HP -1\n\nYou rally.\n\nSTATE: HP +4')
        assert changes == [('hp', 4)]
        assert 'STATE' not in clean
        assert clean == 'You rally.'

    def test_mid_text_state_keyword_not_matched(self):
        # Only a line of its own counts; narration mentioning a "state" with
        # text before it on the line must be left alone.
        text = 'The city state: a marvel of order.'
        clean, changes = parse_state_changes(text)
        assert clean == text
        assert changes == []


class TestApplyStateChanges:
    def test_hp_clamped_to_zero_and_max(self):
        p = make_progression(hp=2)
        apply_state_changes(p, [('hp', -99)])
        assert p.hp == 0
        apply_state_changes(p, [('hp', 99)])
        assert p.hp == p.max_hp

    def test_xp_gain_and_floor_at_level(self):
        p = make_progression(level=2, xp=XP_PER_LEVEL + 10)
        apply_state_changes(p, [('xp', 15)])
        assert p.xp == XP_PER_LEVEL + 25
        # A negative award can never de-level the character.
        apply_state_changes(p, [('xp', -999)])
        assert p.xp == xp_for_level(2)

    def test_gain_and_lose_items(self):
        p = make_progression()
        apply_state_changes(p, [('gain', 'Rope'), ('gain', 'torch')])
        assert p.inventory == ['Rope', 'torch']
        # Removal is case-insensitive; losing an item not held is ignored.
        apply_state_changes(p, [('lose', 'rope'), ('lose', 'shield')])
        assert p.inventory == ['torch']


class TestToPrompt:
    def test_contains_all_state(self):
        p = make_progression(hp=7, level=2, xp=130,
                             inventory=['rope'], features=['Second Wind'])
        prompt = p.to_prompt()
        assert 'STATUS' in prompt
        assert 'HP: 7/10' in prompt
        assert 'Level: 2' in prompt
        assert f'XP: 130 (level 3 at {xp_for_level(3)})' in prompt
        assert 'rope' in prompt
        assert 'Second Wind' in prompt

    def test_max_level_and_empty_collections(self):
        p = make_progression(level=MAX_LEVEL, xp=xp_for_level(MAX_LEVEL))
        prompt = p.to_prompt()
        assert 'maximum level' in prompt
        assert 'Inventory: nothing' in prompt
        assert 'Features: none' in prompt
