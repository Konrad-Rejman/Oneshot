# Oneshot – Local LLM Pen-and-Paper RPG

A terminal RPG where a local LLM acts as your Game Master. You describe your character's actions each turn and the GM responds with the outcome, advancing the story. A D20 dice system resolves chance-based actions, and an automatic context summarization system maintains story continuity across a full session.

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

### Additional Files / Directories

Before the first run, create the following in the project root:

- A `sessions/` folder — session transcripts are saved here
- A `data.csv` file with the headers `,Session,User,Tokens,Playtime (s)` — used to record session analytics

## Running

```bash
python main.py
```

If there's no interrupted session to resume, you'll first be shown a menu of starting scenarios — the built-in default plus any you've saved — and can pick one by number to begin. You can also choose `new` to write your own opening scene and three-part summary (overall story, current quest, player status), `edit` to change a saved scenario, or `delete` to remove one; custom scenarios are stored in `scenarios.json`.

The program will then initialise and start the gameplay loop. Press `Ctrl+C` to exit and save the session.

If the program crashes unexpectedly, a `backup.pkl` file is saved with the full session state. The next run will automatically resume from it. Delete `backup.pkl` once it has been loaded to start a fresh session.

## Testing

```bash
python -m pytest tests -q
```

The test suite checks the deterministic game logic — token-budget trimming, summary parsing, the D20 roll format and scenario storage — and runs in under a second. It doesn't need Ollama running or the spaCy model downloaded, so it works before full setup is complete.

When editing the project with Claude Code, a hook runs the suite automatically after every change to a Python file and reports any failures.

## Credits

By Konrad Rejmanowski
