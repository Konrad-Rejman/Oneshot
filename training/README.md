# Phase 3 — GM Model Fine-Tuning Pipeline

Fine-tunes the game's GM model (`mistral:instruct`) on filtered examples of
its own best behaviour, targeting the failure modes the base model actually
shows in play: inventing dice values instead of consuming the pre-rolled
pool, drifting out of the plain-text format, and mangling or dropping the
machine-read STATE line.

The original model is untouched. The fine-tuned model registers under its
own Ollama name (`oneshot-gm`); when installed, the game offers a
base/fine-tuned toggle at startup (`model.py:choose_model`) and shows the
active model in the status bar, so the two can be compared side by side.

See `COMPLIANCE.md` for the UK copyright/data-law rationale behind the
dataset design (short version: every sentence is generated locally by the
base model itself; nothing third-party is copied).

## How it works

`generate_dataset.py` builds each example in four model stages, all written
by the local base model from a structural spec (`specs.py` — terse
parameters like location `sewer`, action `pick the lock`, the turn's roll
pool, a sampled character sheet and progression state):

1. a three-section story summary,
2. an opening scene,
3. a first-person player action,
4. the GM response — generated from the **exact production prompt** (the
   same `gm_rules.RULES_TEXT` + character sheet + STATUS block + rolls
   message, flattened by `model._build_prompt_from_memory`), sampled at
   several temperatures.

Every stage is gated by `validators.py` (tested in the main suite): strict
canonical STATE-line grammar, dice announced only from the pool and in
order, no markdown, no character breaks, second-person narration. The first
GM candidate to pass all checks is kept; specs whose candidates all fail
are skipped. The fine-tune then amortises this filtering — the model learns
to produce first-try what the pipeline accepts.

## Usage

```bash
# 1. Generate data (Ollama running; ~1-2 min/example on a laptop GPU).
#    Resumable - rerun to grow the dataset. Target 300+ for a real run.
python -m training.generate_dataset --n 300

# 2. Train on Kaggle's free T4 (30 GPU-hours/week) - see the step-by-step
#    header of train_qlora.py. Output: oneshot-gm.Q4_K_M.gguf

# 3. Register with Ollama (next to the downloaded GGUF):
ollama create oneshot-gm -f training/Modelfile

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
