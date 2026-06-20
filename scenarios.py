import json, os, re

import ownership
import ui

SCENARIOS_FILE = 'scenarios.json'
DEFAULT_NAME = 'Default'

# The three sections the in-game summariser expects, with a plain-language
# explanation of what belongs in each one shown to the player before they write them.
SUMMARY_SECTIONS = [
    ('OVERALL STORY', 'the long-term arc - what the player is ultimately trying to do, and the wider situation they are in'),
    ('CURRENT QUEST', 'what is happening right now - the immediate goal or problem directly in front of the player'),
    ('PLAYER STATUS', "the player's current state - memories, health, possessions, or anything else notable about who they are right now"),
]

_SUMMARY_HEADERS = [header for header, _ in SUMMARY_SECTIONS]

_SECTION_PATTERN = re.compile(
    r'(' + '|'.join(_SUMMARY_HEADERS) + r')\s*:\s*(.*?)(?=(?:' + '|'.join(_SUMMARY_HEADERS) + r')\s*:|\Z)',
    re.IGNORECASE | re.DOTALL
)

# The always-available default opening scene and summary. Generated openings
# (ROADMAP 1.2, pending) belong in add_scenario() as {'startMessage',
# 'summary'} dicts, the same shape custom scenarios use.
DEFAULT_SCENARIO = {
    'startMessage': '''You stir as the first light of dawn filters through a canopy of tangled branches. The air is cold and damp, the scent of pine and earth filling your lungs. When you sit up, you find yourself lying on a rough, moss-covered road that cuts through the forest like a scar. The twisted wreckage of a caravan lies beside you.

Your head throbs as you try to remember what has happened, rolling a Wisdom check you roll a... 9 and realize you have no memory of who you are, how you got here, or why the caravan is ruined.

The only clue is a faint, silver-etched token clutched in your hand, a small medallion shaped like a stylized wolf\'s head, warm to the touch. As you stare at the wreckage, you notice a faint trail of disturbed leaves and broken twigs snaking away from the caravan into the dense forest.''',

    'summary': 'OVERALL STORY: The player must find civilization and uncover clues as to their identity along the way, they should also be given the chance to help the people they encounter by fighting monsters.\n\nCURRENT QUEST: The player is inside a forest beside a caravan which has been destroyed, a trail leads from the wreckage into the forest. The player rolled a Wisdom check resulting in a 9, revealing no clues as to their identity. The player must find a way out of the forest.\n\nPLAYER STATUS: The player has woken up with no memories and nothing but the clothes on their back and a small silver medallion shaped like a stylized wolf\'s head.'
}

