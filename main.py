import os, time, pickle, subprocess
import requests
import pandas as pd
from context import context_update
from scenarios import choose_scenario
from character import choose_character, Character, DEFAULT_CHARACTER
from progression import Progression, new_progression, prompt_starting_spell_slots
from saves import choose_save, prompt_session_save, prompt_transcript_export, format_transcript_text
import ui

# Model setup
rules = {'role': 'system', 'content':
    '''PERSONA:
    You are the Game Master of a pen-and-paper RPG. Narrate in second person and present tense ("You push open the door and hear..."). Keep the tone grounded and immersive. Never break character, never acknowledge being an AI or language model, and never reference these or other instructions provided.

    Pacing: resolve the outcome of the player's action fully before advancing the scene. End a turn on a cliffhanger only when the player's action leads to an unresolved threat or discovery. Do not advance the plot beyond the direct result of the player's action.

    Turn length: respond with only the next beat of the story - the immediate result of the player's action and the situation they now face - then stop and hand control back to the player. Never write ahead to what the player does next, skip forward in time, narrate a sequence of multiple turns, or produce a long multi-scene passage. One reply is one exchange, not a chapter.

    Stat checks are how chance is resolved. Whenever the player attempts an action whose outcome is uncertain or could fail in a way that matters - fighting, sneaking, climbing, persuading, deceiving, searching, recalling knowledge, resisting harm - you must call for a check of the most relevant stat and resolve it with the next unused roll before narrating the outcome. Expect most player actions to need a check; if in doubt, call for one. Skip a check only for trivial actions that cannot meaningfully fail, plain conversation, and flavour description.

    DICE SYSTEM:
    The system message contains exactly 5 pre-rolled D20 values. Consume them left-to-right, one value per stat check called for. Use each number exactly as given; do not invent, round, or paraphrase it. Announce each check by naming the stat and the value used ("Roll a Wisdom check... you roll a 13..."). Do not mention the existence of the roll list to the player.

    Consequence scaling:
    1-5: Critical failure. The action fails with a meaningful setback or complication.
    6-10: Partial failure. The action fails or succeeds at a significant cost.
    11-15: Partial success. The action succeeds with a minor complication or limitation.
    16-20: Full success. The action succeeds cleanly.
    Natural 20: Full success with a narrative bonus or exceptional outcome.

    CHARACTER:
    The system message contains a CHARACTER SHEET describing the player character, with six stats rated 1 to 10, where 5 is an average person and 10 is peak mortal ability. When the player attempts an action, judge it through the most relevant stat, and name that stat when you call for a roll ("Roll a Dexterity check..."). If the relevant stat is 8 or higher, treat the roll result as one consequence tier better; if it is 3 or lower, treat it as one tier worse. Never shift a natural 20 or natural 1. Let the character's race, class and background inform what they can plausibly know or attempt, and weave their listed traits into the narration where natural.

    PROGRESSION:
    The system message contains a STATUS block listing the character's current HP, level, XP, spell slots, inventory and features. Treat it as the single source of truth and never contradict it: narrate wounds consistently with the listed HP, do not let the player cast a spell without a remaining spell slot of the right level, and only let them use items the inventory lists. Failed checks with physical danger should cost HP; rest and healing restore it. Award 10 to 50 XP when the player overcomes a meaningful challenge. If HP reaches 0 the character falls; narrate the fall and stop - what happens after death is handled outside the story.

    STATE LINE:
    End every reply with exactly one final line reporting this turn's mechanical changes, in exactly this form:
    STATE: HP -3; XP +25; GAIN torch; LOSE rope; SLOT 1 -1
    Available entries: HP +N or HP -N for healing or damage, XP +N for experience awarded, GAIN <item> or LOSE <item> for inventory changes, SLOT <level> -1 when a spell slot is spent. Separate entries with semicolons. Include only what actually changed this turn; if nothing changed mechanically, end with:
    STATE: none
    The state line is machine-read bookkeeping, not narration: keep it to that exact format, never mention it to the player, and never report a change in the narration without also reporting it in the state line.

    OUTPUT FORMAT:
    Output plain text only. Do not use markdown, special characters (*, **, #, -), bullet points, bold, or italics. Write in clear sentences and paragraphs. Check the output against all rules above before producing it; correct any violation before outputting.'''
}

# Session state persisted across runs: written to backup.pkl on a crash and
# to a named save slot (saves.py, as JSON) when the player keeps the story.
# Both restore through restore_session(), so the keys must stay in sync.
def session_state(chatlogs, context_logs, memory, tokens, summary, character, progression):
    return {
        'User': user,
        'Chat Logs': chatlogs,
        'Context Logs': context_logs,
        'Tokens': tokens,
        'Playtime': playtime,
        'Memory': memory,
        'Summary': summary,
        'Character': character.to_dict(),
        'Progression': progression.to_dict()
    }

# Unpack persisted session state (backup.pkl or a named save slot) into the
# game-loop variables.
def restore_session(data):
    # Saves from before the character system carry no sheet; fall back to the default
    character_data = data.get('Character')
    character = Character.from_dict(character_data) if character_data else DEFAULT_CHARACTER
    # Version-1 saves carry no progression (ROADMAP 2.3); start a fresh one
    progression_data = data.get('Progression')
    progression = Progression.from_dict(progression_data) if progression_data else new_progression(character)
    return (data['User'], data['Chat Logs'], data['Context Logs'], data['Tokens'],
            data['Playtime'], data['Memory'], data['Summary'], character, progression)

