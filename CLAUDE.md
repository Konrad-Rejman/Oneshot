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
3. **Pre-send trim:** oldest messages are dropped from the prompt until the estimated token count is under `TOKEN_LIMIT` (4096). Estimation uses `len(content) // 4` per message.
4. The model receives: `[system rules + rolls] + [hierarchical summary] + [as many recent messages as fit] + [current action]`
5. Response is streamed from Ollama (`model.py:generate_response`)
6. A second model call generates 3 candidate updated summaries of the story state
7. The best summary is selected by a weighted score of cosine similarity (0.5) + ROUGE-1/2/L (0.2 each) against the reference (old summary + last interactions)
8. **Post-summary trim:** persistent `memory` is trimmed (oldest first) so that next turn's full prompt will fit under 4096 tokens, using the updated summary's actual token cost: `budget = TOKEN_LIMIT - rules_tokens - ROLLS_TOKEN_RESERVE - summary_tokens - ACTION_TOKEN_RESERVE`

**State tracked across turns:**
- `chatlogs` — full conversation history (written to file on exit)
- `memory` — token-budget-bounded history passed to the model each turn; retains as many messages as fit within the 4096-token limit (adaptive — more history early in a session when messages are short)
- `hierarchical_summary` — compressed story state string with sections OVERALL STORY / CURRENT QUEST / PLAYER STATUS
- `context_logs` — what was in memory at each prompt (for debugging/analysis)
- `tokens` — cumulative prompt token count from Ollama's `prompt_eval_count`

**Session persistence:**
- Clean exit (Ctrl+C): saves transcript + context logs to `sessions/<number>/`, appends row to `data.csv`
- Unexpected crash: writes `backup.pkl` with full state; on next launch `main.py` detects this file and resumes the interrupted session. Delete `backup.pkl` manually after the data has been loaded.

## Key Constants

- `model.py`: `MODEL_NAME = "mistral:instruct"`, `OLLAMA_API = "http://localhost:11434/api/generate"`
- `rolls.py`: `roll_num = 5` — number of D20 rolls per turn
- `context.py`: `TOKEN_LIMIT = 4096` — maximum estimated tokens per prompt; `ROLLS_TOKEN_RESERVE = 30` — token budget reserved for the rolls message; `ACTION_TOKEN_RESERVE = 200` — token budget reserved for the user's next action in post-summary trim
