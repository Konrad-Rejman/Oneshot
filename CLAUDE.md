# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## Commands

```bash
python main.py                                   # run the game (needs Ollama + a GM model pulled)
.venv312\Scripts\python.exe -m pytest tests -q   # run the test suite (~1s, no Ollama/models needed)
```

Setup (Python 3.12, the Ollama models, `python -m spacy download en_core_web_md`)
is in README.md. The BERTScore model (`roberta-large`, ~1.4 GB) downloads lazily
on the first summary score, not at startup.

## Documentation & comment style

This repo travels light: documentation is **just barely good enough**. The test
for whether a doc or comment earns its place is the **definition of done** — it
should state something needed to consider a change done or to safely extend the
code (an invariant, a constraint, a non-obvious *why*, a rule the tests don't
enforce). If the code or a test already says it, don't restate it.

- **Code is the source of truth for *what*; comment the *why*.** Trade-offs,
  gotchas, load-bearing constraints — not the mechanics the line below already
  shows. A comment that paraphrases its code is bloat; delete it.
- **Tests are executable documentation.** Don't describe in prose what a test
  pins down — point to the test instead.
- **Single source of truth.** A fact lives in one place; cross-link rather than
  duplicate it across README / ROADMAP / CLAUDE.md / code.
- **Present tense, no history.** Describe the code as it is now — no
  "previously", "used to", "was replaced", or roadmap-phase storytelling. A bare
  "(ROADMAP 2.3)" cross-reference is fine.
- **Barely sufficient beats comprehensive.** Five bullets over five paragraphs.
  Add documentation when something is non-obvious and stable, not by reflex.
- Multi-line docstrings: `'''` on its own line, text on the next, closing `'''`
  on its own line; single-line docstrings stay on one line. Applies to
  docstrings, not multi-line string *data* (the rules prompt, scenario text).

## Testing

A `PostToolUse` hook (`.claude/hooks/run-tests.ps1`, registered in
`.claude/settings.json`) runs the suite after every Edit/Write to a project
`.py` file and feeds failures back. **If the hook reports a failure, fix the
code — or, when the behaviour change was intentional, update the matching test
in the same change. Never disable the hook or delete a test to get past a
failure without the user's say-so.**

The suite covers the deterministic logic only — pure functions tested directly;
Ollama and the spaCy/BERT models are never loaded (`tests/conftest.py` stubs
`spacy`; BERT is monkeypatched). Each `tests/test_*.py` is the contract for its
module — read the test, not a paraphrase of it.

**Binding rule:** any intentional behaviour change to memory trimming, summary
parsing/classification, the keyword lists, prompt assembly, the STATE-line
grammar or progression clamping, the scenarios.json format, the accounts.json
format / hashing / authentication (`tests/test_accounts.py`), or the training
validators/spec samplers/turn-mechanics (`training/outcomes.py`) must update the
corresponding tests in the same change.

Deliberately **not** asserted on, so they can be iterated freely: the rules
system-prompt wording; interactive menus and exact rendering (colours, box
characters, prompt text — only `ui.py`'s pure style helpers and rendered data
content are tested); and the exact prompt framing in `_build_prompt_from_memory`
(only content presence + order). Extend the suite the same way when adding
deterministic logic.

## Architecture

A terminal loop where a local LLM plays a D&D-style Game Master. Every
print/input goes through `ui.py` (a `rich` presentation layer), so game logic
never touches `print`/`input` directly and a later full-screen TUI only has to
reimplement `ui.py`.

**Modules:** `main.py` (account screen, main menu, session/save restore, game
loop) · `accounts.py` (login credentials as sha512 hashes + the persistent
per-user default model, in `accounts.json`) · `context.py` (`context_update` —
the per-turn pipeline) · `model.py` (Ollama calls, prompt assembly,
base/fine-tuned toggle) · `gm_rules.py` (the rules system prompt, shared with
training) · `character.py` / `progression.py` (player dataclasses + STATE-line
parsing/clamping) · `rolls.py` · `scoring.py` (summary-candidate scoring) ·
`saves.py` / `scenarios.py` (JSON stores) · `ownership.py` (per-user visibility
/ edit-delete rules for the shared character & scenario stores) · `training/`
(synthetic dataset + QLoRA fine-tune).

