import os, time, pickle, subprocess
from types import SimpleNamespace
import requests
import pandas as pd
from context import context_update, SessionEnd
from gm_rules import rules
import model
from scenarios import choose_scenario, manage_scenarios, migrate_scenarios
from character import (choose_character, manage_characters, migrate_characters,
                       Character, DEFAULT_CHARACTER)
from progression import Progression, new_progression
from saves import (choose_save, migrate_saves, prompt_session_save,
                   prompt_transcript_export, format_transcript_text)
import accounts
import ui

# Session state persisted across runs: written to backup.pkl on a crash and
# to a named save slot (saves.py, as JSON) when the player keeps the story.
# Both restore through restore_session(), so the keys must stay in sync. A live
# session is held in a SimpleNamespace (see new_session/session_from_state) with
# these same fields, mutated as the game loop runs.
def _state_dict(s, chatlogs=None, context_logs=None, memory=None, tokens=None):
    '''
    Build the persisted-state dict from session s. The four list/count fields
    default to s's current values but can be overridden with the pre-turn
    snapshots backup() holds, so a crash backs up a consistent state.
    '''
    return {
        'User': s.user,
        'Chat Logs': s.chatlogs if chatlogs is None else chatlogs,
        'Context Logs': s.context_logs if context_logs is None else context_logs,
        'Tokens': s.tokens if tokens is None else tokens,
        'Playtime': s.playtime,
        'Memory': s.memory if memory is None else memory,
        'Summary': s.summary,
        'Character': s.character.to_dict(),
        'Progression': s.progression.to_dict()
    }

# Unpack persisted session state (backup.pkl or a named save slot) into a live
# session namespace, keeping the logged-in user (the save's stored 'User' is
# ignored). playtime gains this run's start time.
def session_from_state(user, data):
    # Saves from before the character system carry no sheet; fall back to the default
    character_data = data.get('Character')
    character = Character.from_dict(character_data) if character_data else DEFAULT_CHARACTER
    # Version-1 saves carry no progression (ROADMAP 2.3); start a fresh one
    progression_data = data.get('Progression')
    progression = Progression.from_dict(progression_data) if progression_data else new_progression(character)
    playtime = data['Playtime']
    playtime.append([time.time()])
    return SimpleNamespace(
        user=user, chatlogs=data['Chat Logs'], context_logs=data['Context Logs'],
        tokens=data['Tokens'], playtime=playtime, memory=data['Memory'],
        summary=data['Summary'], character=character, progression=progression)

# First-run setup: create the session-transcript directory and the analytics
# CSV if absent, so a fresh clone needs no manual file/folder creation.
def ensure_setup():
    os.makedirs('sessions', exist_ok=True)
    if not os.path.exists('data.csv'):
        # Default index writes the leading empty-named column read back with index_col=0
        pd.DataFrame(columns=['Session', 'User', 'Tokens', 'Playtime (s)']).to_csv('data.csv')

# Start Ollama if it is not already serving, so the game has a model backend.
def ensure_ollama():
    try:
        requests.get("http://localhost:11434", timeout=2)
        return
    except Exception:
        ui.system("Ollama not detected, starting server...")
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(["ollama", "serve"], **kwargs)
    for _ in range(20):
        time.sleep(1)
        try:
            requests.get("http://localhost:11434", timeout=2)
            ui.system("Ollama started.")
            return
        except Exception:
            continue
    ui.error("Could not start Ollama. Please run 'ollama serve' manually.")
    quit()

# Account screen: log into an existing account or create a new one. The chosen
# username is the owner tag for everything created this session. Passwords are
# entered masked and stored only as an sha512 hash (accounts.py).
def account_screen():
    while True:
        action = ui.select('Account', [('Log in', 'login'), ('Create account', 'create')])
        if action == 'login':
            username = ui.ask('Username:').strip()
            password = ui.ask_secret('Password:')
            if accounts.authenticate(username, password):
                ui.system(f'Welcome back, {username}.')
                return username
            ui.error('Incorrect username or password.')
        else:
            username = ui.ask('Choose a username:').strip()
            if accounts.user_exists(username):
                ui.warn('That username is taken; choose another or log in.')
                continue
            password = ui.ask_secret('Choose a password:')
            if accounts.create_account(username, password) is None:
                ui.warn('That username has no usable characters; try another.')
                continue
            ui.system(f'Account created. Welcome, {username}.')
            return username

# Apply the user's persistent default GM model, asking them to set it the first
# time only (accounts stores None until then). Changeable later in Settings.
def init_default_model(user):
    if accounts.get_default_model(user) is None:
        chosen = model.choose_default_model()
        accounts.set_default_model(user, chosen)
    model.apply_default_model(accounts.get_default_model(user))

