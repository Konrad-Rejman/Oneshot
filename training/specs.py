'''Structural scenario specs for the Phase 3 training pipeline (ROADMAP 3.1).

A spec is the *parameters* of one training example - location/threat/goal
keywords, the action kind and its stat, a sampled character and progression,
and the turn's roll pool. All creative prose (the opening scene, the summary,
the player action, the GM response) is generated from the spec by the local
base model in generate_dataset.py, so every sentence in the dataset is
model-authored; this file contributes only terse generic noun phrases and
random sampling, which keeps the dataset's provenance single-source (see
training/COMPLIANCE.md). Names are assembled from syllables; feature names
are generic phrases, deliberately not SRD terms.

Everything takes an explicit random.Random so sampling is seedable and the
distribution helpers are testable (tests/test_training_specs.py).
'''
import sys
from pathlib import Path

# Runnable both as a module (python -m training.generate_dataset) and with
# the repo root not on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from character import Character, STAT_NAMES  # noqa: E402
from progression import Progression, starting_max_hp, HP_PER_LEVEL  # noqa: E402
from rolls import roll_num  # noqa: E402

LOCATIONS = [
    'dungeon', 'forest', 'tavern', 'mountain pass', 'castle hall', 'sewer',
    'desert ruin', 'harbour town', 'cave', 'swamp', 'old library', 'mine',
    'crypt', 'market square', 'wizard tower', 'battlefield', 'ship at sea',
    'temple', 'snowfield', 'underground lake',
]

THREATS = [
    'goblin ambush', 'locked door', 'collapsed bridge', 'suspicious guard',
    'hidden trap', 'wild beast', 'rival adventurer', 'cursed idol',
    'poison gas', 'narrow ledge', 'angry mob', 'sleeping dragon',
    'magical ward', 'thief', 'riddle inscription', 'crumbling floor',
    'hostile patrol', 'storm', 'dark ritual', 'sealed gate',
]

GOALS = [
    'stolen relic', 'missing child', 'ancient map', 'bounty', 'lost heirloom',
    'secret passage', 'cure for a plague', 'traitor', 'buried treasure',
    'kidnapped merchant', 'forbidden book', 'broken seal', 'missing caravan',
    'haunted manor', 'smuggling ring',
]

# (action kind, most relevant stat, requires a check). The kind is a generic
# verb phrase the action-generation prompt hands to the model; the stat
# drives the high/low-stat tier-shift sampling below. Check-free kinds train
# the "skip a check for conversation and flavour" rule.
ACTIONS = [
    ('fight it head-on', 'Strength', True),
    ('force the obstacle open', 'Strength', True),
    ('swim across', 'Strength', True),
    ('sneak past unseen', 'Dexterity', True),
    ('pick the lock', 'Dexterity', True),
    ('dodge out of the way', 'Dexterity', True),
    ('jump the gap', 'Dexterity', True),
    ('disarm the trap', 'Dexterity', True),
    ('endure the strain', 'Constitution', True),
    ('resist the effect', 'Constitution', True),
    ('decipher the inscription', 'Intelligence', True),
    ('recall what is known about it', 'Intelligence', True),
    ('cast a spell at the problem', 'Intelligence', True),
    ('search the area for clues', 'Wisdom', True),
    ('listen carefully at the door', 'Wisdom', True),
    ('track where it went', 'Wisdom', True),
    ('persuade them to help', 'Charisma', True),
    ('deceive them with a story', 'Charisma', True),
    ('intimidate them into backing down', 'Charisma', True),
    ('haggle over the price', 'Charisma', True),
    ('make small talk and ask around', None, False),
    ('take a careful look at the surroundings', None, False),
]

ITEMS = [
    'torch', 'rope', 'dagger', 'healing potion', 'shield', 'lockpicks',
    'map', 'lantern', 'rations', 'short sword', 'bow', 'cloak',
    'grappling hook', 'spellbook', 'flask of oil', 'coin pouch', 'bedroll',
    'crowbar', 'smoke bomb', 'silver ring',
]

