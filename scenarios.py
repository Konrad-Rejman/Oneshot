import json, os, re

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

# The original hardcoded opening scene and summary, kept as the always-available
# starting point. Can later add scenarios here the same way custom ones are added 
# - by handing {'startMessage', 'summary'} to add_scenario() once it can generate
# them from a character sheet.
DEFAULT_SCENARIO = {
    'startMessage': '''You stir as the first light of dawn filters through a canopy of tangled branches. The air is cold and damp, the scent of pine and earth filling your lungs. When you sit up, you find yourself lying on a rough, moss-covered road that cuts through the forest like a scar. The twisted wreckage of a caravan lies beside you.

Your head throbs as you try to remember what has happened, rolling a Wisdom check you roll a... 9 and realize you have no memory of who you are, how you got here, or why the caravan is ruined.

The only clue is a faint, silver-etched token clutched in your hand, a small medallion shaped like a stylized wolf\'s head, warm to the touch. As you stare at the wreckage, you notice a faint trail of disturbed leaves and broken twigs snaking away from the caravan into the dense forest.''',

    'summary': 'OVERALL STORY: The player must find civilization and uncover clues as to their identity along the way, they should also be given the chance to help the people they encounter by fighting monsters.\n\nCURRENT QUEST: The player is inside a forest beside a caravan which has been destroyed, a trail leads from the wreckage into the forest. The player rolled a Wisdom check resulting in a 9, revealing no clues as to their identity. The player must find a way out of the forest.\n\nPLAYER STATUS: The player has woken up with no memories and nothing but the clothes on their back and a small silver medallion shaped like a stylized wolf\'s head.'
}

def load_scenarios():
    '''Return saved custom scenarios as {name: {'startMessage': ..., 'summary': ...}}.'''
    if not os.path.exists(SCENARIOS_FILE):
        return {}
    with open(SCENARIOS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _write_scenarios(scenarios):
    with open(SCENARIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(scenarios, f, indent=2, ensure_ascii=False)

def add_scenario(name, start_message, summary):
    scenarios = load_scenarios()
    scenarios[name] = {'startMessage': start_message, 'summary': summary}
    _write_scenarios(scenarios)

def edit_scenario(name, start_message, summary):
    scenarios = load_scenarios()
    if name not in scenarios:
        raise KeyError(name)
    scenarios[name] = {'startMessage': start_message, 'summary': summary}
    _write_scenarios(scenarios)

def delete_scenario(name):
    scenarios = load_scenarios()
    if name in scenarios:
        del scenarios[name]
        _write_scenarios(scenarios)

def _read_multiline(prompt_label, keep_current=None):
    '''
    Read multi-line text from the terminal, terminated by a line containing only END.

    Blank lines are preserved so multi-paragraph text can be entered. If
    keep_current is given, submitting nothing returns it unchanged (used when
    editing a scenario so a field can be left as-is).
    '''
    print(f'\n{prompt_label}')
    print('Type or paste the text - blank lines are fine. Finish with a line containing only END.')
    if keep_current is not None:
        print('(Submit nothing to keep the current text.)')

    lines = []
    while True:
        line = input()
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
    print('\nThe summary tracks the story in three sections, which get updated automatically as you play:')
    for header, description in SUMMARY_SECTIONS:
        print(f'  {header}: {description}')
    print("You'll be asked for each section in turn - they'll be combined into the summary for you.")

    current_sections = None
    if keep_current is not None:
        current_sections = _split_summary(keep_current)
        if current_sections is None:
            print("(The current summary doesn't split cleanly into those sections, so you'll write each one fresh.)")

    sections = {}
    for header, description in SUMMARY_SECTIONS:
        keep = current_sections[header] if current_sections else None
        sections[header] = _read_multiline(f'{header}: {description}', keep_current=keep)

    if not all(sections.values()):
        return None

    return '\n\n'.join(f'{header}: {sections[header]}' for header, _ in SUMMARY_SECTIONS)

def _print_menu(names):
    print('\nStarting scenarios:')
    for i, name in enumerate(names, start=1):
        print(f'  {i}. {name}')
    print('Enter a number to start there, "new" to write one, "edit" to change a saved one, or "delete" to remove one.')

def choose_scenario():
    '''
    Interactively let the player pick, create, edit, or delete a starting scenario.

    Returns (start_message, summary) for the scenario chosen to play.
    '''
    while True:
        custom = load_scenarios()
        names = [DEFAULT_NAME] + list(custom.keys())

        _print_menu(names)
        choice = input('> ').strip()
        command = choice.lower()

        if command == 'new':
            name = input('Name for the new scenario: ').strip()
            if not name or name == DEFAULT_NAME or name in custom:
                print(f'Please choose a unique name other than "{DEFAULT_NAME}".')
                continue

            start_message = _read_multiline('Write the opening scene the GM will narrate first:')
            summary = _read_summary()

            if not start_message or not summary:
                print('A scenario needs both an opening scene and a summary; nothing was saved.')
                continue

            add_scenario(name, start_message, summary)
            print(f'Saved scenario "{name}".')
            continue

        if command == 'edit':
            if not custom:
                print('There are no saved scenarios to edit.')
                continue
            name = input('Name of the scenario to edit: ').strip()
            if name not in custom:
                print(f'No saved scenario named "{name}".')
                continue

            current = custom[name]
            start_message = _read_multiline('New opening scene:', keep_current=current['startMessage'])
            summary = _read_summary(keep_current=current['summary'])

            if summary is None:
                print('Each section needs some text; the scenario was left unchanged.')
                continue

            edit_scenario(name, start_message, summary)
            print(f'Updated scenario "{name}".')
            continue

        if command == 'delete':
            if not custom:
                print('There are no saved scenarios to delete.')
                continue
            name = input('Name of the scenario to delete: ').strip()
            if name not in custom:
                print(f'No saved scenario named "{name}".')
                continue
            confirm = input(f'Type "yes" to permanently delete "{name}": ').strip().lower()
            if confirm == 'yes':
                delete_scenario(name)
                print(f'Deleted scenario "{name}".')
            else:
                print('Cancelled.')
            continue

        try:
            selected = names[int(choice) - 1]
        except (ValueError, IndexError):
            print('Please enter a listed number, "new", "edit", or "delete".')
            continue

        if selected == DEFAULT_NAME:
            return DEFAULT_SCENARIO['startMessage'], DEFAULT_SCENARIO['summary']

        chosen = custom[selected]
        return chosen['startMessage'], chosen['summary']
