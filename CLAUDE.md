# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Program

```bash
python main.py
```

Requires Ollama running locally (`http://localhost:11434`) with the `mistral:instruct` model pulled:

```bash
ollama pull mistral:instruct
ollama serve
```

## Required Setup Before First Run

- A `sessions/` directory in the project root (for saving session transcripts)
- A `data.csv` file with headers `,Session,User,Tokens,Playtime (s)` (for session analytics)
- Python 3.12 (required for GPU/torch compatibility)
- spaCy model: `python -m spacy download en_core_web_md`

## Architecture

The game runs as a terminal loop where the LLM plays a D&D-style Game Master.

**Data flow per turn** (`context.py:context_update`):

1. User inputs their action
2. 5 pre-generated D20 rolls (`rolls.py`) are appended to the system prompt so the model uses them instead of hallucinating numbers
3. The model receives: `[system rules + rolls] + [hierarchical summary] + [last n=3 interactions] + [current action]`
4. Response is streamed from Ollama (`model.py:generate_response`)
5. A second model call generates 3 candidate updated summaries of the story state
6. The best summary is selected by a weighted score of cosine similarity (0.5) + ROUGE-1/2/L (0.2 each) against the reference (old summary + last interactions)
7. Only the last `2*n` messages are kept in `memory` for the next turn

**State tracked across turns:**
- `chatlogs` — full conversation history (written to file on exit)
- `memory` — sliding window passed to model each turn (last 6 messages)
- `hierarchical_summary` — compressed story state string with sections OVERALL STORY / CURRENT QUEST / PLAYER STATUS
- `context_logs` — what was in memory at each prompt (for debugging/analysis)
- `tokens` — cumulative prompt token count from Ollama's `prompt_eval_count`

**Session persistence:**
- Clean exit (Ctrl+C): saves transcript + context logs to `sessions/<number>/`, appends row to `data.csv`
- Unexpected crash: writes `backup.pkl` with full state; on next launch `main.py` detects this file and resumes the interrupted session. Delete `backup.pkl` manually after the data has been loaded.

## Key Constants

- `model.py`: `MODEL_NAME = "mistral:instruct"`, `OLLAMA_API = "http://localhost:11434/api/generate"`
- `rolls.py`: `roll_num = 5` — number of D20 rolls per turn
- `context.py`: `n=3` — number of recent interactions kept in sliding window memory