**Startup flow (`main.py:main`):** ensure setup/Ollama · `accounts.ensure_seed`
(creates the `u00`/`admin` account on first run) · `account_screen` (log in /
create account) · one-time `migrate_*` claims of pre-account data · first-login
default-model init (`accounts` ↔ `model.choose_default_model`) · resume a
user-owned `backup.pkl` if present · `menu_loop` (New game · Continue ·
Characters · Scenarios · Settings · Exit), all arrow-navigated via `ui.select`.
A session ends by raising `context.SessionEnd` (Ctrl+C or an unrevived death,
after `save()`), which `run_game` catches to return to the menu rather than
exiting; a crash still `backup()`s and `quit()`s.

**Per-turn data flow (`context.py:context_update`):**

1. Render the status bar (`ui.status_bar`), take the player's action, show the
   turn's 5 colour-coded D20s (`ui.dice`).
2. Append the rolls (`rolls.py`), character sheet (`Character.to_prompt`) and
   progression STATUS block (`Progression.to_prompt`) to the system prompt, so
   the model uses real dice/stats/HP instead of inventing them.
3. Pre-send trim (`_trim_presend`): drop oldest messages until under
   `TOKEN_LIMIT`. Prompt = `[rules+rolls] + [summary] + [recent messages] + [action]`.
4. Stream the response (`model.generate_response`). The mandatory end-of-reply
   STATE line is stripped before storage (`parse_state_changes`) and applied at
   end of turn (`apply_state_changes`, after the summary phase, so a crash backs
   up consistent state) with clamping; level-up/death menus follow.
5. Classify which summary sections the exchange touched (`_affected_sections` —
   a STATE change always includes PLAYER STATUS). Regenerate only those via a
   second model call producing 3 candidates; force a full refresh after
   `SUMMARY_UPDATE_INTERVAL` quiet turns (`_apply_forced_update`).
6. Pick the best candidate (`scoring.select_best_candidate`) and merge it in.
7. Post-summary trim (`_trim_to_memory_budget`) so next turn fits `TOKEN_LIMIT`.

**Load-bearing invariants:**

- Switch the active GM model only via `model.set_active_model` (never reassign
  `MODEL_NAME`); it is not part of saved state and shows in the status bar.
- Train and inference prompts must match: the dataset is built from the
  production prompt assembly (`gm_rules.RULES_TEXT` + the `to_prompt`s +
  `rolls_message`), so **changing the rules prompt or a `to_prompt` format means
  regenerating the training dataset.**
- The training dataset is synthetic-only; the licensing rationale in
  `training/COMPLIANCE.md` is binding — re-read it before adding any data source.
- Bump `saves.SAVE_VERSION` when adding a persisted state key, keeping older
  saves loadable.

State carried across turns and the persistence formats (named save slots, crash
`backup.pkl`) are defined in `main.py:_state_dict` / `session_from_state`; a live
session is a `SimpleNamespace` with those same fields, and `save`/`backup` are
closures over it (`make_save` / `make_backup`).

**Per-user ownership:** the username typed at startup *is* the owner tag. Saved
stories are private — each user's slots live in `saves/<username>/`, so the
directory is the privacy boundary. Characters and scenarios are shared (anyone
can load any of them) but stored as owner-tagged record lists and gated by
`ownership.py`: only the creator may edit or delete one, and the picker
(`ui.select`) hides other users' entries behind a toggle. The pre-ownership
flat saves / `{name: payload}` stores are claimed by the first user to run via
the `migrate_*` functions. The binding-rule format tests are
`tests/test_ownership.py` plus the CRUD/migration tests in
`test_saves.py` / `test_character.py` / `test_scenarios.py`.

Tunable constants live beside the code that uses them. ROADMAP.md tracks planned
work and records why the implementation diverged from each plan.
