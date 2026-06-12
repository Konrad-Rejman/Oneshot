'''Named save slots, startup load menu, and transcript export (ROADMAP 2.2).

A save slot is a single JSON file in SAVES_DIR carrying the same state keys
as backup.pkl ('User', 'Chat Logs', 'Context Logs', 'Tokens', 'Playtime',
'Memory', 'Summary', 'Character', 'Progression'), plus 'Version' and 'Name'
added on write. Version history:
- 1: the original key set, no 'Progression'
- 2: ROADMAP 2.3 added the 'Progression' key (HP/spell slots/inventory/XP);
  version-1 saves load fine - main.py:restore_session falls back to a fresh
  progression when the key is absent
Future phases should keep extending the state dict with new keys and bumping
SAVE_VERSION rather than changing the existing keys, so old saves stay
loadable.
'''
import json, os, re, time

SAVES_DIR = 'saves'
EXPORTS_DIR = 'exports'
SAVE_VERSION = 2

EXPORT_FORMATS = ['txt', 'md']

def _sanitize_name(name):
    '''
    Make a save name filesystem-safe: keep ASCII letters, digits, spaces,
    dashes and underscores; drop everything else and collapse whitespace.
    Returns '' if nothing usable remains.
    '''
    cleaned = re.sub(r'[^\w \-]', '', name, flags=re.ASCII)
    return re.sub(r'\s+', ' ', cleaned).strip()

def _save_path(name):
    return os.path.join(SAVES_DIR, name + '.json')

def list_saves():
    '''Names of existing save slots, most recently saved first.'''
    if not os.path.isdir(SAVES_DIR):
        return []
    files = [f for f in os.listdir(SAVES_DIR) if f.endswith('.json')]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(SAVES_DIR, f)), reverse=True)
    return [os.path.splitext(f)[0] for f in files]

def save_session(name, state):
    '''
    Write session state to the named slot, creating SAVES_DIR if needed and
    overwriting any existing save with that name. state must hold the same
    JSON-serialisable keys as backup.pkl's dict (Character already as a dict,
    not a Character instance); 'Version' and 'Name' are added here.
    '''
    os.makedirs(SAVES_DIR, exist_ok=True)
    payload = {'Version': SAVE_VERSION, 'Name': name}
    payload.update(state)
    with open(_save_path(name), 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def load_session(name):
    '''Return the saved state dict for the named slot.'''
    with open(_save_path(name), 'r', encoding='utf-8') as f:
        return json.load(f)

def delete_save(name):
    if os.path.exists(_save_path(name)):
        os.remove(_save_path(name))

def format_transcript_text(chatlogs):
    '''
    Plain-text transcript: alternating GM:/PLAYER: blocks, the same format
    the sessions/ directory files use (system messages count as GM).
    '''
    parts = []
    for prompt in chatlogs:
        txt = prompt.get('content')
        if prompt.get('role') in ('system', 'assistant'):
            parts.append('GM:\n\n' + txt + '\n\n')
        elif prompt.get('role') == 'user':
            parts.append('PLAYER:\n\n' + txt + '\n\n')
    return ''.join(parts)

def format_transcript_markdown(chatlogs, title):
    '''
    Markdown transcript of the session. chatlogs is a list of
    {'role': 'system'|'assistant'|'user', 'content': str} dicts in story
    order; 'system' and 'assistant' messages are the GM, 'user' messages are
    the player. Returns the complete Markdown document as a string.
    '''
    md = f'# {title}\n'
    for line in chatlogs:
        if line['role'] in ('system', 'assistant'):
            md += f"\n### GM:\n\n{line['content']}\n"
        elif line['role'] == 'user':
            md += f"\n### PLAYER:\n\n{line['content']}\n"
    return md

def export_transcript(chatlogs, name, fmt):
    '''
    Write the transcript to EXPORTS_DIR/<name>.<fmt>, where fmt is 'txt' or
    'md', creating the directory if needed. Returns the written path.
    '''
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f'Unknown export format {fmt!r}; expected one of {EXPORT_FORMATS}')
    if fmt == 'txt':
        text = format_transcript_text(chatlogs)
    else:
        text = format_transcript_markdown(chatlogs, title=name)
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f'{name}.{fmt}')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path

def prompt_session_save(state):
    '''
    Exit-time prompt: offer to keep the finished session in a named slot.
    Returns the slot name saved to, or None if the player skipped saving.
    '''
    while True:
        raw = input('\nSave this story to a named slot? Enter a name, or leave blank to skip: ').strip()
        if not raw:
            return None
        name = _sanitize_name(raw)
        if not name:
            print('That name has no usable characters; use letters, numbers, spaces, dashes or underscores.')
            continue
        if name in list_saves():
            confirm = input(f'A save named "{name}" already exists. Type "yes" to overwrite it: ').strip().lower()
            if confirm != 'yes':
                continue
        save_session(name, state)
        print(f'Saved story "{name}".')
        return name

def prompt_transcript_export(chatlogs, default_name):
    '''
    Exit-time prompt: offer to export the session transcript as plain text
    or Markdown, written under default_name (the save-slot name when one was
    chosen, otherwise the session file name).
    '''
    while True:
        fmt = input('Export the transcript? Enter "txt" or "md", or leave blank to skip: ').strip().lower()
        if not fmt:
            return
        if fmt not in EXPORT_FORMATS:
            print('Please enter "txt", "md", or leave blank to skip.')
            continue
        path = export_transcript(chatlogs, default_name, fmt)
        print(f'Transcript written to {path}.')
        return

def choose_save():
    '''
    Startup menu over existing save slots: continue, export, or delete a
    saved story. Returns the loaded state dict to continue from, or None to
    start a new story. Skipped entirely when no saves exist.
    '''
    while True:
        names = list_saves()
        if not names:
            return None

        print('\nSaved stories:')
        for i, name in enumerate(names, start=1):
            saved_on = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(_save_path(name))))
            print(f'  {i}. {name} (saved {saved_on})')
        print('Enter a number to continue that story, "new" to start a new one, "export" to export a transcript, or "delete" to remove a save.')

        choice = input('> ').strip()
        command = choice.lower()

        if command == 'new':
            return None

        if command == 'export':
            name = input('Name of the save to export: ').strip()
            if name not in names:
                print(f'No save named "{name}".')
                continue
            fmt = input('Format ("txt" or "md"): ').strip().lower()
            if fmt not in EXPORT_FORMATS:
                print('Please choose "txt" or "md".')
                continue
            path = export_transcript(load_session(name)['Chat Logs'], name, fmt)
            print(f'Transcript written to {path}.')
            continue

        if command == 'delete':
            name = input('Name of the save to delete: ').strip()
            if name not in names:
                print(f'No save named "{name}".')
                continue
            confirm = input(f'Type "yes" to permanently delete "{name}": ').strip().lower()
            if confirm == 'yes':
                delete_save(name)
                print(f'Deleted save "{name}".')
            else:
                print('Cancelled.')
            continue

        try:
            selected = names[int(choice) - 1]
        except (ValueError, IndexError):
            print('Please enter a listed number, "new", "export", or "delete".')
            continue

        return load_session(selected)
