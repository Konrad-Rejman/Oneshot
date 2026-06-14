# Phase 3 — GM Model Fine-Tuning Pipeline

Fine-tunes the game's GM model (`mistral:instruct`) on filtered examples of
its own best behaviour, targeting the failure modes the base model actually
shows in play: inventing dice values instead of consuming the pre-rolled
pool, calling a check on the wrong (or a non-existent) stat, drifting out of
the plain-text format, and mangling or dropping the machine-read STATE line.

The original model is untouched. The fine-tuned model registers under its
own Ollama name (`gm-istral`); when installed, the game offers a
base/fine-tuned toggle at startup (`model.py:choose_model`) and shows the
active model in the status bar, so the two can be compared side by side.

See `COMPLIANCE.md` for the UK copyright/data-law rationale behind the
dataset design (short version: every sentence is generated locally by the
base model itself; nothing third-party is copied).

## How it works

`generate_dataset.py` builds each example from a structural spec (`specs.py`
— terse parameters like location `sewer`, action `pick the lock`, the turn's
roll pool, a sampled character sheet and progression state). The base model
writes the prose; the **turn mechanics are computed by code**, not the model:

1. a three-section story summary (model),
2. an opening scene (model),
3. a first-person player action (model),
4. the GM turn, assembled from
   - a check announcement built deterministically (`outcomes.py`) — the
     spec's relevant stat and `pool[0]`, e.g. `Roll a Dexterity check... you
     roll a 14.`;
   - the GM **narration** (model), answering the **exact production prompt**
     (`gm_rules.RULES_TEXT` + character sheet + STATUS block + rolls message,
     flattened by `model._build_prompt_from_memory`) but told only the
     plain-language outcome to narrate — never the numbers;
   - the canonical STATE line, computed from the consequence tier
     (`outcomes.py`, with the CHARACTER stat shift applied): success awards
     XP, a failed physical check costs HP, and a critical failure also loses
     an item.

   No-check actions (conversation, looking around) skip the announcement and
   end with `STATE: none`.

**Why the split.** The earlier all-model-authored GM response failed exactly
where it mattered: the base model named the wrong stat (or a non-stat skill
like "Perception") about half the time and emitted `STATE: none` on every
turn — behaviours no amount of best-of-N filtering can surface, because the
model almost never produces them. Computing the stat, dice and STATE line in
code guarantees every example demonstrates them, while the model still
writes all the prose (its actual strength).

Every model stage is gated by `validators.py` (tested in the main suite):
strict canonical STATE-line grammar, dice announced only from the pool and
in order, no markdown, no character breaks, second-person narration, and
`validate_narration` forbidding any dice/mechanics talk in the prose body.
The assembled response must still pass the full production gate
(`validate_gm_response`); specs whose stages all fail validation are skipped.

## Usage

```bash
# 1. Generate data (Ollama running; ~1-2 min/example on a laptop GPU).
#    Resumable - rerun to grow the dataset. Target 300+ for a real run.
python -m training.generate_dataset --n 300

# 2. Train on Kaggle's free T4 (30 GPU-hours/week) - see the step-by-step
#    header of train_qlora.py. Output: gm-istral.Q4_K_M.gguf

# 3. Register with Ollama (next to the downloaded GGUF):
ollama create gm-istral -f training/Modelfile

# 4. Play. The startup menu now offers base vs fine-tuned.
python main.py
```

`training/data/` (the dataset) and `training/private/` are gitignored: the
public repository carries the pipeline, not the outputs.

## Evaluation (ROADMAP 3.5, manual for now)

Play the same scenario seeds against both models via the startup toggle and
compare: dice fidelity (announced rolls vs the pool shown in the UI),
STATE-line correctness (watch for warnings/mis-tracked HP), format slips,
and narrative pacing. The status bar names the active model, and session
transcripts land in `sessions/`, so runs are attributable after the fact.

## Keeping things in sync

The training prompt embeds `gm_rules.RULES_TEXT` by import — if the rules
prompt changes, **regenerate the dataset and retrain**, otherwise the
fine-tune reinforces a stale prompt format. Same applies to
`Character.to_prompt` / `Progression.to_prompt` / `rolls_message` changes.
