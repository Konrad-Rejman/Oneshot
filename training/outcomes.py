'''
Deterministic turn mechanics for the Phase 3 training pipeline (ROADMAP 3.1).

The base model writes prose well but cannot reliably name the right stat,
consume the correct roll, or emit a populated STATE line - so the generator
no longer asks it to. From the spec's roll pool, relevant stat and action it
computes the check announcement, the consequence tier (with the CHARACTER
rule's stat-based shift) and the canonical STATE line here, and the model is
asked only to narrate the given outcome. This guarantees that every training
example demonstrates correct dice usage, the right stat, the tier->outcome
mapping and a valid STATE line - the exact behaviours the fine-tune must
learn but the base model rarely produces on its own.

Pure functions over the spec's scalar fields (no model calls, no game
imports beyond the stat name set) so the test suite covers them like the
rest of the deterministic logic (tests/test_training_outcomes.py). Numbers
are derived from the roll so the data varies without an extra rng.
'''

# The four consequence tiers, indexed 0-3, matching the rules prompt's
# 1-5 / 6-10 / 11-15 / 16-20 scaling.
TIER_NAMES = ['critical failure', 'partial failure',
              'partial success', 'full success']

# Physical/bodily stats: failed checks driven by these cost HP (the
# PROGRESSION rule "failed checks with physical danger should cost HP");
# mental and social failures do not wound the character.
PHYSICAL_STATS = {'Strength', 'Dexterity', 'Constitution'}


def base_tier(roll):
    '''The unshifted consequence tier (0-3) for a raw D20 value.'''
    if roll <= 5:
        return 0
    if roll <= 10:
        return 1
    if roll <= 15:
        return 2
    return 3


def effective_tier(roll, stat_value):
    '''
    The consequence tier after the CHARACTER rule's stat shift: a relevant
    stat of 8+ shifts one tier better, 3- one tier worse, naturals (1 and
    20) never shift. stat_value is None for a no-stat action (no shift).
    '''
    tier = base_tier(roll)
    if roll in (1, 20) or stat_value is None:
        return tier
    if stat_value >= 8:
        return min(3, tier + 1)
    if stat_value <= 3:
        return max(0, tier - 1)
    return tier


def consequences(roll, stat, stat_value, inventory):
    '''
    The mechanical changes a check turn produces, as a tier (0-3) and a
    changes dict keyed by entry kind:
      - success (tier 2-3) awards XP scaled by the roll (10-50);
      - a failed physical check (tier 0-1) costs HP;
      - a critical failure also loses the first carried item, if any.
    '''
    tier = effective_tier(roll, stat_value)
    changes = {}
    if tier >= 2:  # success: the challenge is overcome
        changes['xp'] = min(50, 10 + 2 * roll)
    else:  # failure
        if stat in PHYSICAL_STATS:
            changes['hp'] = -3 if tier == 0 else -2
        if tier == 0 and inventory:
            changes['lose'] = inventory[0]
    return tier, changes


def announce_line(stat, roll):
    '''The canonical check announcement the rules prompt mandates.'''
    article = 'an' if stat[:1].lower() in 'aeiou' else 'a'
    return f'Roll {article} {stat} check... you roll a {roll}.'


def state_line(changes):
    '''
    Render a changes dict as the canonical final STATE line, entries in the
    rules prompt's order (HP; XP; GAIN; LOSE). An empty dict is "none".
    The output is built to satisfy validators.check_state_line exactly.
    '''
    parts = []
    if 'hp' in changes:
        parts.append(f'HP {changes["hp"]:+d}')
    if 'xp' in changes:
        parts.append(f'XP +{changes["xp"]}')
    if 'gain' in changes:
        parts.append(f'GAIN {changes["gain"]}')
    if 'lose' in changes:
        parts.append(f'LOSE {changes["lose"]}')
    return 'STATE: ' + ('; '.join(parts) if parts else 'none')


def outcome_hint(tier, changes):
    '''
    A plain-language description of the outcome for the narration prompt -
    what happened, never how it was rolled. The model turns this into prose;
    no numbers or mechanics words appear so they cannot leak into the data.
    '''
    if tier == 0:
        hint = ('The attempt fails badly and the situation turns sharply '
                'against the player.')
    elif tier == 1:
        hint = 'The attempt does not work, or only half-works at a real cost.'
    elif tier == 2:
        hint = ('The attempt works and the player gets what they were after, '
                'but a minor complication or limit comes with it.')
    else:
        hint = ('The attempt clearly succeeds: the player fully overcomes the '
                'obstacle and ends the moment better off, with no reversal or '
                'new setback undoing it.')
    if 'hp' in changes:
        hint += ' The player is wounded in the process.'
    if 'lose' in changes:
        hint += f' In the chaos the player loses their {changes["lose"]}.'
    return hint
