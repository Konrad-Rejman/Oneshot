import json, os
from dataclasses import dataclass, field

import ownership
import ui

CHARACTERS_FILE = 'characters.json'
DEFAULT_NAME = 'Default'

# The six SRD ability names on a clean 1-10 scale - no derived modifiers.
# 5 is an average person, 10 is peak mortal capability. The GM model reads
# the numbers directly (see the CHARACTER section of the rules prompt).
STAT_NAMES = ['Strength', 'Dexterity', 'Constitution', 'Intelligence', 'Wisdom', 'Charisma']
STAT_MIN = 1
STAT_MAX = 10

# Phrases describing different stat-point values
STAT_PHRASES = {
    1: 'pathetic',
    2: 'pathetic',
    3: 'below average',
    4: 'below average',
    5: 'average',
    6: 'above average',
    7: 'above average',
    8: 'incredible',
    9: 'incredible',
    10: 'demi-god'
}

# Point pool for interactive character creation: six stats averaging 6 -
# an ordinary person (average 5) with a little hero headroom.
STAT_POOL = 36

def describe_stat(value):
    '''
    Map a stat value (1-10) to a short qualitative phrase used in the
    character sheet shown to the GM model, e.g. "above average" or "feeble".
    The phrase shades how the model narrates actions that lean on the stat.
    '''
    return STAT_PHRASES[value]

@dataclass
class Character:
    name: str
    race: str
    char_class: str
    background: str
    stats: dict = field(default_factory=dict)

    def __post_init__(self):
        missing = [stat for stat in STAT_NAMES if stat not in self.stats]
        if missing:
            raise ValueError(f'Missing stats: {", ".join(missing)}')
        unknown = [stat for stat in self.stats if stat not in STAT_NAMES]
        if unknown:
            raise ValueError(f'Unknown stats: {", ".join(unknown)}')
        for stat in STAT_NAMES:
            value = self.stats[stat]
            if not isinstance(value, int) or isinstance(value, bool) or not (STAT_MIN <= value <= STAT_MAX):
                raise ValueError(f'{stat} must be an integer between {STAT_MIN} and {STAT_MAX}, got {value!r}')

    def to_dict(self):
        return {
            'name': self.name,
            'race': self.race,
            'char_class': self.char_class,
            'background': self.background,
            'stats': dict(self.stats),
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data['name'],
            race=data['race'],
            char_class=data['char_class'],
            background=data['background'],
            stats=dict(data['stats']),
        )

    def to_prompt(self):
        '''
        Render the character as a plain-text block appended to the system
        prompt each turn, alongside the pre-rolled D20s.
        '''
        stat_lines = '\n'.join(
            f'{stat} {self.stats[stat]}/{STAT_MAX} ({describe_stat(self.stats[stat])})'
            for stat in STAT_NAMES
        )
        return (
            'CHARACTER SHEET:\n'
            f'Name: {self.name}\n'
            f'Race: {self.race}\n'
            f'Class: {self.char_class}\n'
            f'Background: {self.background}\n'
            f'Stats ({STAT_MIN}-{STAT_MAX} scale, 5 is an average person):\n'
            f'{stat_lines}'
        )

# The always-available starting character, matching the default scenario's
# amnesiac opening (low Wisdom nods to the failed Wisdom check in the
# opening scene). Stats sum to STAT_POOL.
DEFAULT_CHARACTER = Character(
    name='The Stranger',
    race='Human',
    char_class='Wanderer',
    background="An amnesiac survivor of a caravan ambush, carrying only a silver wolf's-head medallion.",
    stats={
        'Strength': 6,
        'Dexterity': 7,
        'Constitution': 6,
        'Intelligence': 6,
        'Wisdom': 5,
        'Charisma': 6,
    },
)