# Run on a session ending (Ctrl+C or an unrevived death): archive the transcript
# and analytics, then offer to keep the story and export it.
def make_save(s):
    def session_state():
        return _state_dict(s)

    def save():
        file_number = len(os.listdir('sessions'))
        folder_name = os.path.join('sessions', str(file_number))
        os.makedirs(folder_name)

        file_name = str(file_number) + '_' + s.user
        file_path = os.path.join(folder_name, file_name + '.txt')
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(format_transcript_text(s.chatlogs))

        ctx_name = str(file_number) + '_' + s.user + '_' + 'Context_Logs'
        ctx_path = os.path.join(folder_name, ctx_name + '.txt')
        with open(ctx_path, 'w', encoding='utf-8') as file:
            for i in range(len(s.context_logs)):
                file.write('Memory at prompt ' + str(i+1) + '\n\n')
                for prompt in s.context_logs[i]:
                    if isinstance(prompt, int):
                        file.write('Token usage: ' + str(prompt) + '\n\n')
                    elif isinstance(prompt, dict):
                        txt = prompt['content']
                        if prompt.get('role') in ('system', 'assistant'):
                            file.write('Model:\n\n' + txt + '\n\n')
                        elif prompt.get('role') == 'user':
                            file.write('User:\n\n' + txt + '\n\n')
                        else:
                            file.write('Other:\n\n' + txt + '\n\n')
                    else:
                        file.write('Other:\n\n' + str(prompt) + '\n\n')

        # Add endtime to last session
        s.playtime[-1].append(time.time())

        session_data = {
            'Session': [file_name],
            'User': [s.user],
            'Tokens': [s.tokens],
            'Playtime (s)': [sum(round(p[1] - p[0]) for p in s.playtime)]
        }
        df = pd.read_csv('data.csv', index_col=0)
        df = pd.concat([df, pd.DataFrame(session_data)])
        df.to_csv('data.csv')

        # Offer to keep the story in a named save slot and to export the
        # transcript. A second Ctrl+C here just skips the offers - the session
        # files are already written.
        try:
            slot_name = prompt_session_save(session_state(), s.user)
            prompt_transcript_export(s.chatlogs, slot_name if slot_name else file_name)
        except KeyboardInterrupt:
            pass

    return save

# Back up a session interrupted by an unexpected error: persist the pre-turn
# snapshots (so the backed-up state is internally consistent) to backup.pkl.
def make_backup(s):
    def backup(old_chatlogs, old_context_logs, old_memory, old_tokens):
        s.playtime[-1].append(time.time())
        backup_data = _state_dict(s, chatlogs=old_chatlogs, context_logs=old_context_logs,
                                  memory=old_memory, tokens=old_tokens)
        pickle.dump(backup_data, open('backup.pkl', 'wb'))
    return backup

# Build a fresh session: pick the scenario and character, then seed the chat
# history and model memory with the opening scene.
def new_session(user):
    ui.system('Generating...')
    playtime = [[time.time()]]
    start_message, summary = choose_scenario(user)
    character = choose_character(user)
    progression = new_progression(character)
    chatlogs = [{'role': 'assistant', 'content': start_message}]
    context_logs = []
    memory = [rules, {'role': 'assistant', 'content': start_message}]
    ui.gm_message(start_message)
    return SimpleNamespace(
        user=user, chatlogs=chatlogs, context_logs=context_logs, tokens=0,
        playtime=playtime, memory=memory, summary=summary,
        character=character, progression=progression)

# Re-print the last GM message so a resumed/continued story shows where it left off.
def _replay_last_gm(s):
    last_gm = next((m['content'] for m in reversed(s.chatlogs) if m.get('role') == 'assistant'), None)
    if last_gm:
        ui.gm_message(last_gm)

# Play a session to its end. Ctrl+C or an unrevived death raises SessionEnd
# (after save()), returning control to the main menu rather than exiting.
def run_game(s):
    ui.system('Press Ctrl+C to end the session and return to the menu.')
    save = make_save(s)
    backup = make_backup(s)
    turns_since_summary_update = 0
    try:
        while True:
            s.tokens, s.memory, s.summary, turns_since_summary_update = context_update(
                s.chatlogs, s.context_logs, s.memory, rules, s.summary, s.tokens,
                save, backup, s.character, turns_since_summary_update, s.progression)
    except SessionEnd:
        return

# Settings menu: change the persistent default GM model (applied immediately).
def settings_menu(user):
    while True:
        choice = ui.select('Settings', [
            ('Change default model', 'model'),
            ('Back', 'back'),
        ])
        if choice == 'model':
            chosen = model.choose_default_model(accounts.get_default_model(user))
            accounts.set_default_model(user, chosen)
            model.apply_default_model(chosen)
            ui.system(f'Default model: {model.active_model()}')
        else:
            return

def menu_loop(user):
    while True:
        choice = ui.select('Main menu', [
            ('New game', 'new'),
            ('Continue', 'continue'),
            ('Characters', 'characters'),
            ('Scenarios', 'scenarios'),
            ('Settings', 'settings'),
            ('Exit', 'exit'),
        ])

        if choice == 'new':
            run_game(new_session(user))
        elif choice == 'continue':
            state = choose_save(user)
            if state is None:
                ui.system('No saved story to continue.')
                continue
            s = session_from_state(user, state)
            _replay_last_gm(s)
            run_game(s)
        elif choice == 'characters':
            manage_characters(user)
        elif choice == 'scenarios':
            manage_scenarios(user)
        elif choice == 'settings':
            settings_menu(user)
        else:
            return

def main():
    ensure_setup()
    ensure_ollama()
    accounts.ensure_seed()

    user = account_screen()

    # The first user to run after the ownership change claims any pre-existing
    # unowned saves, characters and scenarios (one-time, no-op thereafter).
    migrate_saves(user)
    migrate_characters(user)
    migrate_scenarios(user)

    init_default_model(user)

    # Resume a session interrupted by an unexpected error, but only if its
    # backup belongs to the logged-in user. Remove the stale backup once loaded
    # so it is not re-resumed; a fresh crash writes a new one.
    if os.path.exists('backup.pkl'):
        backup_data = pickle.load(open('backup.pkl', 'rb'))
        if backup_data.get('User') == user:
            os.remove('backup.pkl')
            s = session_from_state(user, backup_data)
            _replay_last_gm(s)
            run_game(s)

    menu_loop(user)

if __name__ == '__main__':
    main()
