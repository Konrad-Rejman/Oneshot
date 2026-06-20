# Oneshot – Development Roadmap

Planned work in rough priority order. Once an item ships, the *what* lives in the
code and CLAUDE.md; entries here keep only the status, the pending work, and the
non-obvious reasons the implementation diverged from the original plan.

---

## Phase 1 — Core LLM Quality

### 1.1 Revise the Rules System Prompt — DONE

`gm_rules.py:rules` (importable, so the training pipeline shares one copy):
labelled `PERSONA` / `DICE SYSTEM` / `OUTPUT FORMAT` / `CHARACTER` sections,
5 pre-rolled D20s consumed left-to-right, consequence scaling by roll band, and
stat-based tier shifts. Tests don't assert the wording, so it can be iterated —
but Phase 3 fine-tuning must keep the production prompt in sync with the data.

### 1.2 Hierarchical Summary Update Logic — DONE (dynamic initialisation pending)

Selective per-section updates (`context.py`): each exchange is keyword-classified
as touching story / quest / status; only those sections are regenerated and
merged, with markdown-tolerant parsing and a staleness guard that forces a full
refresh after `SUMMARY_UPDATE_INTERVAL` quiet turns. An unstructured summary
(e.g. a hand-written scenario) falls back to whole-summary regeneration.

**Pending — dynamic initialisation:** the scenario picker
(`scenarios.py:choose_scenario`) replaced the hardcoded opening, but the planned
model call that *generates* an opening scene + summary from the character sheet
doesn't exist yet. When added, feed it through `add_scenario()` so generated
openings are saved like hand-written ones.

### 1.3 Summary Candidate Selection — DONE (evaluation pending)

BERTScore composite `0.6 × BERTScore-F1 + 0.2 × ROUGE-L + 0.2 × cosine`
(`scoring.py`), scored against the old affected sections + last two exchanges;
falls back to the lexical signals if BERTScore fails at runtime. Base model
`roberta-large`, loaded lazily, CUDA when available.

**Pending — evaluation:** the scorer was swapped in without the planned
acceptance gate (run old vs. new on 20 held-out turns, require the new scorer to
win ≥14 against a hand-ranked ground truth). Needs per-turn candidate logging,
which doesn't exist yet.

---

## Phase 2 — User Interface and Character System

### 2.1 Character Creation — DONE

Startup flow builds a `Character` dataclass (name/race/class/background + six
ability scores from a shared point pool), serialised with session state. The
backstory-driven model generation of the opening scene/summary is the dynamic
initialisation still pending under 1.2.

### 2.2 Story Saving and Loading — DONE

Named save slots (`saves.py`): one JSON file per slot in `saves/` holding the
same state keys as `backup.pkl` plus `Version`/`Name`. Startup menu lists them
newest-first to continue / export / delete; `backup.pkl` crash-resume takes
priority and both restore through `main.py:session_from_state`. Transcript export
to `exports/` as plain text or Markdown.

### 2.3 Character Stats and Progression — DONE

