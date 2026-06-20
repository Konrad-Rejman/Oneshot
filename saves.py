'''
Named save slots, startup load menu, and transcript export (ROADMAP 2.2).

Saved stories are private to their owner: each user's slots live in their own
SAVES_DIR/<sanitized-username>/ subdirectory, so the owning directory is the
privacy boundary and two users may reuse a slot name. A slot is a single JSON
file carrying the same state keys as backup.pkl ('User', 'Chat Logs',
'Context Logs', 'Tokens', 'Playtime', 'Memory', 'Summary', 'Character',
'Progression'), plus 'Version' and 'Name' added on write. Version history:
- 1: the initial key set, no 'Progression'
- 2: adds the 'Progression' key (ROADMAP 2.3 - HP/inventory/XP/level);
  version-1 saves load with a fresh progression (main.py:restore_session).
  (Early version-2 saves also carried spell-slot keys inside Progression;
  those were removed and Progression.from_dict simply ignores any extra
  keys, so such saves still load.)
The per-user layout does not touch the JSON schema, so it is not a version
bump; migrate_saves relocates pre-existing flat saves. New state belongs in
new keys with a SAVE_VERSION bump - never a change to the existing keys - so
old saves stay loadable.
'''
import json, os, re, time

import ui

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

def _user_dir(user):
    '''The save directory private to user; sanitised so it is path-safe.'''
    return os.path.join(SAVES_DIR, _sanitize_name(user))

def _save_path(name, user):
    return os.path.join(_user_dir(user), name + '.json')

def list_saves(user):
    '''Names of user's existing save slots, most recently saved first.'''
    user_dir = _user_dir(user)
    if not os.path.isdir(user_dir):
        return []
    files = [f for f in os.listdir(user_dir) if f.endswith('.json')]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(user_dir, f)), reverse=True)
    return [os.path.splitext(f)[0] for f in files]

def save_session(name, state, user):
    '''
    Write session state to user's named slot, creating their save directory if
    needed and overwriting any existing save with that name. state must hold the
    same JSON-serialisable keys as backup.pkl's dict (Character already as a
    dict, not a Character instance); 'Version' and 'Name' are added here.
    '''
    os.makedirs(_user_dir(user), exist_ok=True)
    payload = {'Version': SAVE_VERSION, 'Name': name}
    payload.update(state)
    with open(_save_path(name, user), 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def load_session(name, user):
    '''Return the saved state dict for user's named slot.'''
    with open(_save_path(name, user), 'r', encoding='utf-8') as f:
        return json.load(f)

def delete_save(name, user):
    if os.path.exists(_save_path(name, user)):
        os.remove(_save_path(name, user))

def migrate_saves(user):
    '''
    Claim pre-ownership saves for user: move any *.json sitting directly in
    SAVES_DIR (the old flat layout) into user's private subdirectory. A no-op
    once no flat saves remain.
    '''
    if not os.path.isdir(SAVES_DIR):
        return
    legacy = [f for f in os.listdir(SAVES_DIR)
              if f.endswith('.json') and os.path.isfile(os.path.join(SAVES_DIR, f))]
    if not legacy:
        return
    os.makedirs(_user_dir(user), exist_ok=True)
    for f in legacy:
        os.replace(os.path.join(SAVES_DIR, f), os.path.join(_user_dir(user), f))

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

def prompt_session_save(state, user):
    '''
    Exit-time prompt: offer to keep the finished session in one of user's named
    slots. Returns the slot name saved to, or None if the player skipped saving.
    '''
    while True:
        raw = ui.ask('\nSave this story to a named slot? Enter a name, or leave blank to skip:').strip()
        if not raw:
            return None
        name = _sanitize_name(raw)
        if not name:
            ui.warn('That name has no usable characters; use letters, numbers, spaces, dashes or underscores.')
            continue
        if name in list_saves(user):
            confirm = ui.ask(f'A save named "{name}" already exists. Type "yes" to overwrite it:').strip().lower()
            if confirm != 'yes':
                continue
        save_session(name, state, user)
        ui.system(f'Saved story "{name}".')
        return name

def prompt_transcript_export(chatlogs, default_name):
    '''
    Exit-time prompt: offer to export the session transcript as plain text
    or Markdown, written under default_name (the save-slot name when one was
    chosen, otherwise the session file name).
    '''
    while True:
        fmt = ui.ask('Export the transcript? Enter "txt" or "md", or leave blank to skip:').strip().lower()
        if not fmt:
            return
        if fmt not in EXPORT_FORMATS:
            ui.warn('Please enter "txt", "md", or leave blank to skip.')
            continue
        path = export_transcript(chatlogs, default_name, fmt)
        ui.system(f'Transcript written to {path}.')
        return

def choose_save(user):
    '''
    Startup menu over user's existing save slots: continue, export, or delete a
    saved story. Other users' saves are never listed or reachable. Returns the
    loaded state dict to continue from, or None to start a new story. Skipped
    entirely when user has no saves.
    '''
    while True:
        names = list_saves(user)
        if not names:
            return None

        entries = []
        for name in names:
            saved_on = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(_save_path(name, user))))
            entries.append(f'{name} (saved {saved_on})')
        ui.menu('Saved stories:', entries)
        ui.system('Enter a number to continue that story, "new" to start a new one, "export" to export a transcript, or "delete" to remove a save.')

        choice = ui.ask().strip()
        command = choice.lower()

        if command == 'new':
            return None

        if command == 'export':
            name = ui.ask('Name of the save to export:').strip()
            if name not in names:
                ui.warn(f'No save named "{name}".')
                continue
            fmt = ui.ask('Format ("txt" or "md"):').strip().lower()
            if fmt not in EXPORT_FORMATS:
                ui.warn('Please choose "txt" or "md".')
                continue
            path = export_transcript(load_session(name, user)['Chat Logs'], name, fmt)
            ui.system(f'Transcript written to {path}.')
            continue

        if command == 'delete':
            name = ui.ask('Name of the save to delete:').strip()
            if name not in names:
                ui.warn(f'No save named "{name}".')
                continue
            confirm = ui.ask(f'Type "yes" to permanently delete "{name}":').strip().lower()
            if confirm == 'yes':
                delete_save(name, user)
                ui.system(f'Deleted save "{name}".')
            else:
                ui.system('Cancelled.')
            continue

        try:
            selected = names[int(choice) - 1]
        except (ValueError, IndexError):
            ui.warn('Please enter a listed number, "new", "export", or "delete".')
            continue

        return load_session(selected, user)
