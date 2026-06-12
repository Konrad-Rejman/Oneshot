# Oneshot – Development Roadmap

Planned improvements in rough priority order.

---

## Phase 1 — Core LLM Quality

### 1.1 Revise the Rules System Prompt — IMPLEMENTED

The rules message (`main.py:rules`) now contains all the planned changes:

- The GM persona specifies tone (second-person, present tense, grounded), pacing (resolve the action fully, cliffhangers only on unresolved threats, one beat per reply), and the roll threshold (chance-based actions only, not pure narrative beats)
- The dice system rules are unambiguous: exactly 5 pre-rolled D20s in the system message, consumed left-to-right, one per roll, never invented or paraphrased, never mentioned to the player
- Consequence scaling: 1–5 critical failure with a setback, 6–10 partial failure, 11–15 partial success, 16–20 full success, natural 20 narrative bonus
- The prompt is split into labelled sections — `PERSONA`, `DICE SYSTEM`, `OUTPUT FORMAT`, plus a `CHARACTER` section added by Phase 2.1 (stat-based consequence-tier shifts: a relevant stat of 8+ shifts one tier up, 3- one tier down, naturals never shift)

Tests deliberately do not assert on the prompt wording (see Testing notes in CLAUDE.md), so it can be iterated freely; Phase 3 fine-tuning must keep the production prompt in sync with the training data.

### 1.2 Improve Hierarchical Summary Initialisation and Update Logic — IMPLEMENTED (dynamic initialisation pending)

The update logic now works as planned (`context.py`):

- **Update prompt:** the candidate-generation prompt names the exact section heading(s) the model must output, with an explicit output skeleton and a markdown/numbering ban. Header parsing tolerates markdown decoration (`**CURRENT QUEST**:`), and a candidate covering only some affected sections is still scored (`_parse_partial_sections`) — the merge keeps the old text for whatever it missed. Only an unstructured old summary (regenerated whole) requires full-coverage candidates (`_parse_requested_sections`); if no candidate survives, the previous summary is kept rather than corrupted
- **Selective updates:** each turn's exchange is classified by keyword match (`_classify_exchange`, `QUEST_RESOLUTION_KEYWORDS` / `STATUS_CHANGE_KEYWORDS`) as affecting story / quest / status or none; only the affected section(s) are regenerated and merged into the carried-forward summary. A summary that doesn't parse into the three sections (e.g. a hand-written scenario summary) falls back to whole-summary regeneration. As a staleness guard, a full refresh of all sections is forced after `SUMMARY_UPDATE_INTERVAL` (5) consecutive turns without a successful update (`_apply_forced_update`).

**Remaining work — dynamic initialisation:** the hardcoded `startMessage`/`summary` were replaced by the scenario picker (`scenarios.py:choose_scenario`, with the original opening kept as the always-available Default), but the originally planned model call that generates an opening scene and summary from the character sheet does not exist yet. When added, it should feed `add_scenario()` so generated openings become saved scenarios like hand-written ones.

### 1.3 Better Summary Candidate Selection — IMPLEMENTED (evaluation pending)

New scoring method to replace previous scorer — cosine similarity (0.5) + ROUGE-1/2/L (0.2 each) — which measured n-gram overlap and shallow vector similarity, both of which could favour a candidate that copies the reference wording without genuinely capturing what happened.

Should use **BERTScore** (`bert-score` on PyPI, MIT) instead, with the composite formula `0.6 × BERTScore-F1 + 0.2 × ROUGE-L + 0.2 × cosine` — the existing lexical signals are kept but semantic quality is weighted higher. The reference is the old affected summary section(s) + the last two exchanges. If BERTScore fails at runtime (model unavailable, OOM), scoring falls back to the lexical signals alone rather than ending the session.

