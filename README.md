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

The base `mistral:instruct` is the default Game Master, so it's all you need to play. The fine-tuned `Konrad-Rejman/gm-istral-v01` is optional (see [Fine-Tuned GM Model](#fine-tuned-gm-model-optional) below) — with both installed you're offered a choice at startup; with only the fine-tuned model installed, pick it from that startup menu.

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

**Startup** walks you through a few menus (each takes a number, or a word like
`new` / `export` / `delete`):

- **Story** — continue a saved story (newest first; the GM's last message is
  re-printed), or start a `new` one. Saved stories live in `saves/`.
- **Scenario** (new story only) — the built-in opening or one you've saved, or
  `new` to write your own opening scene and three-part summary. Stored in
  `scenarios.json`.
- **Character** — the default or one of your own; `new` builds one (name, race,
  class, background, six ability scores from a shared point pool). Stored in
  `characters.json`. The GM reads the sheet every turn, so your stats shape
  outcomes.

**During play** a status panel above the input line shows name, HP (green /
yellow / red by how hurt you are), level, XP and the running token count. After
you submit an action the turn's five D20 rolls appear — coloured red (failure)
through yellow and cyan to green (success) — and the GM's response streams under
a `GM` divider. The GM tracks HP, XP and inventory: dangerous failures cost HP,
healing restores it, challenges earn XP. Enough XP levels you up (more max HP, a
full heal, and a stat or class-feature reward); reaching 0 HP lets you resurrect
at half HP for an XP cost or end the story.

Press `Ctrl+C` to exit and save: you can keep the story in a named slot and
export the transcript as text or Markdown to `exports/`. If the program crashes,
it writes `backup.pkl` with the full state and resumes from it on the next run —
delete that file once loaded to start fresh.

## Fine-Tuned GM Model (optional)

The `training/` directory contains a pipeline for fine-tuning the GM model so it more reliably calls a check on the right stat, consumes the pre-rolled dice in order, and keeps its end-of-turn state-tracking line correct. The training data is fully synthetic and generated locally — the base model writes the prose while the dice, stat checks and state-tracking line are computed in code from each example's setup — so the public repository carries no third-party datasets (see `training/COMPLIANCE.md` for the licensing rationale, and `training/README.md` for how to generate the data and run the training on a free cloud GPU).

The base model is never replaced. The fine-tuned model is published on the Ollama registry as `Konrad-Rejman/gm-istral-v01` — pull it with `ollama pull Konrad-Rejman/gm-istral-v01` (or build your own from `training/` and register it under that name). When it is installed, the game offers a choice between the two at startup (defaulting to the base model) and shows the active model in the status panel. Without it installed, nothing changes.

## Testing

```bash
python -m pytest tests -q
```

The test suite checks the deterministic game logic — token-budget trimming, summary parsing and candidate scoring, the D20 roll format, character validation, the progression rules (HP/XP bookkeeping, level-ups, death and resurrection), the terminal UI's colour rules (dice tiers, HP thresholds) and rendered status values, the scenario, character and save-slot storage formats, the model toggle's name matching, and the training pipeline's validators, spec sampling and deterministic turn mechanics — and runs in under a second. It doesn't need Ollama running or the spaCy/BERTScore models downloaded, so it works before full setup is complete.

When editing the project with Claude Code, a hook runs the suite automatically after every change to a Python file and reports any failures.

## Credits

By Konrad Rejmanowski
