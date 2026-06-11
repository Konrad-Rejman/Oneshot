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
- The BERTScore model (`roberta-large`, ~1.4 GB) downloads automatically on the first summary-scoring call of the first session — not at startup

## Testing

```bash
.venv312\Scripts\python.exe -m pytest tests -q
```

The suite (~60 tests, sub-second) covers the deterministic logic only — no Ollama, no spaCy/BERT model load (`tests/conftest.py` stubs `spacy` before importing `context`, since `scoring.py` — imported by `context.py` — loads `en_core_web_md` at import time; the BERT model loads lazily and is monkeypatched in tests):

- `test_compile.py` — every top-level `.py` file compiles (catches syntax errors without importing `main.py`'s interactive code)
- `test_context_trim.py` — `_trim_presend` / `_trim_to_memory_budget` / `_estimate_tokens` budget contracts
- `test_summary.py` — `_parse_sections` / `_build_summary` round-trip, markdown-tolerant header parsing (`**CURRENT QUEST**:`) and `_parse_partial_sections` candidate salvage, `_classify_exchange` keyword routing (prefix matching: stems like `injur` match "injured"; `heal` matching "healthy" is an accepted trade-off)
- `test_scoring.py` — composite-score weights (0.6/0.2/0.2), candidate selection argmax, lazy-loading contract (metric helpers monkeypatched; BERT never loaded)
- `test_rolls.py`, `test_model_prompt.py`, `test_scenarios.py` — roll format, prompt-assembly ordering, scenarios.json file-format CRUD
- `test_character.py` — `Character` stat validation, dict round-trip, characters.json file-format CRUD, `describe_stat` phrase mapping, `to_prompt` content presence
- `test_saves.py` — save-name sanitisation, `saves/` slot file-format CRUD (state keys + `Version`/`Name` metadata round-trip), transcript text formatting, export writing

**A `PostToolUse` hook (`.claude/hooks/run-tests.ps1`, registered in `.claude/settings.json`) runs this suite automatically after every Edit/Write to a project `.py` file and feeds failures back.** If the hook reports a failure after your change, fix the code or — if the behavior change was intentional — update the matching test in the same change. Never disable the hook or delete a test to get past a failure without the user's say-so.

**Rule: any intentional behavior change to memory trimming, summary parsing/classification, the keyword lists, prompt assembly, or the scenarios.json format must update the corresponding tests in the same change.**

The tests deliberately do NOT assert on (see ROADMAP.md):
- Rules system-prompt text — Phase 1.1 rewrites it
- Interactive menus/UI — Phase 2 reworks them
- Exact prompt framing in `_build_prompt_from_memory` (only content presence + order) — Phase 3 fine-tuning may change the format

When implementing roadmap items, extend the suite to cover the new deterministic logic the same way (pure functions tested directly; Ollama/model calls never invoked).

## Architecture

The game runs as a terminal loop where the LLM plays a D&D-style Game Master.

**Data flow per turn** (`context.py:context_update`):

1. User inputs their action
2. 5 pre-generated D20 rolls (`rolls.py`) and the character sheet (`character.py:Character.to_prompt`) are appended to the system prompt — the rolls so the model uses them instead of hallucinating numbers, the sheet so the model judges actions through the character's stats (D&D six on a clean 1-10 scale, no modifiers; a relevant stat of 8+ shifts the roll's consequence tier up by one, 3- shifts it down, naturals never shift)
3. **Pre-send trim:** oldest messages are dropped from the prompt until the estimated token count is under `TOKEN_LIMIT` (4096). Estimation uses `len(content) // 4` per message.
4. The model receives: `[system rules + rolls] + [hierarchical summary] + [as many recent messages as fit] + [current action]`
5. Response is streamed from Ollama (`model.py:generate_response`)
6. The exchange is classified by keyword (`_classify_exchange`) to determine which summary sections it affected; a second model call generates 3 candidate updates for just those sections. If no section matched for `SUMMARY_UPDATE_INTERVAL` (5) consecutive turns since the summary last changed, a full refresh of all sections is forced (`_apply_forced_update`; the counter lives in the `main.py` loop, is not persisted across resumes, and resets only on a successful update — so a failed forced refresh retries next turn)
7. The best candidate is selected by `scoring.py:select_best_candidate` — a weighted score of BERTScore-F1 (0.6) + ROUGE-L (0.2) + cosine similarity (0.2) against the reference (old affected summary sections + last two exchanges); falls back to the lexical signals alone if BERTScore fails
8. **Post-summary trim:** persistent `memory` is trimmed (oldest first) so that next turn's full prompt will fit under 4096 tokens, using the updated summary's actual token cost: `budget = TOKEN_LIMIT - rules_tokens - character_tokens - ROLLS_TOKEN_RESERVE - summary_tokens - ACTION_TOKEN_RESERVE`