**Divergence from the original plan:** the base model is `roberta-large` (MIT, bert-score's English default). The model is a constant (`scoring.py: BERTSCORE_MODEL`) and is loaded lazily on the first scoring call; CUDA is used automatically when available.

**Future work — evaluation:** the scorer was swapped in without the originally planned acceptance gate. To validate it retrospectively: hold out 20 consecutive session turns, run both the old and new scorer on the same candidates, and compare chosen candidates against a hand-ranked ground truth. The new scorer should win on at least 14/20 turns; if it does not, revisit the weights or base model. This requires per-turn candidate logging, which does not exist yet.

---

## Phase 2 — User Interface and Character System

### 2.1 Character Creation

Replace the hardcoded opening scene with a structured character creation flow at startup:

- Name, race, class, background (drawn from SRD 5.1 options)
- Starting ability scores (point-buy or standard array)
- Brief backstory prompt used to dynamically generate both `startMessage` and the initial `summary` via a model call, replacing the hardcoded values in `main.py:38-42/49`
- Character sheet stored as a dataclass and serialised alongside session state

### 2.2 Story Saving and Loading — IMPLEMENTED

Extends the existing session persistence (`saves.py` + `main.py`):

- **Named save slots:** on clean exit (Ctrl+C) the player is offered a named slot; each slot is one JSON file in `saves/` carrying the same state keys as `backup.pkl` plus `Version`/`Name`. Phase 2.3 state (HP, inventory, XP) should be added as new keys with a `SAVE_VERSION` bump, keeping old saves loadable.
- **Load at startup:** when saves exist, a startup menu (`saves.py:choose_save`) lists them most-recent-first to continue, export, or delete; `backup.pkl` crash-resume still takes priority and both restore through the same `main.py:restore_session` path.
- **Transcript export:** plain text (`format_transcript_text`, the same format the `sessions/` files use) or Markdown (`format_transcript_markdown`), written to `exports/`, offered on exit and from the startup menu.

### 2.3 Character Stats and Progression — IMPLEMENTED

All progression state lives in `progression.py:Progression` (HP/max HP, level, XP, per-level spell slots, inventory, named class features), serialised alongside the character in `backup.pkl` and the save slots (`SAVE_VERSION` bumped to 2; version-1 saves load with a fresh progression):

- **Tracking between turns:** the GM model reports each turn's mechanical changes in a machine-read line at the end of its reply (`STATE: HP -3; XP +25; GAIN torch; LOSE rope; SLOT 1 -1`, or `STATE: none`), mandated by the `STATE LINE` rules section. `parse_state_changes` strips the line before the response is stored anywhere and `apply_state_changes` applies it with clamping (HP to `[0, max_hp]`, XP floored at the current level so the model can never de-level, slots to `[0, max]`, invalid entries ignored). A missing or mangled state line degrades safely to "nothing changed". A turn with state changes also forces the PLAYER STATUS summary section into the update set (`context.py:_affected_sections`).
- **Surfacing in the prompt:** `Progression.to_prompt` renders a `STATUS` block (HP, level, XP to next level, slots remaining, inventory, features) appended to the system prompt each turn like the character sheet; the `PROGRESSION` rules section makes it the single source of truth and tells the model to charge HP for failed dangerous checks and award 10–50 XP per overcome challenge.
- **Level-ups:** flat XP curve (`XP_PER_LEVEL` = 100 per level, capped at `MAX_LEVEL` = 10). Crossing a threshold triggers an interactive prompt per level (`prompt_level_up`): +`HP_PER_LEVEL` max HP, full heal, slots restored, plus a class-feature choice — +1 to a stat (capped at `STAT_MAX`), a named free-text feature, or a new spell slot of any level. Starting max HP is `STARTING_HP_BASE` + Constitution; starting level-1 slots are asked once at new-game time (`prompt_starting_spell_slots`).
- **Death and resurrection:** HP 0 ends the turn in a death menu (`prompt_death`): resurrect at half max HP for `RESURRECTION_XP_PENALTY` XP (floored so no level is lost) — a revival note is injected into the story so the GM narrates from it — or end the story, which goes through the normal save/export flow.

**Future work this keeps open:** Phase 2.4's status bar reads `Progression` fields directly; Phase 3 training data must include the STATE line in assistant turns so the fine-tuned model keeps emitting it; further progression state (conditions, currency) should be new `Progression` fields plus new STATE-line entry kinds, with another `SAVE_VERSION` bump.

### 2.4 Terminal UI — IMPLEMENTED

Every print/input in the game now goes through `ui.py`, a presentation layer built on `rich` (already pinned in `requirements.txt`):

- **Status bar:** a panel rendered directly above each turn's input line showing character name, HP (colour-coded green/yellow/red by thirds of max, `ui.hp_style`), level, XP and cumulative token count — read straight off the `Progression`/`Character` dataclasses as planned (`ui.status_bar`, called from `context.py:context_update`)
- **Distinct formatting:** GM speech streams under a `GM` rule separator; system/instruction messages are dim; game events (level-up, death, resurrection) are bold magenta; warnings yellow; errors bold red; input prompts green. One style constant per output kind at the top of `ui.py`. Game text is always printed with `markup=False`/`Text()` so model output containing brackets is never parsed as rich markup
- **Colour-coded D20s:** the turn's 5 pre-rolled values are shown once the action is submitted, coloured by consequence tier (1-5 red, 6-10 yellow, 11-15 cyan, 16-20 green, naturals emphasised — `ui.roll_style`, matching the rules prompt's scaling). The whole turn pool is displayed rather than per-roll consumption, because consumption only exists in the model's narration and is not machine-tracked. `rolls.py` was split into `roll_values()` + `rolls_message(values)` so the UI and the prompt share the same values; `rolls()` is the unchanged composition of the two

**Divergence from the original plan:** `rich` was chosen over `textual`, so the layout scrolls rather than being a true split-pane with a pinned input widget — the status bar + prompt re-rendered at the bottom each turn approximate it. A real split-pane would mean rewriting the synchronous `input()`/`KeyboardInterrupt` control flow (the Ctrl+C save path, the mid-turn level-up/death menus) into an async TUI. The path stays open: game logic never touches `print`/`input` directly, so a later `textual` upgrade only has to reimplement `ui.py`'s functions.