All progression state in `progression.py:Progression` (HP/max HP, level, XP,
inventory, features). The GM reports mechanical changes in an end-of-reply
`STATE:` line; `parse_state_changes` strips it before storage and
`apply_state_changes` applies it with clamping (HP `[0, max]`, XP floored at the
current level so the model can't de-level, invalid entries ignored). Flat XP
curve with interactive level-ups; HP 0 opens a resurrect-or-end death menu.

**Spell slots — deferred:** per-level slot tracking was removed to focus on
stat-driven checks and HP/XP/inventory first. The STATE-line grammar and
`Progression` are designed to take a new entry kind back when casting returns.

**Keeps open:** further progression state (conditions, currency, spell slots)
should be new `Progression` fields + new STATE-line entry kinds, with a
`SAVE_VERSION` bump.

### 2.4 Terminal UI — DONE

`ui.py` (`rich`) is the single presentation layer: status-bar panel, GM speech
under a `GM` rule, colour-coded D20 pool by consequence tier, distinct styles
per message kind, all game text printed with `markup=False` so model brackets
aren't parsed.

**Divergence:** `rich` over `textual`, so the layout scrolls rather than being a
true pinned-input split-pane. The path to `textual` stays open because game
logic never touches `print`/`input` directly — only `ui.py` would change.

### 2.5 User Accounts and Main Menu — DONE

The free-text username prompt became an account screen (`main.py:account_screen`):
log in or create an account, password entered masked (`ui.ask_secret`) and stored
only as an sha512 hash in `accounts.json` (`accounts.py`). The seeded `u00`/`admin`
account owns the pre-account data. The username is still the owner tag, so the
`ownership.py` rules and `migrate_*` claims are unchanged. After login an
arrow-navigated main menu (New game · Continue · Characters · Scenarios · Settings
· Exit) loops back after each session — a session ends by raising
`context.SessionEnd` (caught by `run_game`) instead of `quit()`ing the process.

**Default model now persistent:** the per-session `choose_model()` prompt became a
per-account default (`accounts.default_model`), asked once on first login and
changeable in Settings; `model.apply_default_model` falls back to base when a
stored fine-tuned default is no longer installed.

---

## Phase 3 — Model Fine-Tuning

`mistral:instruct` is a general assistant; fine-tuning on GM dialogue improves
staying in character, dice usage, pacing, and rules adherence.

### 3.1 Training Data — DONE (synthetic-only pipeline)

`training/generate_dataset.py` builds a fully synthetic, self-distilled dataset:
the local base model writes the prose from each structural spec while the dice,
stat check and STATE line are computed in code (`training/outcomes.py`);
`training/validators.py` gates every stage.

**Divergence — why synthetic-only:** the project is public and may be
commercialised, so every source would need an express commercial licence (the UK
TDM exception, s29A CDPA, is non-commercial-only). A single-source dataset (the
base model's own Apache-2.0 output) needs no attribution chain and matches the
game's house rules better than SRD text. Claude-authored examples are excluded
(Anthropic ToS). Full rationale: `training/COMPLIANCE.md` (binding).

**Divergence — format:** production sends one flattened prompt to
`/api/generate`, so each example stores that exact flattened prompt + the
validated GM response. Changing the rules prompt or a `to_prompt` means
regenerating the dataset.

### 3.2 Fine-Tuning Method — DONE (run on Kaggle free tier)

QLoRA via Unsloth, base `unsloth/mistral-7b-instruct-v0.3-bnb-4bit` (Apache 2.0),
`lora_r=16` / `lora_alpha=32` / 4-bit / `max_seq_length=2048` /
`learning_rate=2e-4`, loss masked to response tokens, Q4_K_M GGUF exported
directly — packaged as `training/train_qlora.py` for a free Kaggle T4 (the dev
machine's 6 GB GPU can't train a 7B). Paid-platform guide in `training/private/`
(gitignored).

**Model toggle (pulled forward from 3.4):** the fine-tune registers as
`Konrad-Rejman/gm-istral-v01` alongside the untouched base model;
`model.choose_default_model()` offers the toggle only when it's installed
(default: base, persisted per account — see 2.5) and the status bar names the
active model.

### 3.3 Hardware Plan

The standard run (~300 examples, QLoRA 7B) fits Kaggle's free tier (30 GPU
hrs/week, T4 16 GB, no mid-run disconnects), so paid compute is optional. Colab
free is unreliable for long runs. Paid options if needed:

| Platform | GPU | VRAM | $/hr | Est. hours | Est. cost |
|---|---|---|---|---|---|
| Vast.ai | RTX 4090 | 24 GB | ~$0.35–0.55 | 8–12 | ~$4–7 |
| Runpod | RTX 4090 | 24 GB | ~$0.50–0.74 | 8–12 | ~$5–9 |
| Lambda Labs | A100 80 GB | 80 GB | ~$1.29 | 4–6 | ~$5–8 |

Step-by-step paid guide: `training/private/PAID_FINETUNING_GUIDE.md` (gitignored).

### 3.4 Export Back to Ollama — DONE

Unsloth exports a merged Q4_K_M GGUF directly, replacing the separate
merge/convert/quantise steps. Register with
`ollama create Konrad-Rejman/gm-istral-v01 -f training/Modelfile`. `MODEL_NAME`
is **not** repointed — the base stays the default and the per-account default
model (2.5) selects between them.

### 3.5 Evaluation — pending

Before deploying, compare against base `mistral:instruct` on rule accuracy
(20 SRD questions), narrative quality (human eval on 10 scenarios — in-world,
dice consumed in order, story advanced), and format compliance.

### 3.6 Licensing for Distribution

Fine-tuned weights are published to the Ollama registry
(`Konrad-Rejman/gm-istral-v01`) under Apache 2.0. With the synthetic-only
dataset the attribution chain is one entry — the `NOTICE` crediting Mistral AI,
embedded via the `LICENSE` block in `training/Modelfile`. The project's own
Apache 2.0 licence covers the code. Full UK-law rationale: `training/COMPLIANCE.md`.