**State tracked across turns:**
- `chatlogs` — full conversation history (written to file on exit)
- `memory` — token-budget-bounded history passed to the model each turn; retains as many messages as fit within the 4096-token limit (adaptive — more history early in a session when messages are short)
- `hierarchical_summary` — compressed story state string with sections OVERALL STORY / CURRENT QUEST / PLAYER STATUS
- `context_logs` — what was in memory at each prompt (for debugging/analysis)
- `tokens` — cumulative prompt token count from Ollama's `prompt_eval_count`
- `character` — the `character.py:Character` dataclass being played (chosen/created at startup via `choose_character()`, saved as a dict in `backup.pkl` and in `characters.json` for custom characters)

**Session persistence:**
- Clean exit (Ctrl+C): saves transcript + context logs to `sessions/<number>/`, appends row to `data.csv`, then offers a named save slot and a transcript export (plain text or Markdown, written to `exports/`)
- Named save slots (`saves.py`): one JSON file per slot in `saves/`, holding the same state keys as `backup.pkl` (built by `main.py:session_state`) plus `Version`/`Name` metadata; when saves exist, a startup menu (`choose_save()`) lists them most-recent-first to continue, export, or delete. Loading goes through `main.py:restore_session`, shared with the backup-resume flow.
- Unexpected crash: writes `backup.pkl` with full state; on next launch `main.py` detects this file and resumes the interrupted session (takes priority over the save-slot menu). Delete `backup.pkl` manually after the data has been loaded.

## Key Constants

- `model.py`: `MODEL_NAME = "mistral:instruct"`, `OLLAMA_API = "http://localhost:11434/api/generate"`
- `rolls.py`: `roll_num = 5` — number of D20 rolls per turn
- `character.py`: `STAT_NAMES` — the six stats (Strength/Dexterity/Constitution/Intelligence/Wisdom/Charisma); `STAT_MIN/STAT_MAX = 1/10` — clean stat scale, no modifiers; `STAT_POOL = 36` — point pool for interactive stat allocation
- `context.py`: `TOKEN_LIMIT = 4096` — maximum estimated tokens per prompt; `ROLLS_TOKEN_RESERVE = 30` — token budget reserved for the rolls message; `ACTION_TOKEN_RESERVE = 200` — token budget reserved for the user's next action in post-summary trim; `SUMMARY_UPDATE_INTERVAL = 5` — turns without a successful summary update before a full refresh is forced
- `scoring.py`: `BERTSCORE_MODEL = "roberta-large"` — BERTScore base model (lazy-loaded on first scoring call; must ship safetensors weights — transformers 5.x refuses `.bin` checkpoints on the venv's torch 2.5.1); `BERT_WEIGHT/ROUGE_WEIGHT/COSINE_WEIGHT = 0.6/0.2/0.2` — composite scoring weights
- `saves.py`: `SAVES_DIR = "saves"` / `EXPORTS_DIR = "exports"` — both created on demand, no setup needed; `SAVE_VERSION = 1` — save-format version written into each slot (bump when Phase 2.3 adds progression state); `EXPORT_FORMATS = ['txt', 'md']`