---

## Phase 3 — Model Fine-Tuning

`mistral:instruct` is a general-purpose assistant. Fine-tuning on RPG GM dialogue would improve staying in character, appropriate dice usage, narrative pacing, and rules adherence.

### 3.1 Training Data

| Dataset | License | Notes |
|---|---|---|
| **D&D SRD 5.1** | CC BY 4.0 (Wizards of the Coast) | Rules, spells, monsters — clean to train on; SRD content only, not published adventures or non-SRD lore |
| **LIGHT (Facebook Research)** | MIT — `parl.ai/projects/light/` | 663 locations, 1755 character types, 11k+ interaction episodes in a fantasy world; highest-quality source for this use case |
| **Writing Prompts** (`euclaise/writingprompts`, HuggingFace) | Mixed CC / public domain mirrors | Narrative prompt–continuation pairs; useful for story generation style; verify individual post licences before commercial use |
| **DnD NLP dataset** (`grantprice/DND-NLP`, HuggingFace) | Verify dataset card before use | D&D-specific text data; licence unclear at time of writing — check before including |
| **Hand-curated examples** | Own work | 200–500 manually written GM interactions; highest signal-to-noise ratio |

**What to avoid:** published WotC adventure modules, Forgotten Realms lore, Reddit scrapes without explicit CC licensing (legally gray for commercial use).

**Training format:** all examples must use Mistral's instruction-tuning chat template, with the system prompt matching the one used in production (`main.py:7`) exactly:

```json
{
  "messages": [
    {"role": "system", "content": "<rules prompt from main.py>"},
    {"role": "user",  "content": "I attempt to pick the lock."},
    {"role": "assistant", "content": "[GM narrative response using a pre-rolled D20]"}
  ]
}
```

### 3.2 Fine-Tuning Method

Full fine-tuning a 7B model requires ~80 GB VRAM. The practical approach is **QLoRA** (4-bit quantisation + low-rank adapter):

- Tool: **Unsloth** (`unslothai/unsloth`, Apache 2.0) — fastest QLoRA implementation with native Mistral support
- Base model: `mistralai/Mistral-7B-Instruct-v0.3` (Apache 2.0, HuggingFace)
- Key hyperparameters: `lora_r=16`, `lora_alpha=32`, `load_in_4bit=True`, `max_seq_length=2048`, `learning_rate=2e-4`

### 3.3 Hardware Plan

**Free cloud — prototype phase:**

- **Kaggle Notebooks** — 30 free GPU hours/week, NVIDIA T4 (16 GB VRAM). Sessions do not disconnect mid-run. Use to validate the data pipeline and confirm loss decreases before committing to paid compute.
- **Google Colab free tier** — T4 (16 GB) but sessions disconnect during long runs; unreliable for full training.

**Paid cloud — full training run:**

| Platform | GPU | VRAM | $/hr | Est. hours | Est. cost |
|---|---|---|---|---|---|
| Vast.ai | RTX 4090 | 24 GB | ~$0.35–0.55 | 8–12 | ~$4–7 |
| Runpod | RTX 4090 | 24 GB | ~$0.50–0.74 | 8–12 | ~$5–9 |
| Lambda Labs | A100 80 GB | 80 GB | ~$1.29 | 4–6 | ~$5–8 |

Validate using Free options, then run the full job on paid cloud.

### 3.4 Export Back to Ollama

After training, merge the LoRA adapter into the base weights and convert to GGUF for Ollama:

```bash
# Merge LoRA adapter into base model
python merge_lora.py --base mistralai/Mistral-7B-Instruct-v0.3 --adapter ./output

# Convert to GGUF via llama.cpp
python llama.cpp/convert_hf_to_gguf.py ./merged_model --outfile dnd-mistral.gguf

# Quantise to Q4_K_M (best quality/size balance)
llama.cpp/quantize dnd-mistral.gguf dnd-mistral-q4km.gguf Q4_K_M

# Register with Ollama
ollama create dnd-mistral -f Modelfile
```

Then update `MODEL_NAME` in `model.py` to point to the new model.

### 3.5 Evaluation

Before deploying, compare against the base `mistral:instruct` on:

- **Rule accuracy:** 20 SRD rules questions, scored correct/incorrect
- **Narrative quality:** human eval on 10 open scenarios — does it stay in-world, consume pre-rolled dice in order, and advance the story?
- **Format compliance:** does it respect the plain-text output rules from the system prompt?

### 3.6 Licensing Notes for Distribution

If the fine-tuned model weights are distributed publicly, attribution is required for each component:

- **Apache 2.0 (Mistral base):** include a `NOTICE` file crediting Mistral AI
- **MIT (LIGHT dataset):** include the MIT copyright notice
- **CC BY 4.0 (SRD):** attribute Wizards of the Coast

The project's existing Apache 2.0 licence covers the code. Apache 2.0 and MIT are fully compatible; CC BY 4.0 carries no ShareAlike obligation, so it does not constrain the model licence.