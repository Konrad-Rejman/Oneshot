'''Spec sampling for the Phase 3 training pipeline (training/specs.py).

The samplers must only ever produce specs the game itself considers valid:
the Character/Progression constructors validate on construction, so most of
the contract is "sampling many specs never raises".
'''
import random

from character import STAT_NAMES
from progression import SPELL_SLOT_LEVELS
from training import specs


def test_many_sampled_specs_are_valid_game_state():
    rng = random.Random(7)
    for _ in range(200):
        spec = specs.sample_spec(rng)  # constructors raise on invalid state
        assert len(spec['rolls']) == 5
        assert all(1 <= roll <= 20 for roll in spec['rolls'])
        assert spec['stat'] is None or spec['stat'] in STAT_NAMES
        progression = spec['progression']
        assert 1 <= progression.hp <= progression.max_hp
        assert set(progression.spell_slots) <= set(SPELL_SLOT_LEVELS)


def test_spell_actions_only_sampled_for_casters():
    rng = random.Random(11)
    for _ in range(300):
        spec = specs.sample_spec(rng)
        if 'spell' in spec['action_kind']:
            assert spec['character'].char_class in specs.CASTER_CLASSES


def test_relevant_stat_covers_both_tier_shift_bands():
    rng = random.Random(3)
    bands = set()
    for _ in range(200):
        character = specs.sample_character(rng, relevant_stat='Strength')
        value = character.stats['Strength']
        if value >= 8:
            bands.add('high')
        elif value <= 3:
            bands.add('low')
        else:
            bands.add('mid')
    assert bands == {'high', 'low', 'mid'}


def test_sampling_is_seed_deterministic():
    spec_a = specs.sample_spec(random.Random(42))
    spec_b = specs.sample_spec(random.Random(42))
    assert spec_a['rolls'] == spec_b['rolls']
    assert spec_a['character'].to_dict() == spec_b['character'].to_dict()
    assert spec_a['progression'].to_dict() == spec_b['progression'].to_dict()