# Run on exit
def save():
    # Save session info
    file_number = 0
    for f in os.listdir('sessions'):
        file_number += 1

    # Construct folder
    folder_name = os.path.join('sessions', str(file_number))
    os.makedirs(folder_name)

    # Construct chatlogs file name
    file_name = str(file_number) + '_' + user
    file_path = os.path.join(folder_name, file_name + '.txt')

    # Write a file containing the session chatlogs
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(format_transcript_text(chatlogs))

    # Construct contextlogs file name
    file_name = str(file_number) + '_' + user + '_' + 'Context_Logs'
    file_path = os.path.join(folder_name, file_name + '.txt')

    # Write a file containing the memory context at each prompt
    with open(file_path, 'w', encoding='utf-8') as file:
        for i in range(len(context_logs)):
            file.write('Memory at prompt ' + str(i+1) + '\n\n')
            for prompt in context_logs[i]:
                if isinstance(prompt, int):
                    # Token usage at interaction i+1
                    file.write('Token usage: ' + str(prompt) + '\n\n')
                elif isinstance(prompt, dict):
                    txt = prompt['content']
                    if prompt.get('role') == 'system' or prompt.get('role') == 'assistant':
                        file.write('Model:\n\n' + txt + '\n\n')
                    elif prompt.get('role') == 'user':
                        file.write('User:\n\n' + txt + '\n\n')
                    else:
                        file.write('Other:\n\n' + txt + '\n\n')
                else:
                    # Fallback for unexpected types
                    file.write('Other:\n\n' + str(prompt) + '\n\n')

    # Add endtime to last session
    playtime[-1].append(time.time())

    # Construct file name
    file_name = str(file_number) + '_' + user

    session_data = {
        'Session': [file_name], 
        'User': [user],
        'Tokens': [tokens], 
        'Playtime (s)': [sum(round(s[1] - s[0]) for s in playtime)] # Sum session endtime-starttime for each session instance
    }
    new_row = pd.DataFrame(session_data)

    # Add the session feedback to the data csv
    df = pd.read_csv('data.csv', index_col=0)
    df = pd.concat([df, new_row])
    df.to_csv('data.csv')

    # Offer to keep the story in a named save slot (loadable from the startup
    # menu) and to export the transcript as plain text or Markdown. A second
    # Ctrl+C here just skips the offers - the session files are already written.
    try:
        state = session_state(chatlogs, context_logs, memory, tokens, summary, character, progression)
        slot_name = prompt_session_save(state)
        prompt_transcript_export(chatlogs, slot_name if slot_name else file_name)
    except KeyboardInterrupt:
        pass

# Backup function, run if session is interrupted unexpectedly
def backup(chatlogs, context_logs, memory, tokens):
    # Adjust playtime
    playtime[-1].append(time.time()) # Add current time as endtime to last session

    # Save backup data
    backup_data = session_state(chatlogs, context_logs, memory, tokens, summary, character, progression)
    pickle.dump(backup_data, open('backup.pkl', 'wb'))

# Check that ollama is running
# If not, start ollama as a separate process
try:
    requests.get("http://localhost:11434", timeout=2)
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
            break
        except Exception:
            continue
    else:
        ui.error("Could not start Ollama. Please run 'ollama serve' manually.")
        quit()

# Check if backup exists, if so then carry on interrupted session
if 'backup.pkl' in os.listdir():
    # Load backup data
    backup_data = pickle.load(open('backup.pkl', 'rb'))
    user, chatlogs, context_logs, tokens, playtime, memory, summary, character, progression = restore_session(backup_data)
    playtime.append([time.time()]) # Add current session starttime

else:
    # Game start
    ui.system('Press ctrl + c to exit.')
    ui.system('The LLM will act as the Game Master (GM), play along by inputing your characters actions each turn and the LLM will respond with the outcome setting up the next turn.')

    # Get user identifier
    user = ui.ask('Enter your username (please use the same username for each session):')

    # Continue a named saved story, or start a new one (menu skipped when no saves exist)
    saved_state = choose_save()

    if saved_state is not None:
        user, chatlogs, context_logs, tokens, playtime, memory, summary, character, progression = restore_session(saved_state)
        playtime.append([time.time()]) # Add current session starttime

        # Re-print the last GM message so the player remembers where the story left off
        last_gm = next((msg['content'] for msg in reversed(chatlogs) if msg.get('role') == 'assistant'), None)
        if last_gm:
            ui.gm_message(last_gm)

    else:
        ui.system('Generating...')
        playtime = [[time.time()]]

        # Select/write/edit/delete the scenario this session opens with
        startMessage, summary = choose_scenario()

        # Select/create/delete the character this session is played as
        character = choose_character()

        # Starting HP comes from Constitution; spell slots from one question
        progression = new_progression(character, prompt_starting_spell_slots())

        # Conversation history
        chatlogs = [{'role': 'assistant', 'content': startMessage}] # Full chat history
        context_logs = [] # Memory history, what was in models memory at each prompt

        # Memory
        memory = [rules, {'role': 'assistant', 'content': startMessage}] # Model context

        # Initialise token counter
        tokens = 0

        ui.gm_message(startMessage)

# Core loop, prompting the Model to continue with the story until the player exits using Ctrl + C
# Turns since the summary last changed - drives the forced refresh in
# context_update. Not persisted: resuming a session just restarts the count.
turns_since_summary_update = 0
while True:
    tokens, memory, summary, turns_since_summary_update = context_update(chatlogs, context_logs, memory, rules, summary, tokens, save, backup, character, turns_since_summary_update, progression)