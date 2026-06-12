'''Character progression: HP, spell slots, inventory, XP, levels, and death
(ROADMAP 2.3).

The GM model reports each turn's mechanical changes in a machine-read STATE
line at the end of its reply ("STATE: HP -3; XP +25; GAIN torch").
parse_state_changes strips that line from the narration before it is stored
anywhere and returns the parsed entries; apply_state_changes applies them to
the Progression dataclass, clamping everything to valid ranges. The current
state is surfaced back to the model each turn through Progression.to_prompt,
the same way the character sheet is, so the model never has to remember the
numbers itself.

The model omitting or mangling the STATE line degrades safely: no entries
parse, so nothing changes that turn.
'''
import re
from dataclasses import dataclass, field

from character import STAT_MAX, STAT_NAMES

# Flat XP curve: level N is reached at (N - 1) * XP_PER_LEVEL total XP. The
# rules prompt tells the GM to award 10-50 XP per meaningful challenge, so a
# level is roughly 2-10 overcome challenges.
XP_PER_LEVEL = 100
MAX_LEVEL = 10  # matches the 1-10 stat scale

STARTING_HP_BASE = 4  # starting max HP = STARTING_HP_BASE + Constitution
HP_PER_LEVEL = 2      # max HP gained per level

# XP lost on resurrection - never below the current level's floor, so a
# resurrection can never take a level away.
RESURRECTION_XP_PENALTY = 50

# Valid spell-slot levels. String keys so the dicts round-trip through the
# JSON save slots unchanged.
SPELL_SLOT_LEVELS = [str(n) for n in range(1, 10)]

@dataclass
class Progression:
    max_hp: int
    hp: int
    level: int = 1
    xp: int = 0
    spell_slots: dict = field(default_factory=dict)      # {slot level: remaining}
    spell_slots_max: dict = field(default_factory=dict)  # {slot level: total}
    inventory: list = field(default_factory=list)
    features: list = field(default_factory=list)

    def __post_init__(self):
        for name in ('max_hp', 'hp', 'level', 'xp'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f'{name} must be an integer, got {value!r}')
        if self.max_hp < 1:
            raise ValueError(f'max_hp must be at least 1, got {self.max_hp}')
        if not (0 <= self.hp <= self.max_hp):
            raise ValueError(f'hp must be between 0 and max_hp ({self.max_hp}), got {self.hp}')
        if not (1 <= self.level <= MAX_LEVEL):
            raise ValueError(f'level must be between 1 and {MAX_LEVEL}, got {self.level}')
        if self.xp < 0:
            raise ValueError(f'xp must not be negative, got {self.xp}')
        if set(self.spell_slots) != set(self.spell_slots_max):
            raise ValueError('spell_slots and spell_slots_max must list the same slot levels')
        for slot_level, maximum in self.spell_slots_max.items():
            if slot_level not in SPELL_SLOT_LEVELS:
                raise ValueError(f'Unknown spell-slot level: {slot_level!r}')
            remaining = self.spell_slots[slot_level]
            for value in (maximum, remaining):
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError(f'Spell-slot counts must be integers, got {value!r}')
            if maximum < 0 or not (0 <= remaining <= maximum):
                raise ValueError(f'Level-{slot_level} slots must satisfy 0 <= remaining <= maximum, '
                                 f'got {remaining}/{maximum}')
        for entry in list(self.inventory) + list(self.features):
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError(f'Inventory and feature entries must be non-empty strings, got {entry!r}')

    def to_dict(self):
        return {
            'max_hp': self.max_hp,
            'hp': self.hp,
            'level': self.level,
            'xp': self.xp,
            'spell_slots': dict(self.spell_slots),
            'spell_slots_max': dict(self.spell_slots_max),
            'inventory': list(self.inventory),
            'features': list(self.features),
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            max_hp=data['max_hp'],
            hp=data['hp'],
            level=data['level'],
            xp=data['xp'],
            spell_slots=dict(data['spell_slots']),
            spell_slots_max=dict(data['spell_slots_max']),
            inventory=list(data['inventory']),
            features=list(data['features']),
        )

    def to_prompt(self):
        '''
        Render the current state as a plain-text STATUS block appended to the
        system prompt each turn (like the character sheet), so the model can
        reference HP, slots and items accurately.
        '''
        if self.level >= MAX_LEVEL:
            xp_text = f'XP: {self.xp} (maximum level reached)'
        else:
            xp_text = f'XP: {self.xp} (level {self.level + 1} at {xp_for_level(self.level + 1)})'
        if self.spell_slots_max:
            slots_text = '; '.join(
                f'level {slot_level}: {self.spell_slots[slot_level]}/{self.spell_slots_max[slot_level]} remaining'
                for slot_level in sorted(self.spell_slots_max, key=int)
            )
        else:
            slots_text = 'none (not a spellcaster)'
        inventory_text = ', '.join(self.inventory) if self.inventory else 'nothing'
        features_text = ', '.join(self.features) if self.features else 'none'
        return (
            'STATUS:\n'
            f'HP: {self.hp}/{self.max_hp}\n'
            f'Level: {self.level}\n'
            f'{xp_text}\n'
            f'Spell slots: {slots_text}\n'
            f'Inventory: {inventory_text}\n'
            f'Features: {features_text}'
        )

