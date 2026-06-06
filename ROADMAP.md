# Oneshot – Development Roadmap

Planned improvements in rough priority order.

---

## Phase 1 — Core LLM Quality

### 1.1 Revise the Rules System Prompt

The current rules message (`main.py:7-36`) needs the following changes:

- Expand the GM persona definition to specify tone (second-person, present tense, grounded), pacing (when to end a turn on a cliffhanger vs. resolve fully), and the threshold for calling a roll (chance-based actions only, not pure narrative beats)
- Rewrite the dice system rules to be unambiguous: the model receives exactly 5 pre-rolled D20s appended to the system message, must consume them left-to-right, one per roll, and must not invent or paraphrase numbers
- Add a consequence-scaling rule: a roll of 1–5 is a critical failure with a setback, 6–10 is a partial failure, 11–15 is a partial success, 16–20 is a full success, and a natural 20 has a narrative bonus
- Split the prompt into three labelled sections — `PERSONA`, `DICE SYSTEM`, `OUTPUT FORMAT` — so individual rules can be edited and tested in isolation

### 1.2 Improve Hierarchical Summary Initialisation and Update Logic

The summary is currently initialised as a hardcoded string at `main.py:49`, tightly coupled to the fixed opening scene (`startMessage`). Both will need to become dynamic once character creation is introduced (Phase 2), but improvements to the update logic are also needed:

- **Update prompt:** add explicit section anchors to the candidate-generation prompt so the model is required to output all three sections (`OVERALL STORY`, `CURRENT QUEST`, `PLAYER STATUS`) in every candidate; candidates missing a section are discarded before scoring
- **Selective updates:** classify each turn's exchange as affecting story / quest / status or none (keyword match on quest-resolution and status-change phrases is sufficient); only regenerate the affected section(s) and carry the rest forward unchanged to save tokens and prevent drift in stable sections
- **Dynamic initialisation (Phase 2 dependency):** once character creation exists, generate the opening `startMessage` and `summary` from the character sheet via a dedicated model call, replacing the hardcoded values at `main.py:38-42` and `main.py:49`

### 1.3 Better Summary Candidate Selection

Current scoring: cosine similarity (0.5) + ROUGE-1/2/L (0.2 each) against the old summary + last interactions.

Weaknesses: ROUGE measures n-gram overlap and misses paraphrase; spaCy cosine similarity is shallow. Both can favour a candidate that copies the reference wording without genuinely capturing what happened.

Replacement scoring:

Replace the current scorer with **BERTScore** (`bert-score` on PyPI, MIT, runs on CPU in ~50–100 ms using `microsoft/deberta-xlarge-mnli` as the base model). Score each candidate against the reference (old summary + last two exchanges) and select the highest F1.

Composite formula: `0.6 × BERTScore-F1 + 0.2 × ROUGE-L + 0.2 × cosine` — keeps the existing lexical signals but weights semantic quality higher.

Evaluation before switching: hold out 20 consecutive session turns, run both the current scorer and the new scorer on the same candidates, and compare chosen candidates against a hand-ranked ground truth. Merge only if the new scorer wins on 14/20 turns.

---

## Phase 2 — User Interface and Character System

### 2.1 Character Creation

Replace the hardcoded opening scene with a structured character creation flow at startup:

- Name, race, class, background (drawn from SRD 5.1 options)
- Starting ability scores (point-buy or standard array)
- Brief backstory prompt used to dynamically generate both `startMessage` and the initial `summary` via a model call, replacing the hardcoded values in `main.py:38-42/49`
- Character sheet stored as a dataclass and serialised alongside session state

### 2.2 Story Saving and Loading

Extend the existing session persistence (`main.py:58–122`):

- Named save slots rather than only numbered session directories
- Load a named previous session at startup alongside the existing `backup.pkl` resume flow
- Export session transcript as formatted plain text or Markdown

### 2.3 Character Stats and Progression

- Track HP, spell slots, inventory, and XP between turns
- Surface relevant stats in the system prompt each turn so the model can reference them accurately (e.g. "The player currently has 8 HP and 2 first-level spell slots remaining")
- Level-up prompts at XP thresholds with class feature choices
- Death and resurrection mechanics tied to HP

### 2.4 Terminal UI

Current interface is plain `print`/`input`, change to `rich` or `textual`:

- Split-pane layout: GM narrative scrolling above, input line pinned below
- Persistent status bar showing character name, HP, level, and cumulative token count
- Distinct formatting for GM speech, roll results, and system messages
- Colour-coded display of D20 values when consumed each turn

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