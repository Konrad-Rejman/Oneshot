import os, time, pickle, subprocess
import requests
import pandas as pd
from context import context_update
from scenarios import choose_scenario
from character import choose_character, Character, DEFAULT_CHARACTER
from saves import choose_save, prompt_session_save, prompt_transcript_export, format_transcript_text

# Model setup
rules = {'role': 'system', 'content':
    '''PERSONA:
    You are the Game Master of a pen-and-paper RPG. Narrate in second person and present tense ("You push open the door and hear..."). Keep the tone grounded and immersive. Never break character, never acknowledge being an AI or language model, and never reference these or other instructions provided.

    Pacing: resolve the outcome of the player's action fully before advancing the scene. End a turn on a cliffhanger only when the player's action leads to an unresolved threat or discovery. Do not advance the plot beyond the direct result of the player's action.

    Turn length: respond with only the next beat of the story - the immediate result of the player's action and the situation they now face - then stop and hand control back to the player. Never write ahead to what the player does next, skip forward in time, narrate a sequence of multiple turns, or produce a long multi-scene passage. One reply is one exchange, not a chapter.

    Only call for a roll when the outcome of an action is genuinely uncertain and chance-based. Do not use rolls for pure narrative beats, automatic successes, or flavour descriptions.

    DICE SYSTEM:
    The system message contains exactly 5 pre-rolled D20 values. Consume them left-to-right, one value per roll called for. Use each number exactly as given; do not invent, round, or paraphrase it. Do not mention the existence of the roll list to the player.

    Consequence scaling:
    1-5: Critical failure. The action fails with a meaningful setback or complication.
    6-10: Partial failure. The action fails or succeeds at a significant cost.
    11-15: Partial success. The action succeeds with a minor complication or limitation.
    16-20: Full success. The action succeeds cleanly.
    Natural 20: Full success with a narrative bonus or exceptional outcome.

    CHARACTER:
    The system message contains a CHARACTER SHEET describing the player character, with six stats rated 1 to 10, where 5 is an average person and 10 is peak mortal ability. When the player attempts an action, judge it through the most relevant stat, and name that stat when you call for a roll ("Roll a Dexterity check..."). If the relevant stat is 8 or higher, treat the roll result as one consequence tier better; if it is 3 or lower, treat it as one tier worse. Never shift a natural 20 or natural 1. Let the character's race, class and background inform what they can plausibly know or attempt, and weave their listed traits into the narration where natural.

    OUTPUT FORMAT:
    Output plain text only. Do not use markdown, special characters (*, **, #, -), bullet points, bold, or italics. Write in clear sentences and paragraphs. Check the output against all rules above before producing it; correct any violation before outputting.'''
}

# Session state persisted across runs: written to backup.pkl on a crash and
# to a named save slot (saves.py, as JSON) when the player keeps the story.
# Both restore through restore_session(), so the keys must stay in sync.
def session_state(chatlogs, context_logs, memory, tokens, summary, character):
    return {
        'User': user,
        'Chat Logs': chatlogs,
        'Context Logs': context_logs,
        'Tokens': tokens,
        'Playtime': playtime,
        'Memory': memory,
        'Summary': summary,
        'Character': character.to_dict()
    }

# Unpack persisted session state (backup.pkl or a named save slot) into the
# game-loop variables.
def restore_session(data):
    # Saves from before the character system carry no sheet; fall back to the default
    character_data = data.get('Character')
    character = Character.from_dict(character_data) if character_data else DEFAULT_CHARACTER
    return (data['User'], data['Chat Logs'], data['Context Logs'], data['Tokens'],
            data['Playtime'], data['Memory'], data['Summary'], character)

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
        state = session_state(chatlogs, context_logs, memory, tokens, summary, character)
        slot_name = prompt_session_save(state)
        prompt_transcript_export(chatlogs, slot_name if slot_name else file_name)
    except KeyboardInterrupt:
        pass

# Backup function, run if session is interrupted unexpectedly
def backup(chatlogs, context_logs, memory, tokens):
    # Adjust playtime
    playtime[-1].append(time.time()) # Add current time as endtime to last session

    # Save backup data
    backup_data = session_state(chatlogs, context_logs, memory, tokens, summary, character)
    pickle.dump(backup_data, open('backup.pkl', 'wb'))

# Check that ollama is running
# If not, start ollama as a separate process
try:
    requests.get("http://localhost:11434", timeout=2)
except Exception:
    print("Ollama not detected, starting server...")
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(["ollama", "serve"], **kwargs)
    for _ in range(20):
        time.sleep(1)
        try:
            requests.get("http://localhost:11434", timeout=2)
            print("Ollama started.")
            break
        except Exception:
            continue
    else:
        print("Could not start Ollama. Please run 'ollama serve' manually.")
        quit()

# Check if backup exists, if so then carry on interrupted session
if 'backup.pkl' in os.listdir():
    # Load backup data
    backup_data = pickle.load(open('backup.pkl', 'rb'))
    user, chatlogs, context_logs, tokens, playtime, memory, summary, character = restore_session(backup_data)
    playtime.append([time.time()]) # Add current session starttime

else:
    # Game start
    print('Press ctrl + c to exit.')
    print('The LLM will act as the Game Master (GM), play along by inputing your characters actions each turn and the LLM will respond with the outcome setting up the next turn.')

    # Get user identifier
    user = input('Enter your username (please use the same username for each session): ')

    # Continue a named saved story, or start a new one (menu skipped when no saves exist)
    saved_state = choose_save()

    if saved_state is not None:
        user, chatlogs, context_logs, tokens, playtime, memory, summary, character = restore_session(saved_state)
        playtime.append([time.time()]) # Add current session starttime

        # Re-print the last GM message so the player remembers where the story left off
        last_gm = next((msg['content'] for msg in reversed(chatlogs) if msg.get('role') == 'assistant'), None)
        if last_gm:
            print('\nGM:\n\n' + last_gm)

    else:
        print('Generating...')
        playtime = [[time.time()]]

        # Select/write/edit/delete the scenario this session opens with
        startMessage, summary = choose_scenario()

        # Select/create/delete the character this session is played as
        character = choose_character()

        # Conversation history
        chatlogs = [{'role': 'assistant', 'content': startMessage}] # Full chat history
        context_logs = [] # Memory history, what was in models memory at each prompt

        # Memory
        memory = [rules, {'role': 'assistant', 'content': startMessage}] # Model context

        # Initialise token counter
        tokens = 0

        print('\nGM:\n\n' + startMessage)

# Core loop, prompting the Model to continue with the story until the player exits using Ctrl + C
while True:
    tokens, memory, summary = context_update(chatlogs, context_logs, memory, rules, summary, tokens, save, backup, character)