def starting_max_hp(constitution):
    return STARTING_HP_BASE + constitution

def new_progression(character, level_1_slots=0):
    '''Fresh level-1 progression for the given Character: max HP from
    Constitution, optional starting level-1 spell slots, empty inventory.'''
    hp = starting_max_hp(character.stats['Constitution'])
    slots = {'1': level_1_slots} if level_1_slots > 0 else {}
    return Progression(max_hp=hp, hp=hp, spell_slots=dict(slots), spell_slots_max=dict(slots))

def xp_for_level(level):
    '''Total XP at which the given level is reached.'''
    return (level - 1) * XP_PER_LEVEL

def level_for_xp(xp):
    '''Level the given total XP entitles the character to, capped at MAX_LEVEL.'''
    return min(MAX_LEVEL, 1 + xp // XP_PER_LEVEL)

def pending_level_ups(progression):
    '''Levels earned by XP but not yet applied.'''
    return level_for_xp(progression.xp) - progression.level

def level_up(progression):
    '''Advance one level: +HP_PER_LEVEL max HP, fully healed, spell slots
    restored. The class-feature choice is applied separately (increase_stat /
    grant_feature / grant_spell_slot). Mutates in place.'''
    progression.level += 1
    progression.max_hp += HP_PER_LEVEL
    progression.hp = progression.max_hp
    progression.spell_slots = dict(progression.spell_slots_max)

def increase_stat(character, stat):
    '''Level-up choice: +1 to the named stat, capped at STAT_MAX.
    Returns False (and changes nothing) for an unknown or maxed stat.'''
    if stat not in character.stats or character.stats[stat] >= STAT_MAX:
        return False
    character.stats[stat] += 1
    return True

def grant_feature(progression, feature):
    '''Level-up choice: record a named class feature, surfaced to the model
    in the STATUS block.'''
    progression.features.append(feature)

def grant_spell_slot(progression, slot_level):
    '''Level-up choice: one more maximum (and current) spell slot of the
    given level ('1'-'9'). Returns False for an invalid slot level.'''
    slot_level = str(slot_level)
    if slot_level not in SPELL_SLOT_LEVELS:
        return False
    progression.spell_slots_max[slot_level] = progression.spell_slots_max.get(slot_level, 0) + 1
    progression.spell_slots[slot_level] = progression.spell_slots.get(slot_level, 0) + 1
    return True

def is_dead(progression):
    return progression.hp <= 0

def resurrect(progression):
    '''Bring a dead character back: half max HP (at least 1) and an XP
    penalty floored at the current level, so no level is ever lost.'''
    progression.hp = max(1, progression.max_hp // 2)
    progression.xp = max(xp_for_level(progression.level), progression.xp - RESURRECTION_XP_PENALTY)

# The STATE line the rules prompt requires at the end of every GM reply.
# Matching is tolerant of markdown decoration around the keyword and at the
# line's edges, for the same reason the summary header pattern is (see
# context._SECTION_PATTERN): the model decorates despite being told not to.
_STATE_LINE_PATTERN = re.compile(
    r'^[ \t*_#>\-]*STATE[ \t*_]*:[ \t*_]*(.*?)[ \t*_]*$',
    re.IGNORECASE | re.MULTILINE,
)

# Entry grammar, one pattern per change kind. Colons after the keyword are
# tolerated ("HP: -3"); anything that matches nothing is skipped.
_STATE_ENTRY_PATTERNS = [
    ('hp', re.compile(r'^HP\s*:?\s*([+-]?\d+)$', re.IGNORECASE)),
    ('xp', re.compile(r'^XP\s*:?\s*([+-]?\d+)$', re.IGNORECASE)),
    ('slot', re.compile(r'^SLOTS?\s*:?\s*(\d)\s*:?\s*([+-]?\d+)$', re.IGNORECASE)),
    ('gain', re.compile(r'^GAINS?\s*:?\s+(.+)$', re.IGNORECASE)),
    ('lose', re.compile(r'^LOSES?\s*:?\s+(.+)$', re.IGNORECASE)),
]

def parse_state_changes(response):
    '''
    Find the GM's STATE line(s) in a response. Returns (clean_text, changes):
    the response with every STATE line stripped, and the last line's parsed
    entries as a list of tuples - ('hp', delta), ('xp', delta),
    ('gain', item), ('lose', item), ('slot', slot_level, delta).
    "none", blank, and unparseable entries are skipped; a response with no
    STATE line at all returns it unchanged with no changes.
    '''
    matches = list(_STATE_LINE_PATTERN.finditer(response))
    if not matches:
        return response, []

    clean = _STATE_LINE_PATTERN.sub('', response)
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()

    changes = []
    for raw_entry in re.split(r'[;,]', matches[-1].group(1)):
        entry = raw_entry.strip(' \t*_')
        if not entry or entry.lower() == 'none':
            continue
        for kind, pattern in _STATE_ENTRY_PATTERNS:
            match = pattern.match(entry)
            if not match:
                continue
            if kind in ('hp', 'xp'):
                changes.append((kind, int(match.group(1))))
            elif kind == 'slot':
                changes.append((kind, match.group(1), int(match.group(2))))
            else:
                changes.append((kind, match.group(1).strip()))
            break
    return clean, changes

def apply_state_changes(progression, changes):
    '''
    Apply parsed STATE-line changes to the progression, clamping to valid
    ranges: HP to [0, max_hp], XP no lower than the current level's floor
    (so the model can never de-level the character), spell slots to
    [0, maximum] and only for slot levels the character actually has.
    Losing an item not held, like every other invalid entry, is ignored.
    Mutates in place; the caller checks for level-ups and death afterwards.
    '''
    for change in changes:
        kind = change[0]
        if kind == 'hp':
            progression.hp = max(0, min(progression.max_hp, progression.hp + change[1]))
        elif kind == 'xp':
            progression.xp = max(xp_for_level(progression.level), progression.xp + change[1])
        elif kind == 'gain':
            progression.inventory.append(change[1])
        elif kind == 'lose':
            wanted = change[1].lower()
            for held in progression.inventory:
                if held.lower() == wanted:
                    progression.inventory.remove(held)
                    break
        elif kind == 'slot':
            slot_level, delta = change[1], change[2]
            if slot_level in progression.spell_slots_max:
                maximum = progression.spell_slots_max[slot_level]
                progression.spell_slots[slot_level] = max(
                    0, min(maximum, progression.spell_slots[slot_level] + delta))

def prompt_starting_spell_slots():
    '''
    New-game question: how many level-1 spell slots the character starts
    with (0 or blank for a non-caster). Returns the count.
    '''
    print('\nSpell slots are your budget for casting spells: each spell cast spends one slot of '
          'the matching level, and the GM will not let you cast once you have none left. '
          'They refill when you level up, and you can gain more as level-up rewards.')
    print('If your character casts spells, choose how many level-1 slots they start with (2 is typical); '
          'if not, enter 0 - you can still become a caster later.')
    while True:
        raw = input('Starting level-1 spell slots (0 or blank for a non-caster): ').strip()
        if not raw:
            return 0
        try:
            value = int(raw)
        except ValueError:
            print('Please enter a whole number.')
            continue
        if 0 <= value <= 9:
            return value
        print('Please enter a number between 0 and 9.')

def prompt_level_up(progression, character):
    '''
    Interactive level-up flow: applies every pending level one at a time,
    each with a class-feature choice (stat increase, named feature, or a
    new spell slot). Mutates progression and character in place.
    '''
    while pending_level_ups(progression) > 0:
        level_up(progression)
        print(f'\nLevel up! You are now level {progression.level}: '
              f'max HP is {progression.max_hp}, you are fully healed and your spell slots are restored.')
        print('Choose your class feature for this level:')
        print('  1. Increase a stat by 1')
        print('  2. Learn a new class feature')
        print('  3. Gain a spell slot')
        while True:
            choice = input('> ').strip()
            if choice == '1':
                for stat in STAT_NAMES:
                    print(f'  {stat}: {character.stats[stat]}')
                stat = input('Stat to increase: ').strip().title()
                if increase_stat(character, stat):
                    print(f'{stat} is now {character.stats[stat]}.')
                    break
                print(f'Cannot increase "{stat}" - pick a listed stat that is below {STAT_MAX}.')
                continue
            if choice == '2':
                feature = input('Describe the feature (a short phrase, e.g. "Second Wind"): ').strip()
                if feature:
                    grant_feature(progression, feature)
                    print(f'Learned "{feature}".')
                    break
                print('The feature needs a name.')
                continue
            if choice == '3':
                slot_level = input('Spell slot level (1-9): ').strip()
                if grant_spell_slot(progression, slot_level):
                    print(f'You now have {progression.spell_slots_max[slot_level]} level-{slot_level} spell slot(s).')
                    break
                print('Please enter a slot level from 1 to 9.')
                continue
            print('Please enter 1, 2, or 3.')

def prompt_death(progression):
    '''
    Death menu, shown when HP reaches 0: resurrect (RESURRECTION_XP_PENALTY
    XP, revived at half max HP) or let the story end. Returns True after
    resurrecting, False to end - the caller saves and exits on False.
    '''
    print('\nYour character has fallen - their HP has reached 0.')
    while True:
        choice = input(f'Type "resurrect" to return to life (costs {RESURRECTION_XP_PENALTY} XP, '
                       'revived at half HP) or "end" to end the story here: ').strip().lower()
        if choice == 'resurrect':
            resurrect(progression)
            print(f'You are pulled back from death with {progression.hp}/{progression.max_hp} HP.')
            return True
        if choice == 'end':
            return False
        print('Please type "resurrect" or "end".')
