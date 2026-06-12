# Oneshot – Local LLM Pen-and-Paper RPG

A terminal RPG where a local LLM acts as your Game Master. You describe your character's actions each turn and the GM responds with the outcome, advancing the story. A D20 dice system resolves chance-based actions, your character's stats and progression (HP, XP, levels, spell slots, inventory) shape the outcomes, and an automatic context summarization system maintains story continuity across a full session.

## Setup

### Prerequisites

**Python 3.12** (required for compatibility with GPU processing)

**Ollama**, with the Mistral Instruct model pulled:

```bash
ollama pull mistral:instruct
```

You don't need to start the server yourself — on launch the program checks whether Ollama is already running and starts it for you if not (falling back to asking you to run `ollama serve` manually if that fails).

### Installation

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_md
```

The first time a session scores a summary update, a ~1.4 GB BERTScore model (`roberta-large`) is downloaded automatically — a one-time wait during play, not a setup step.

### Additional Files / Directories

Before the first run, create the following in the project root:

- A `sessions/` folder — session transcripts are saved here
- A `data.csv` file with the headers `,Session,User,Tokens,Playtime (s)` — used to record session analytics

## Running

```bash
python main.py
```

If there's no interrupted session to resume, you'll be asked for a username and then — when you have saved stories — shown a menu of them, newest first: pick one by number to continue where it left off (the GM's last message is re-printed to remind you), or choose `new` to start a fresh story, `export` to write a saved story's transcript to a file, or `delete` to remove a save.

When starting a new story you'll be shown a menu of starting scenarios — the built-in default plus any you've saved — and can pick one by number to begin. You can also choose `new` to write your own opening scene and three-part summary (overall story, current quest, player status), `edit` to change a saved scenario, or `delete` to remove one; custom scenarios are stored in `scenarios.json`.

Next you'll pick the character to play as — the built-in default or one of your own. Choose `new` to create a character (name, race, class, background) and assign its six ability scores from a shared point pool, or `delete` to remove one; custom characters are stored in `characters.json`. The GM reads the character sheet every turn, so your stats shape how actions play out.

Finally you'll set your starting level-1 spell slots — your budget for casting spells — or enter 0 for a non-caster. During play the GM also tracks your character's HP, level, XP, spell slots and inventory, and reads them every turn: dangerous failures cost HP, rest and healing restore it, casting spells spends slots, and overcoming challenges earns XP. Earning enough XP levels you up — your maximum HP grows, you're fully healed, and you choose a reward: a stat increase, a new class feature, or an extra spell slot. If your HP reaches 0 your character falls, and you choose between resurrecting (revived at half HP, for an XP cost) or ending the story there.

The program will then initialise and start the gameplay loop. Press `Ctrl+C` to exit and save the session. On exit you can also keep the story in a named save slot — stored in `saves/` and offered in the saved-stories menu next time — and export the session transcript as plain text or Markdown into `exports/` (both folders are created automatically).

If the program crashes unexpectedly, a `backup.pkl` file is saved with the full session state. The next run will automatically resume from it. Delete `backup.pkl` once it has been loaded to start a fresh session.

## Testing

```bash
python -m pytest tests -q
```

The test suite checks the deterministic game logic — token-budget trimming, summary parsing and candidate scoring, the D20 roll format, character validation, the progression rules (HP/XP/spell-slot bookkeeping, level-ups, death and resurrection), and the scenario, character and save-slot storage formats — and runs in under a second. It doesn't need Ollama running or the spaCy/BERTScore models downloaded, so it works before full setup is complete.

When editing the project with Claude Code, a hook runs the suite automatically after every change to a Python file and reports any failures.

## Credits

By Konrad Rejmanowski
