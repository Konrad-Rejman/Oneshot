# Oneshot – Local LLM Pen-and-Paper RPG

A terminal RPG where a local LLM acts as your Game Master. You describe your character's actions each turn and the GM responds with the outcome, advancing the story. A D20 dice system resolves chance-based actions, your character's stats and progression (HP, XP, levels, inventory) shape the outcomes, and an automatic context summarization system maintains story continuity across a full session.

## Setup

### Prerequisites

**Python 3.12** (required for compatibility with GPU processing)

**Ollama**, with at least one of the two GM models pulled — the base model, the fine-tuned model, or both:

```bash
ollama pull mistral:instruct              # base GM (default)
ollama pull Konrad-Rejman/gm-istral-v01   # fine-tuned GM (optional)
```

The base `mistral:instruct` is the default Game Master, so it's all you need to play. The fine-tuned `Konrad-Rejman/gm-istral-v01` is optional (see [Fine-Tuned GM Model](#fine-tuned-gm-model-optional) below) — when it's installed you can pick which model is your default on first login or change it later in Settings; the choice persists per account.

You don't need to start the server yourself — on launch the program checks whether Ollama is already running and starts it for you if not (falling back to asking you to run `ollama serve` manually if that fails).

### Installation

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_md
```

The first time a session scores a summary update, a ~1.4 GB BERTScore model (`roberta-large`) is downloaded automatically — a one-time wait during play, not a setup step.

No manual file or folder setup is needed: the `sessions/` transcript folder and the `data.csv` analytics file are created automatically on first run (as are `saves/` and `exports/`).

## Running

```bash
python main.py
```

**Startup** opens an **account screen**: log in or create an account (username +
password). Passwords are entered masked and stored only as an sha512 hash in
`accounts.json`. A seeded `u00` account (password `admin`) owns the bundled
content — log in as it to reach the existing characters, scenarios and saves.
Your username is the owner tag for everything you create, so a shared install
keeps players apart. On your first login you're asked once to pick a default GM
model (changeable later in Settings).

After login the **main menu** (navigated with the **arrow keys + Enter**) offers:

- **New game** — start a fresh story. Pick a **Scenario** (the built-in opening,
  one you've saved, or `New scenario` to write your own opening scene and
  three-part summary; stored in `scenarios.json`) and a **Character** (the
  default, one you've made, or `New character` — name, race, class, background,
  six ability scores from a shared point pool; stored in `characters.json`). The
  GM reads the sheet every turn, so your stats shape outcomes.
- **Continue** — resume one of *your* saved stories (newest first; the GM's last
  message is re-printed). Other players' saves are never shown; they live in
  `saves/<username>/`.
- **Characters** / **Scenarios** — create, edit or delete your own.
- **Settings** — change your persistent default GM model.
- **Exit** — leave the program.

Characters and scenarios are shared between players and tagged with their
creator (`Gandalf (alice)`); other players' entries are hidden until you select
the `[ ] Show other users'…` line to toggle them on. You can load anyone's, but
only edit or delete your own.

**During play** a status panel above the input line shows name, HP (green /
yellow / red by how hurt you are), level, XP and the running token count. After
you submit an action the turn's five D20 rolls appear — coloured red (failure)
through yellow and cyan to green (success) — and the GM's response streams under
a `GM` divider. The GM tracks HP, XP and inventory: dangerous failures cost HP,
healing restores it, challenges earn XP. Enough XP levels you up (more max HP, a
full heal, and a stat or class-feature reward); reaching 0 HP lets you resurrect
at half HP for an XP cost or end the story.

Press `Ctrl+C` to end the session and return to the main menu: you can keep the
story in a named slot and export the transcript as text or Markdown to
`exports/`. If the program crashes mid-turn it writes `backup.pkl` with the full
state and resumes from it after your next login (only if the backup is yours).

## Fine-Tuned GM Model (optional)

The `training/` directory contains a pipeline for fine-tuning the GM model so it more reliably calls a check on the right stat, consumes the pre-rolled dice in order, and keeps its end-of-turn state-tracking line correct. The training data is fully synthetic and generated locally — the base model writes the prose while the dice, stat checks and state-tracking line are computed in code from each example's setup — so the public repository carries no third-party datasets (see `training/COMPLIANCE.md` for the licensing rationale, and `training/README.md` for how to generate the data and run the training on a free cloud GPU).

The base model is never replaced. The fine-tuned model is published on the Ollama registry as `Konrad-Rejman/gm-istral-v01` — pull it with `ollama pull Konrad-Rejman/gm-istral-v01` (or build your own from `training/` and register it under that name). When it is installed, the game lets you choose between the two as your per-account default (on first login or in Settings) and shows the active model in the status panel. Without it installed, nothing changes.

## Testing

```bash
python -m pytest tests -q
```

The test suite checks the deterministic game logic — token-budget trimming, summary parsing and candidate scoring, the D20 roll format, character validation, the progression rules (HP/XP bookkeeping, level-ups, death and resurrection), the terminal UI's colour rules (dice tiers, HP thresholds) and rendered status values, the scenario, character and save-slot storage formats, the account registry (password hashing, login and default-model persistence), the model toggle's name matching, and the training pipeline's validators, spec sampling and deterministic turn mechanics — and runs in under a second. It doesn't need Ollama running or the spaCy/BERTScore models downloaded, so it works before full setup is complete.

When editing the project with Claude Code, a hook runs the suite automatically after every change to a Python file and reports any failures.

## Credits

By Konrad Rejmanowski
