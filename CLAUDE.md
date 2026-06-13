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

The suite (~160 tests, sub-second) covers the deterministic logic only — no Ollama, no spaCy/BERT model load (`tests/conftest.py` stubs `spacy` before importing `context`, since `scoring.py` — imported by `context.py` — loads `en_core_web_md` at import time; the BERT model loads lazily and is monkeypatched in tests):

- `test_compile.py` — every top-level `.py` file compiles (catches syntax errors without importing `main.py`'s interactive code)
- `test_context_trim.py` — `_trim_presend` / `_trim_to_memory_budget` / `_estimate_tokens` budget contracts
- `test_summary.py` — `_parse_sections` / `_build_summary` round-trip, markdown-tolerant header parsing (`**CURRENT QUEST**:`) and `_parse_partial_sections` candidate salvage, `_classify_exchange` keyword routing (prefix matching: stems like `injur` match "injured"; `heal` matching "healthy" is an accepted trade-off)
- `test_scoring.py` — composite-score weights (0.6/0.2/0.2), candidate selection argmax, lazy-loading contract (metric helpers monkeypatched; BERT never loaded)
- `test_rolls.py`, `test_model_prompt.py`, `test_scenarios.py` — roll format (incl. the `roll_values`/`rolls_message` split and `rolls()` equivalence), prompt-assembly ordering, the model toggle's deterministic parts (`is_installed` name/tag matching, `set_active_model`/`active_model`, base default — `installed_models()` itself queries Ollama and is untested), scenarios.json file-format CRUD
- `test_ui.py` — `roll_style` consequence-tier colours, `hp_style` thresholds (green above 2/3, yellow above 1/3, red at/below), capture-based checks that the dice line and status bar render the player-facing values incl. the active-model segment (no colour/box-character assertions)
- `test_training_validators.py`, `test_training_specs.py`, `test_training_outcomes.py` — the Phase 3 pipeline's deterministic parts: dataset validators (strict canonical STATE-line grammar — stricter than the runtime parser on purpose — dice announced only as a prefix of the roll pool, plain-text/markdown bans, character-break phrases, the `validate_narration` dice/rolls ban, per-stage composite gates), spec sampling (always-valid `Character`/`Progression` state, no spell actions sampled, both tier-shift bands reachable, seed determinism), and the deterministic turn mechanics (`outcomes.py`: tier boundaries, the CHARACTER stat-shift with natural-roll/clamp rules, consequence mapping — success XP band, physical-only HP cost, critical-failure item loss — and that every emitted STATE line round-trips through `validators.check_state_line` across the full roll×stat grid); Ollama is never called
- `test_character.py` — `Character` stat validation, dict round-trip, characters.json file-format CRUD, `describe_stat` phrase mapping, `to_prompt` content presence
- `test_progression.py` — `Progression` validation/dict round-trip (JSON-safe), XP curve and level-up effects, death/resurrection clamping, STATE-line grammar (`parse_state_changes`, markdown-tolerant like the summary headers) and `apply_state_changes` clamping rules, `to_prompt` content presence; the interactive level-up/death prompts are deliberately untested
- `test_saves.py` — save-name sanitisation, `saves/` slot file-format CRUD (state keys incl. `Progression` + `Version`/`Name` metadata round-trip), transcript text formatting, export writing

**A `PostToolUse` hook (`.claude/hooks/run-tests.ps1`, registered in `.claude/settings.json`) runs this suite automatically after every Edit/Write to a project `.py` file and feeds failures back.** If the hook reports a failure after your change, fix the code or — if the behavior change was intentional — update the matching test in the same change. Never disable the hook or delete a test to get past a failure without the user's say-so.

**Rule: any intentional behavior change to memory trimming, summary parsing/classification, the keyword lists, prompt assembly, the STATE-line grammar or progression clamping rules, the scenarios.json format, or the training-data validators/spec samplers/turn-mechanics (`training/outcomes.py`) must update the corresponding tests in the same change.**

The tests deliberately do NOT assert on (see ROADMAP.md):
- Rules system-prompt text — Phase 1.1 rewrites it
- Interactive menus and exact rendering (colours, box characters, prompt wording) — only `ui.py`'s pure style helpers and rendered data content are tested
- Exact prompt framing in `_build_prompt_from_memory` (only content presence + order) — Phase 3 fine-tuning may change the format

When implementing roadmap items, extend the suite to cover the new deterministic logic the same way (pure functions tested directly; Ollama/model calls never invoked).

## Comment Style

- Comments and docstrings are matter-of-fact present tense: state what the code does, takes and returns ("Parses the STATE line; returns (clean_text, changes)") — never narrate history or intent ("this now does", "this was meant to", "X was replaced by Y"). A bare roadmap cross-reference like "(ROADMAP 2.3)" is fine.
- Multi-line docstrings open with `'''` on its own line; the text starts on the next line, and the closing `'''` is also on its own line. Single-line docstrings stay on one line. This applies to docstrings, not to multi-line string *data* (the rules prompt, scenario text).

## Architecture

The game runs as a terminal loop where the LLM plays a D&D-style Game Master.

**Model toggle (ROADMAP 3):** the rules system prompt lives in `gm_rules.py` (importable — `main.py` runs interactive code at import time) so the game and the training pipeline share one copy. `model.py` knows two models: `BASE_MODEL_NAME` (`mistral:instruct`, always the default) and `FINETUNED_MODEL_NAME` (`oneshot-gm`, the unpublished fine-tune registered via `training/Modelfile`). At startup `choose_model()` queries Ollama's `/api/tags` and offers a per-session base/fine-tuned menu only when the fine-tune is installed; the active model is switched via `set_active_model` (never by reassigning `MODEL_NAME` directly), is not part of saved state, and is shown in the status bar.

**Training pipeline (ROADMAP 3.1/3.2, `training/`):** generates a fully synthetic, self-distilled dataset — the local base model writes the prose (summary → scene → player action → GM narration) from structural specs (`specs.py`), gated per stage by strict validators (`validators.py`), but the **turn mechanics are computed deterministically** (`outcomes.py`): from the spec's roll pool, relevant stat and action the pipeline builds the check announcement (correct stat + `pool[0]`), the consequence tier (with the CHARACTER stat shift) and the canonical STATE line, then asks the model only to narrate the given outcome (`validate_narration` forbids any dice/mechanics talk in the prose). This is why the all-model-authored data failed — the base model misnamed the stat ~half the time and emitted `STATE: none` 100% of the time, behaviours filtering cannot fix; moving them to code guarantees every example demonstrates them. Prompts are assembled with the production code (`gm_rules.RULES_TEXT` + `to_prompt`s + `rolls_message` flattened by `model._build_prompt_from_memory`) so train/inference formats cannot drift — **changing the rules prompt or the `to_prompt` formats means regenerating the dataset**. `train_qlora.py` (Unsloth QLoRA, runs on Kaggle free T4, not locally) exports a Q4_K_M GGUF. `training/data/` and `training/private/` (paid-compute guide) are gitignored; the compliance rationale — synthetic-only, no third-party datasets, no Claude-authored dataset text — is binding and recorded in `training/COMPLIANCE.md`; re-read it before adding any data source.

**Terminal UI (ROADMAP 2.4):** every print/input goes through `ui.py`, a presentation layer built on `rich` — a status-bar panel (name, colour-coded HP, level, XP, tokens) above each turn's input line, GM speech streamed under a `GM` rule, the turn's D20 pool colour-coded by consequence tier (`ui.roll_style`), dim system messages, magenta game events, yellow warnings, red errors. Game text is printed with `markup=False`/`Text()` so brackets in model output are never parsed as markup. Game logic never calls `print`/`input` directly, so a future full-screen TUI (`textual`) only has to reimplement `ui.py`.

**Data flow per turn** (`context.py:context_update`):

1. The status bar is rendered (`ui.status_bar`), then the user inputs their action; the turn's 5 D20 values are then shown colour-coded (`ui.dice`)
2. 5 pre-generated D20 rolls (`rolls.py`), the character sheet (`character.py:Character.to_prompt`) and the progression STATUS block (`progression.py:Progression.to_prompt` — HP, level, XP, inventory, features) are appended to the system prompt — the rolls so the model uses them instead of hallucinating numbers, the sheet so the model judges actions through the character's stats (D&D six on a clean 1-10 scale, no modifiers; a relevant stat of 8+ shifts the roll's consequence tier up by one, 3- shifts it down, naturals never shift), the STATUS block so the model references HP/items accurately instead of remembering them
3. **Pre-send trim:** oldest messages are dropped from the prompt until the estimated token count is under `TOKEN_LIMIT` (4096). Estimation uses `len(content) // 4` per message.
4. The model receives: `[system rules + rolls] + [hierarchical summary] + [as many recent messages as fit] + [current action]`
5. Response is streamed from Ollama (`model.py:generate_response`)
5a. The machine-read STATE line the rules require at the end of every reply (`STATE: HP -3; XP +25; GAIN torch; LOSE rope`) is stripped before the response is stored anywhere (`progression.py:parse_state_changes`); the parsed changes are applied at the end of the turn (`apply_state_changes`, after the summary phase so a crash backs up consistent state) with clamping — HP to [0, max], XP floored at the current level, invalid entries ignored. A missing state line means no changes. Level-ups (flat 100-XP curve, interactive class-feature choice) and death (HP 0 → resurrect at half HP for an XP penalty, or end the story) are handled right after
6. The exchange is classified by keyword (`_classify_exchange`) to determine which summary sections it affected — a turn whose STATE line reported changes always includes PLAYER STATUS (`_affected_sections`); a second model call generates 3 candidate updates for just those sections. If no section matched for `SUMMARY_UPDATE_INTERVAL` (5) consecutive turns since the summary last changed, a full refresh of all sections is forced (`_apply_forced_update`; the counter lives in the `main.py` loop, is not persisted across resumes, and resets only on a successful update — so a failed forced refresh retries next turn)
7. The best candidate is selected by `scoring.py:select_best_candidate` — a weighted score of BERTScore-F1 (0.6) + ROUGE-L (0.2) + cosine similarity (0.2) against the reference (old affected summary sections + last two exchanges); falls back to the lexical signals alone if BERTScore fails
8. **Post-summary trim:** persistent `memory` is trimmed (oldest first) so that next turn's full prompt will fit under 4096 tokens, using the updated summary's actual token cost: `budget = TOKEN_LIMIT - rules_tokens - character_tokens - ROLLS_TOKEN_RESERVE - summary_tokens - ACTION_TOKEN_RESERVE`

