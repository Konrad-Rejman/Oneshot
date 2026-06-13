'''
Character progression: HP, inventory, XP, levels, and death (ROADMAP 2.3).

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

import ui
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

@dataclass
class Progression:
    max_hp: int
    hp: int
    level: int = 1
    xp: int = 0
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
        for entry in list(self.inventory) + list(self.features):
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError(f'Inventory and feature entries must be non-empty strings, got {entry!r}')

    def to_dict(self):
        return {
            'max_hp': self.max_hp,
            'hp': self.hp,
            'level': self.level,
            'xp': self.xp,
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
            inventory=list(data['inventory']),
            features=list(data['features']),
        )

    def to_prompt(self):
        '''
        Render the current state as a plain-text STATUS block appended to the
        system prompt each turn (like the character sheet), so the model can
        reference HP and items accurately.
        '''
        if self.level >= MAX_LEVEL:
            xp_text = f'XP: {self.xp} (maximum level reached)'
        else:
            xp_text = f'XP: {self.xp} (level {self.level + 1} at {xp_for_level(self.level + 1)})'
        inventory_text = ', '.join(self.inventory) if self.inventory else 'nothing'
        features_text = ', '.join(self.features) if self.features else 'none'
        return (
            'STATUS:\n'
            f'HP: {self.hp}/{self.max_hp}\n'
            f'Level: {self.level}\n'
            f'{xp_text}\n'
            f'Inventory: {inventory_text}\n'
            f'Features: {features_text}'
        )

def starting_max_hp(constitution):
    return STARTING_HP_BASE + constitution

def new_progression(character):
    '''
    Fresh level-1 progression for the given Character: max HP from
    Constitution, empty inventory.
    '''
    hp = starting_max_hp(character.stats['Constitution'])
    return Progression(max_hp=hp, hp=hp)

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
    '''
    Advance one level: +HP_PER_LEVEL max HP, fully healed. The class-feature
    choice is applied separately (increase_stat / grant_feature). Mutates in
    place.
    '''
    progression.level += 1
    progression.max_hp += HP_PER_LEVEL
    progression.hp = progression.max_hp

def increase_stat(character, stat):
    '''
    Level-up choice: +1 to the named stat, capped at STAT_MAX.
    Returns False (and changes nothing) for an unknown or maxed stat.
    '''
    if stat not in character.stats or character.stats[stat] >= STAT_MAX:
        return False
    character.stats[stat] += 1
    return True

def grant_feature(progression, feature):
    '''
    Level-up choice: record a named class feature, surfaced to the model
    in the STATUS block.
    '''
    progression.features.append(feature)

def is_dead(progression):
    return progression.hp <= 0

def resurrect(progression):
    '''
    Bring a dead character back: half max HP (at least 1) and an XP
    penalty floored at the current level, so no level is ever lost.
    '''
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
    ('gain', re.compile(r'^GAINS?\s*:?\s+(.+)$', re.IGNORECASE)),
    ('lose', re.compile(r'^LOSES?\s*:?\s+(.+)$', re.IGNORECASE)),
]

def parse_state_changes(response):
    '''
    Find the GM's STATE line(s) in a response. Returns (clean_text, changes):
    the response with every STATE line stripped, and the last line's parsed
    entries as a list of tuples - ('hp', delta), ('xp', delta),
    ('gain', item), ('lose', item).
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
            else:
                changes.append((kind, match.group(1).strip()))
            break
    return clean, changes

def apply_state_changes(progression, changes):
    '''
    Apply parsed STATE-line changes to the progression, clamping to valid
    ranges: HP to [0, max_hp], XP no lower than the current level's floor
    (so the model can never de-level the character).
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

def prompt_level_up(progression, character):
    '''
    Interactive level-up flow: applies every pending level one at a time,
    each with a class-feature choice (stat increase or a named feature).
    Mutates progression and character in place.
    '''
    while pending_level_ups(progression) > 0:
        level_up(progression)
        ui.event(f'\nLevel up! You are now level {progression.level}: '
                 f'max HP is {progression.max_hp} and you are fully healed.')
        ui.menu('Choose your class feature for this level:',
                ['Increase a stat by 1', 'Learn a new class feature'])
        while True:
            choice = ui.ask().strip()
            if choice == '1':
                for stat in STAT_NAMES:
                    ui.system(f'  {stat}: {character.stats[stat]}')
                stat = ui.ask('Stat to increase:').strip().title()
                if increase_stat(character, stat):
                    ui.system(f'{stat} is now {character.stats[stat]}.')
                    break
                ui.warn(f'Cannot increase "{stat}" - pick a listed stat that is below {STAT_MAX}.')
                continue
            if choice == '2':
                feature = ui.ask('Describe the feature (a short phrase, e.g. "Second Wind"):').strip()
                if feature:
                    grant_feature(progression, feature)
                    ui.system(f'Learned "{feature}".')
                    break
                ui.warn('The feature needs a name.')
                continue
            ui.warn('Please enter 1 or 2.')

def prompt_death(progression):
    '''
    Death menu, shown when HP reaches 0: resurrect (RESURRECTION_XP_PENALTY
    XP, revived at half max HP) or let the story end. Returns True after
    resurrecting, False to end - the caller saves and exits on False.
    '''
    ui.event('\nYour character has fallen - their HP has reached 0.')
    while True:
        choice = ui.ask(f'Type "resurrect" to return to life (costs {RESURRECTION_XP_PENALTY} XP, '
                        'revived at half HP) or "end" to end the story here:').strip().lower()
        if choice == 'resurrect':
            resurrect(progression)
            ui.event(f'You are pulled back from death with {progression.hp}/{progression.max_hp} HP.')
            return True
        if choice == 'end':
            return False
        ui.warn('Please type "resurrect" or "end".')
