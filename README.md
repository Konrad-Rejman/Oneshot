# Oneshot – Local LLM Pen-and-Paper RPG

A terminal RPG where a local LLM acts as your Game Master. You describe your character's actions each turn and the GM responds with the outcome, advancing the story. A D20 dice system resolves chance-based actions, and an automatic context summarization system maintains story continuity across a full session.

## Setup

### Prerequisites

**Python 3.12** (required for compatibility with GPU processing)

**Ollama** with the Mistral Instruct model:

```bash
ollama pull mistral:instruct
ollama serve
```

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

The program will initialise and start the gameplay loop. Press `Ctrl+C` to exit and save the session.

If the program crashes unexpectedly, a `backup.pkl` file is saved with the full session state. The next run will automatically resume from it. Delete `backup.pkl` once it has been loaded to start a fresh session.

## Credits

By Konrad Rejmanowski