**State tracked across turns:**
- `chatlogs` — full conversation history (written to file on exit)
- `memory` — token-budget-bounded history passed to the model each turn; retains as many messages as fit within the 4096-token limit (adaptive — more history early in a session when messages are short)
- `hierarchical_summary` — compressed story state string with sections OVERALL STORY / CURRENT QUEST / PLAYER STATUS
- `context_logs` — what was in memory at each prompt (for debugging/analysis)
- `tokens` — cumulative prompt token count from Ollama's `prompt_eval_count`
- `character` — the `character.py:Character` dataclass being played (chosen/created at startup via `choose_character()`, saved as a dict in `backup.pkl` and in `characters.json` for custom characters)
- `progression` — the `progression.py:Progression` dataclass (HP/max HP, level, XP, inventory, features; created at new-game time via `new_progression()` — max HP from Constitution — and mutated in place by `context_update`, so it is not part of the return tuple; saved as a dict under the `Progression` key)

**Session persistence:**
- Clean exit (Ctrl+C): saves transcript + context logs to `sessions/<number>/`, appends row to `data.csv`, then offers a named save slot and a transcript export (plain text or Markdown, written to `exports/`)
- Named save slots (`saves.py`): one JSON file per slot in `saves/`, holding the same state keys as `backup.pkl` (built by `main.py:session_state`) plus `Version`/`Name` metadata — `SAVE_VERSION` 2 added the `Progression` key, version-1 saves load with a fresh progression (`main.py:restore_session`); when saves exist, a startup menu (`choose_save()`) lists them most-recent-first to continue, export, or delete. Loading goes through `main.py:restore_session`, shared with the backup-resume flow.
- Unexpected crash: writes `backup.pkl` with full state; on next launch `main.py` detects this file and resumes the interrupted session (takes priority over the save-slot menu). Delete `backup.pkl` manually after the data has been loaded.