def load_scenarios():
    '''
    Return saved custom scenarios as a list of records, each
    {'name', 'owner', 'startMessage', 'summary'}. Scenarios are shared between
    users; ownership only gates editing/deleting (ownership.py).

    The pre-ownership format was a {name: {'startMessage', 'summary'}} mapping;
    it is read transparently as records with owner ownership.UNOWNED, which
    migrate_scenarios() then claims for the first user to run.
    '''
    if not os.path.exists(SCENARIOS_FILE):
        return []
    with open(SCENARIOS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [{**payload, 'name': name, 'owner': ownership.UNOWNED}
                for name, payload in data.items()]
    return data

def _write_scenarios(records):
    with open(SCENARIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

def migrate_scenarios(user):
    '''Claim every pre-ownership scenario for user; see load_scenarios.'''
    if not os.path.exists(SCENARIOS_FILE):
        return
    records = load_scenarios()
    ownership.migrate_records(records, user)
    _write_scenarios(records)

def _find(records, name, owner):
    '''Index of owner's scenario named name, or None.'''
    for i, r in enumerate(records):
        if r['name'] == name and ownership.is_owner(r, owner):
            return i
    return None

def add_scenario(name, start_message, summary, owner):
    records = load_scenarios()
    records.append({'name': name, 'owner': owner,
                    'startMessage': start_message, 'summary': summary})
    _write_scenarios(records)

def edit_scenario(name, start_message, summary, owner):
    '''Overwrite owner's scenario named name; raises KeyError if they own none.'''
    records = load_scenarios()
    i = _find(records, name, owner)
    if i is None:
        raise KeyError(name)
    records[i] = {'name': name, 'owner': owner,
                  'startMessage': start_message, 'summary': summary}
    _write_scenarios(records)

def delete_scenario(name, owner):
    '''Remove owner's scenario named name; other users' records are untouched.'''
    records = load_scenarios()
    i = _find(records, name, owner)
    if i is not None:
        del records[i]
        _write_scenarios(records)

def _read_multiline(prompt_label, keep_current=None):
    '''
    Read multi-line text from the terminal, terminated by a line containing only END.

    Blank lines are preserved so multi-paragraph text can be entered. If
    keep_current is given, submitting nothing returns it unchanged (used when
    editing a scenario so a field can be left as-is).
    '''
    ui.heading(prompt_label)
    ui.system('Type or paste the text - blank lines are fine. Finish with a line containing only END.')
    if keep_current is not None:
        ui.system('(Submit nothing to keep the current text.)')

    lines = []
    while True:
        line = ui.read_line()
        if line.strip() == 'END':
            break
        lines.append(line)

    text = '\n'.join(lines).strip()
    if not text and keep_current is not None:
        return keep_current
    return text

def _split_summary(text):
    '''
    Best-effort split of an existing summary into {header: body}.
    Returns None if it doesn't cleanly contain all three expected sections.
    '''
    found = {}
    for match in _SECTION_PATTERN.finditer(text):
        header = match.group(1).upper()
        if header in _SUMMARY_HEADERS:
            found[header] = match.group(2).strip()

    if all(header in found for header in _SUMMARY_HEADERS):
        return found
    return None

def _read_summary(keep_current=None):
    '''
    Explain the three summary sections, then collect each one individually
    and combine them into the final summary text.

    Returns the combined summary, or None if some section ended up with no
    text and nothing to fall back on.
    '''
    ui.system('\nThe summary tracks the story in three sections, which get updated automatically as you play:')
    for header, description in SUMMARY_SECTIONS:
        ui.system(f'  {header}: {description}')
    ui.system("You'll be asked for each section in turn - they'll be combined into the summary for you.")

    current_sections = None
    if keep_current is not None:
        current_sections = _split_summary(keep_current)
        if current_sections is None:
            ui.system("(The current summary doesn't split cleanly into those sections, so you'll write each one fresh.)")

    sections = {}
    for header, description in SUMMARY_SECTIONS:
        keep = current_sections[header] if current_sections else None
        sections[header] = _read_multiline(f'{header}: {description}', keep_current=keep)

    if not all(sections.values()):
        return None

    return '\n\n'.join(f'{header}: {sections[header]}' for header, _ in SUMMARY_SECTIONS)

def _create_scenario(user):
    '''
    Prompt for and save a new scenario owned by user. Names must be unique among
    user's own scenarios (other users may reuse the name). Warns and saves
    nothing on invalid input.
    '''
    own_names = {r['name'] for r in load_scenarios() if ownership.is_owner(r, user)}
    name = ui.ask('Name for the new scenario:').strip()
    if not name or name == DEFAULT_NAME or name in own_names:
        ui.warn(f'Please choose a name you have not used, other than "{DEFAULT_NAME}".')
        return

    start_message = _read_multiline('Write the opening scene the GM will narrate first:')
    summary = _read_summary()
    if not start_message or not summary:
        ui.warn('A scenario needs both an opening scene and a summary; nothing was saved.')
        return

    add_scenario(name, start_message, summary, user)
    ui.system(f'Saved scenario "{name}".')

def _edit_scenario(user):
    '''Pick one of user's own scenarios and overwrite its opening/summary.'''
    own = [r for r in load_scenarios() if ownership.is_owner(r, user)]
    if not own:
        ui.warn('You have no saved scenarios to edit.')
        return
    options = [(r['name'], r) for r in own] + [('Cancel', None)]
    record = ui.select('Edit which scenario?', options)
    if record is None:
        return

    start_message = _read_multiline('New opening scene:', keep_current=record['startMessage'])
    summary = _read_summary(keep_current=record['summary'])
    if summary is None:
        ui.warn('Each section needs some text; the scenario was left unchanged.')
        return

    edit_scenario(record['name'], start_message, summary, user)
    ui.system(f'Updated scenario "{record["name"]}".')

def _delete_scenario(user):
    '''Pick one of user's own scenarios from a menu and delete it on confirm.'''
    own = [r for r in load_scenarios() if ownership.is_owner(r, user)]
    if not own:
        ui.warn('You have no saved scenarios to delete.')
        return
    options = [(r['name'], r['name']) for r in own] + [('Cancel', None)]
    name = ui.select('Delete which scenario?', options)
    if name is None:
        return
    confirm = ui.ask(f'Type "yes" to permanently delete "{name}":').strip().lower()
    if confirm == 'yes':
        delete_scenario(name, user)
        ui.system(f'Deleted scenario "{name}".')
    else:
        ui.system('Cancelled.')

def choose_scenario(user):
    '''
    Interactively let user pick, create, edit, or delete a starting scenario.
    Every user's scenarios are listed (tagged with their creator); the
    show-others toggle starts hidden so the menu opens with only user's own
    plus the default. Creating, editing and deleting only touch user's own.

    Returns (start_message, summary) for the scenario chosen to play.
    '''
    show_others = False
    while True:
        records = load_scenarios()
        visible = ownership.visible_records(records, user, show_others)
        toggle_mark = 'x' if show_others else ' '

        options = [(f'{DEFAULT_NAME} (built-in)', ('default', None))]
        options += [(ownership.entry_label(r), ('play', r)) for r in visible]
        options.append((f"[{toggle_mark}] Show other users' scenarios", ('toggle', None)))
        options.append(('New scenario', ('new', None)))
        if any(ownership.is_owner(r, user) for r in records):
            options.append(('Edit one of my scenarios', ('edit', None)))
            options.append(('Delete one of my scenarios', ('delete', None)))

        kind, record = ui.select('Starting scenarios:', options)

        if kind == 'default':
            return DEFAULT_SCENARIO['startMessage'], DEFAULT_SCENARIO['summary']
        if kind == 'play':
            return record['startMessage'], record['summary']
        if kind == 'toggle':
            show_others = not show_others
        elif kind == 'new':
            _create_scenario(user)
        elif kind == 'edit':
            _edit_scenario(user)
        elif kind == 'delete':
            _delete_scenario(user)

def manage_scenarios(user):
    '''
    Main-menu management screen: create, edit or delete user's own scenarios,
    then return. Unlike choose_scenario there is no play/select outcome -
    starting a game picks a scenario separately.
    '''
    while True:
        options = [('New scenario', 'new')]
        if any(ownership.is_owner(r, user) for r in load_scenarios()):
            options.append(('Edit one of my scenarios', 'edit'))
            options.append(('Delete one of my scenarios', 'delete'))
        options.append(('Back', 'back'))

        kind = ui.select('Manage scenarios:', options)

        if kind == 'new':
            _create_scenario(user)
        elif kind == 'edit':
            _edit_scenario(user)
        elif kind == 'delete':
            _delete_scenario(user)
        else:
            return
