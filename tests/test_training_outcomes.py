'''
Deterministic turn mechanics for the Phase 3 pipeline (training/outcomes.py).

These build the parts of a GM turn the model is no longer trusted to produce
- the named stat, the consumed roll and the STATE line - so they are tested
like the rest of the deterministic logic: pure functions, no model calls.
The key contract is that every STATE line they emit passes the same strict
validator that gates the dataset (validators.check_state_line).
'''
import re

from training import outcomes, validators


# --- base_tier / effective_tier ---

def test_base_tier_boundaries():
    assert [outcomes.base_tier(r) for r in (1, 5)] == [0, 0]
    assert [outcomes.base_tier(r) for r in (6, 10)] == [1, 1]
    assert [outcomes.base_tier(r) for r in (11, 15)] == [2, 2]
    assert [outcomes.base_tier(r) for r in (16, 20)] == [3, 3]


def test_effective_tier_high_stat_shifts_up():
    # roll 8 is partial failure (1); a relevant stat of 8+ shifts it to 2.
    assert outcomes.effective_tier(8, 9) == 2


def test_effective_tier_low_stat_shifts_down():
    # roll 13 is partial success (2); a relevant stat of 3- shifts it to 1.
    assert outcomes.effective_tier(13, 2) == 1


def test_effective_tier_mid_stat_and_none_do_not_shift():
    assert outcomes.effective_tier(13, 5) == 2
    assert outcomes.effective_tier(13, None) == 2


def test_effective_tier_naturals_never_shift():
    assert outcomes.effective_tier(20, 1) == 3   # nat 20 stays full success
    assert outcomes.effective_tier(1, 10) == 0   # nat 1 stays critical failure


def test_effective_tier_clamps_at_both_ends():
    assert outcomes.effective_tier(18, 10) == 3  # already full success
    assert outcomes.effective_tier(3, 1) == 0    # already critical failure


# --- consequences ---

def test_success_awards_xp_in_band_and_scales_with_roll():
    _, low = outcomes.consequences(11, 'Strength', 5, [])
    _, high = outcomes.consequences(20, 'Strength', 5, [])
    assert 10 <= low['xp'] <= 50 and 10 <= high['xp'] <= 50
    assert high['xp'] == 50
    assert high['xp'] > low['xp']
    assert 'hp' not in low and 'lose' not in low


def test_physical_failure_costs_hp_mental_does_not():
    _, phys = outcomes.consequences(3, 'Strength', 5, [])
    assert phys['hp'] == -3  # critical failure
    _, partial = outcomes.consequences(8, 'Dexterity', 5, [])
    assert partial['hp'] == -2  # partial failure
    _, mental = outcomes.consequences(3, 'Charisma', 5, [])
    assert 'hp' not in mental


def test_critical_failure_loses_first_item_only_when_carrying():
    _, with_items = outcomes.consequences(2, 'Strength', 5, ['torch', 'rope'])
    assert with_items['lose'] == 'torch'
    _, empty = outcomes.consequences(2, 'Strength', 5, [])
    assert 'lose' not in empty
    # A partial (not critical) failure keeps the inventory.
    _, partial = outcomes.consequences(8, 'Strength', 5, ['torch'])
    assert 'lose' not in partial


def test_item_loss_is_restricted_to_physical_failures():
    # A social/mental critical failure must not lose an item: the loss is
    # only emitted for physical checks so it always has a bodily cause.
    _, social = outcomes.consequences(2, 'Charisma', 5, ['torch', 'rope'])
    assert 'lose' not in social and 'hp' not in social
    _, mental = outcomes.consequences(2, 'Intelligence', 5, ['torch'])
    assert 'lose' not in mental


# --- state_line: must satisfy the strict dataset validator ---

def test_state_line_empty_is_none():
    assert outcomes.state_line({}) == 'STATE: none'


def test_state_line_orders_entries_canonically():
    line = outcomes.state_line({'hp': -3, 'xp': 25, 'gain': 'torch',
                                'lose': 'rope'})
    assert line == 'STATE: HP -3; XP +25; GAIN torch; LOSE rope'


def test_every_emitted_state_line_passes_the_validator():
    cases = [
        {},
        {'xp': 50},
        {'hp': -2},
        {'hp': -3, 'lose': 'lantern'},
        {'xp': 30, 'gain': 'map'},
    ]
    for changes in cases:
        line = outcomes.state_line(changes)
        assert validators.check_state_line(f'You act.\n{line}') == []


def test_consequences_state_lines_round_trip_across_the_grid():
    # Every roll x relevant-stat-band combination must yield a STATE line the
    # dataset validator accepts.
    for roll in range(1, 21):
        for stat_value in (2, 5, 9, None):
            for stat in ('Strength', 'Charisma'):
                _, changes = outcomes.consequences(roll, stat, stat_value, ['torch'])
                line = outcomes.state_line(changes)
                assert validators.check_state_line(f'x\n{line}') == []


# --- announce_line / outcome_hint ---

def test_announce_line_format():
    assert outcomes.announce_line('Wisdom', 13) == 'Roll a Wisdom check... you roll a 13.'
    # "an" before a vowel-initial stat (Intelligence is the only one).
    assert outcomes.announce_line('Intelligence', 7) == 'Roll an Intelligence check... you roll a 7.'


def test_outcome_hint_carries_no_numbers_but_flags_wound_and_loss():
    hint = outcomes.outcome_hint(0, {'hp': -3, 'lose': 'torch'})
    assert not re.search(r'\d', hint)
    assert 'wounded' in hint.lower()
    assert 'torch' in hint
    assert 'success' not in outcomes.outcome_hint(0, {}).lower()
    assert 'succeeds' in outcomes.outcome_hint(3, {}).lower()