def load_characters():
    '''
    Return saved custom characters as a list of records, each a Character dict
    plus an 'owner' (the creator's username). Characters are shared between
    users; ownership only gates editing/deleting (ownership.py).

    The pre-ownership format was a {name: character_dict} mapping; it is read
    transparently as records with owner ownership.UNOWNED, which
    migrate_characters() then claims for the first user to run.
    '''
    if not os.path.exists(CHARACTERS_FILE):
        return []
    with open(CHARACTERS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [{**payload, 'name': name, 'owner': ownership.UNOWNED}
                for name, payload in data.items()]
    return data

def _write_characters(records):
    with open(CHARACTERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

def migrate_characters(user):
    '''Claim every pre-ownership character for user; see load_characters.'''
    if not os.path.exists(CHARACTERS_FILE):
        return
    records = load_characters()
    ownership.migrate_records(records, user)
    _write_characters(records)

def add_character(character, owner):
    records = load_characters()
    records.append({**character.to_dict(), 'owner': owner})
    _write_characters(records)

def delete_character(name, owner):
    '''Remove owner's character named name; other users' records are untouched.'''
    records = load_characters()
    kept = [r for r in records
            if not (r['name'] == name and ownership.is_owner(r, owner))]
    if len(kept) != len(records):
        _write_characters(kept)

def _read_stat_allocation():
    '''
    Interactively allocate STAT_POOL points across the six stats,
    STAT_MIN-STAT_MAX each. Returns a stats dict.
    '''
    ui.system(f'\nAssign your stats: {STAT_POOL} points across {len(STAT_NAMES)} stats, each {STAT_MIN}-{STAT_MAX} (5 is an average person).')
    while True:
        stats = {}
        remaining = STAT_POOL
        for i, stat in enumerate(STAT_NAMES):
            stats_left = len(STAT_NAMES) - i
            while True:
                try:
                    value = int(ui.ask(f'{stat} ({remaining} points left):').strip())
                except ValueError:
                    ui.warn('Please enter a whole number.')
                    continue
                if not (STAT_MIN <= value <= STAT_MAX):
                    ui.warn(f'Value must be between {STAT_MIN} and {STAT_MAX}.')
                    continue
                # Leave at least STAT_MIN for each remaining stat, and don't
                # bank more points than the remaining stats can absorb.
                others = stats_left - 1
                if remaining - value < others * STAT_MIN:
                    ui.warn('That leaves too few points for the remaining stats.')
                    continue
                if remaining - value > others * STAT_MAX:
                    ui.warn('That banks more points than the remaining stats can hold; spend more.')
                    continue
                stats[stat] = value
                remaining -= value
                break
        return stats

def _create_character(user):
    '''
    Prompt for and save a new character owned by user. Names must be unique
    among user's own characters (other users may reuse the name). Returns
    nothing; warns and saves nothing on invalid input.
    '''
    own_names = {r['name'] for r in load_characters() if ownership.is_owner(r, user)}
    name = ui.ask('Character name:').strip()
    if not name or name == DEFAULT_NAME or name in own_names:
        ui.warn(f'Please choose a name you have not used, other than "{DEFAULT_NAME}".')
        return

    race = ui.ask('Race:').strip()
    char_class = ui.ask('Class:').strip()
    background = ui.ask('Background (a sentence or two):').strip()
    if not (race and char_class and background):
        ui.warn('A character needs a race, class and background; nothing was saved.')
        return

    stats = _read_stat_allocation()
    character = Character(name=name, race=race, char_class=char_class,
                          background=background, stats=stats)
    add_character(character, user)
    ui.system(f'Saved character "{name}".')

def _delete_character(user):
    '''Pick one of user's own characters from a menu and delete it on confirm.'''
    own = [r for r in load_characters() if ownership.is_owner(r, user)]
    if not own:
        ui.warn('You have no saved characters to delete.')
        return
    options = [(r['name'], r['name']) for r in own] + [('Cancel', None)]
    name = ui.select('Delete which character?', options)
    if name is None:
        return
    confirm = ui.ask(f'Type "yes" to permanently delete "{name}":').strip().lower()
    if confirm == 'yes':
        delete_character(name, user)
        ui.system(f'Deleted character "{name}".')
    else:
        ui.system('Cancelled.')

def choose_character(user):
    '''
    Interactively let user pick, create, or delete a character. Every user's
    characters are listed (tagged with their creator); the show-others toggle
    starts hidden so the menu opens with only user's own plus the default.
    Creating and deleting only ever touch user's own characters.

    Returns the Character chosen to play.
    '''
    show_others = False
    while True:
        records = load_characters()
        visible = ownership.visible_records(records, user, show_others)
        toggle_mark = 'x' if show_others else ' '

        options = [(f'{DEFAULT_NAME} (built-in)', ('default', None))]
        options += [(ownership.entry_label(r), ('play', r)) for r in visible]
        options.append((f"[{toggle_mark}] Show other users' characters", ('toggle', None)))
        options.append(('New character', ('new', None)))
        if any(ownership.is_owner(r, user) for r in records):
            options.append(('Delete one of my characters', ('delete', None)))

        kind, record = ui.select('Characters:', options)

        if kind == 'default':
            return DEFAULT_CHARACTER
        if kind == 'play':
            return Character.from_dict(record)
        if kind == 'toggle':
            show_others = not show_others
        elif kind == 'new':
            _create_character(user)
        elif kind == 'delete':
            _delete_character(user)

def manage_characters(user):
    '''
    Main-menu management screen: create or delete user's own characters, then
    return. Unlike choose_character there is no play/select outcome - starting
    a game picks a character separately.
    '''
    while True:
        options = [('New character', 'new')]
        if any(ownership.is_owner(r, user) for r in load_characters()):
            options.append(('Delete one of my characters', 'delete'))
        options.append(('Back', 'back'))

        kind = ui.select('Manage characters:', options)

        if kind == 'new':
            _create_character(user)
        elif kind == 'delete':
            _delete_character(user)
        else:
            return