## Key Constants

- `model.py`: `BASE_MODEL_NAME = "mistral:instruct"`, `FINETUNED_MODEL_NAME = "oneshot-gm"`, `MODEL_NAME` — the active model (starts as base; switch only via `set_active_model`), `OLLAMA_API = "http://localhost:11434/api/generate"`, `OLLAMA_TAGS_API = "http://localhost:11434/api/tags"`
- `rolls.py`: `roll_num = 5` — number of D20 rolls per turn (`roll_values()` generates the list, `rolls_message(values)` renders the prompt text, `rolls()` composes the two)
- `ui.py`: one style constant per output kind (`SYSTEM_STYLE`, `EVENT_STYLE`, `WARN_STYLE`, `ERROR_STYLE`, `PROMPT_STYLE`, `HEADING_STYLE`, `GM_RULE_STYLE`); `roll_style(value)` / `hp_style(hp, max_hp)` — pure tier/threshold helpers, tested in `test_ui.py`
- `character.py`: `STAT_NAMES` — the six stats (Strength/Dexterity/Constitution/Intelligence/Wisdom/Charisma); `STAT_MIN/STAT_MAX = 1/10` — clean stat scale, no modifiers; `STAT_POOL = 36` — point pool for interactive stat allocation
- `context.py`: `TOKEN_LIMIT = 4096` — maximum estimated tokens per prompt; `ROLLS_TOKEN_RESERVE = 30` — token budget reserved for the rolls message; `ACTION_TOKEN_RESERVE = 200` — token budget reserved for the user's next action in post-summary trim; `SUMMARY_UPDATE_INTERVAL = 5` — turns without a successful summary update before a full refresh is forced
- `scoring.py`: `BERTSCORE_MODEL = "roberta-large"` — BERTScore base model (lazy-loaded on first scoring call; must ship safetensors weights — transformers 5.x refuses `.bin` checkpoints on the venv's torch 2.5.1); `BERT_WEIGHT/ROUGE_WEIGHT/COSINE_WEIGHT = 0.6/0.2/0.2` — composite scoring weights
- `saves.py`: `SAVES_DIR = "saves"` / `EXPORTS_DIR = "exports"` — both created on demand, no setup needed; `SAVE_VERSION = 2` — save-format version written into each slot (2 added the `Progression` key; bump again when new state keys are added); `EXPORT_FORMATS = ['txt', 'md']`
- `progression.py`: `XP_PER_LEVEL = 100` — flat XP curve, level N at (N-1)×100 XP; `MAX_LEVEL = 10` — matches the 1-10 stat scale; `STARTING_HP_BASE = 4` — starting max HP = 4 + Constitution; `HP_PER_LEVEL = 2` — max HP per level-up; `RESURRECTION_XP_PENALTY = 50` — XP cost of resurrection (floored so no level is lost)