RACES = ['human', 'elf', 'dwarf', 'halfling', 'half-orc', 'gnome']
CLASSES = ['fighter', 'rogue', 'wizard', 'cleric', 'ranger', 'bard']
CASTER_CLASSES = {'wizard', 'cleric', 'bard'}
OCCUPATIONS = [
    'soldier', 'farmhand', 'scribe', 'sailor', 'poacher', 'acolyte',
    'street urchin', 'merchant', 'blacksmith', 'hunter',
]

# Generic feature phrases - deliberately not SRD feature names, so the
# dataset contains no Wizards of the Coast text at all.
FEATURES = [
    'second wind', 'keen senses', 'battle focus', 'light step', 'iron will',
    'steady hands', 'silver tongue', 'night vision', 'beast empathy',
]

_NAME_SYLLABLES = [
    'ar', 'bel', 'cor', 'dan', 'el', 'fen', 'gar', 'hal', 'isa', 'jor',
    'kel', 'lan', 'mor', 'nia', 'or', 'pel', 'quin', 'ros', 'sil', 'tor',
    'ula', 'vor', 'wyn', 'xan', 'yor', 'zel',
]


def sample_name(rng):
    return ''.join(rng.choice(_NAME_SYLLABLES)
                   for _ in range(rng.choice([2, 3]))).capitalize()


def sample_character(rng, relevant_stat=None):
    '''
    A random character on the game's 1-10 stat scale. When relevant_stat is
    given, that stat is pushed high (8-10, tier shift up), low (1-3, tier
    shift down) or mid in roughly 25/25/50 proportions, so the dataset
    exercises the CHARACTER rules' tier shifts in both directions.
    '''
    stats = {name: rng.randint(3, 7) for name in STAT_NAMES}
    if relevant_stat is not None:
        band = rng.random()
        if band < 0.25:
            stats[relevant_stat] = rng.randint(8, 10)
        elif band < 0.5:
            stats[relevant_stat] = rng.randint(1, 3)
    return Character(
        name=sample_name(rng),
        race=rng.choice(RACES),
        char_class=rng.choice(CLASSES),
        background=f'A former {rng.choice(OCCUPATIONS)}.',
        stats=stats,
    )


def sample_progression(rng, character):
    '''
    A random but internally consistent progression: max HP follows the
    game's formula for the sampled level, HP is weighted towards full but
    covers the wounded and near-death bands (so low-HP narration and death
    turns appear in the data), casters get level-1 slots with some spent.
    '''
    level = rng.choice([1, 1, 1, 2, 2, 3, 4, 5])
    max_hp = starting_max_hp(character.stats['Constitution']) + HP_PER_LEVEL * (level - 1)
    band = rng.random()
    if band < 0.4:
        hp = max_hp
    elif band < 0.85:
        hp = rng.randint(max(1, max_hp // 3), max_hp)
    else:
        hp = rng.randint(1, max(1, max_hp // 3))  # near death
    slots, slots_max = {}, {}
    if character.char_class in CASTER_CLASSES:
        total = rng.randint(2, 3)
        slots_max['1'] = total
        slots['1'] = rng.randint(0, total)
    xp = (level - 1) * 100 + rng.randint(0, 99)
    inventory = rng.sample(ITEMS, rng.randint(0, 5))
    features = rng.sample(FEATURES, max(0, level - 1))
    return Progression(max_hp=max_hp, hp=hp, level=level, xp=xp,
                       spell_slots=slots, spell_slots_max=slots_max,
                       inventory=inventory, features=features)


def sample_spec(rng):
    '''One training example's full parameter set.'''
    kind, stat, requires_check = rng.choice(ACTIONS)
    character = sample_character(rng, relevant_stat=stat)
    # A spell action from a non-caster would contradict the STATUS block the
    # prompt swears by; reroute it to a mundane action instead.
    if 'spell' in kind and character.char_class not in CASTER_CLASSES:
        kind, stat, requires_check = ACTIONS[0]
    return {
        'location': rng.choice(LOCATIONS),
        'threat': rng.choice(THREATS),
        'goal': rng.choice(GOALS),
        'action_kind': kind,
        'stat': stat,
        'requires_check': requires_check,
        'character': character,
        'progression': sample_progression(rng, character),
        'rolls': [rng.randint(1, 20) for _ in range(roll_num)],
    }
