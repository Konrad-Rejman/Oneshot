import json, os
from dataclasses import dataclass, field

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
    '''Return saved custom characters as {name: character_dict}.'''
    if not os.path.exists(CHARACTERS_FILE):
        return {}
    with open(CHARACTERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _write_characters(characters):
    with open(CHARACTERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(characters, f, indent=2, ensure_ascii=False)

def add_character(name, character):
    characters = load_characters()
    characters[name] = character.to_dict()
    _write_characters(characters)

def delete_character(name):
    characters = load_characters()
    if name in characters:
        del characters[name]
        _write_characters(characters)

def _read_stat_allocation():
    '''
    Interactively allocate STAT_POOL points across the six stats,
    STAT_MIN-STAT_MAX each. Returns a stats dict.
    '''
    print(f'\nAssign your stats: {STAT_POOL} points across {len(STAT_NAMES)} stats, each {STAT_MIN}-{STAT_MAX} (5 is an average person).')
    while True:
        stats = {}
        remaining = STAT_POOL
        for i, stat in enumerate(STAT_NAMES):
            stats_left = len(STAT_NAMES) - i
            while True:
                try:
                    value = int(input(f'{stat} ({remaining} points left): ').strip())
                except ValueError:
                    print('Please enter a whole number.')
                    continue
                if not (STAT_MIN <= value <= STAT_MAX):
                    print(f'Value must be between {STAT_MIN} and {STAT_MAX}.')
                    continue
                # Leave at least STAT_MIN for each remaining stat, and don't
                # bank more points than the remaining stats can absorb.
                others = stats_left - 1
                if remaining - value < others * STAT_MIN:
                    print('That leaves too few points for the remaining stats.')
                    continue
                if remaining - value > others * STAT_MAX:
                    print('That banks more points than the remaining stats can hold; spend more.')
                    continue
                stats[stat] = value
                remaining -= value
                break
        return stats

def choose_character():
    '''
    Interactively let the player pick, create, or delete a character.

    Returns the Character chosen to play.
    '''
    while True:
        custom = load_characters()
        names = [DEFAULT_NAME] + list(custom.keys())

        print('\nCharacters:')
        for i, name in enumerate(names, start=1):
            print(f'  {i}. {name}')
        print('Enter a number to play that character, "new" to create one, or "delete" to remove one.')

        choice = input('> ').strip()
        command = choice.lower()

        if command == 'new':
            name = input('Character name: ').strip()
            if not name or name == DEFAULT_NAME or name in custom:
                print(f'Please choose a unique name other than "{DEFAULT_NAME}".')
                continue

            race = input('Race: ').strip()
            char_class = input('Class: ').strip()
            background = input('Background (a sentence or two): ').strip()
            if not (race and char_class and background):
                print('A character needs a race, class and background; nothing was saved.')
                continue

            stats = _read_stat_allocation()
            character = Character(name=name, race=race, char_class=char_class,
                                  background=background, stats=stats)
            add_character(name, character)
            print(f'Saved character "{name}".')
            continue

        if command == 'delete':
            if not custom:
                print('There are no saved characters to delete.')
                continue
            name = input('Name of the character to delete: ').strip()
            if name not in custom:
                print(f'No saved character named "{name}".')
                continue
            confirm = input(f'Type "yes" to permanently delete "{name}": ').strip().lower()
            if confirm == 'yes':
                delete_character(name)
                print(f'Deleted character "{name}".')
            else:
                print('Cancelled.')
            continue

        try:
            selected = names[int(choice) - 1]
        except (ValueError, IndexError):
            print('Please enter a listed number, "new", or "delete".')
            continue

        if selected == DEFAULT_NAME:
            return DEFAULT_CHARACTER

        return Character.from_dict(custom[selected])
