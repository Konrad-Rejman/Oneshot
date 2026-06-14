# gm-istral-v01

A fine-tuned **Game Master** for a D&D-style, single-session terminal RPG. It
narrates a scene, calls for stat checks, resolves them with pre-rolled dice, and
keeps mechanical bookkeeping in a machine-readable line at the end of each turn.

QLoRA fine-tune of **mistral-7b-instruct-v0.3**, quantised to Q4_K_M.

## What it's trained to do

Plain `mistral:instruct` makes four recurring mistakes as a GM: it invents dice
values instead of using the ones provided, calls checks on the wrong (or a
non-existent) stat, drifts out of the plain-text format, and mangles or omits
the state-tracking line. `gm-istral-v01` is trained to fix exactly those:

- **Use the supplied dice** - consume the pre-rolled D20 values given in the
  prompt instead of hallucinating numbers.
- **Name the right stat** - pick the relevant stat for the action and announce
  the check (`Roll a Strength check... you roll a 14.`).
- **Resolve chance by the roll** - map the result to a consequence tier
  (1-5 critical failure, 6-10 partial failure, 11-15 partial success,
  16-20 full success) and narrate that outcome, weighing the character's stats,
  history, and the current scene.
- **Emit a state line** - end every reply with a machine-read line such as
  `STATE: HP -3; XP +25; GAIN torch; LOSE rope`, or `STATE: none`.

## Important: it expects a specific prompt structure

This is **not a general-purpose chat model.** It was trained on a fixed prompt
layout - a rules system prompt, a character sheet (six stats rated 1-10), a
status block (HP / level / XP / inventory), five pre-rolled D20 values, a running
summary, recent history, then the player's action. Run cold without that
scaffolding it will still respond, but you won't get correct GM behaviour. It's
designed to be driven by the host game, which assembles that prompt every turn.

The full pipeline, rules prompt, and host game are here:
**https://github.com/Konrad-Rejman/Oneshot**

## Usage

```bash
ollama pull Konrad-Rejman/gm-istral-v01
```

Intended to be called by the Oneshot game (which builds the structured prompt and
shows a base/fine-tuned toggle at startup). The Mistral `[INST] ... [/INST]`
template and `[INST]`/`[/INST]` stop tokens are baked into the model.

## Training data

Fully synthetic and self-distilled: every line of prose was generated locally by
mistral-7b-instruct-v0.3 itself, with the turn mechanics (stat, roll, tier, state
line) computed deterministically in code. No third-party datasets, scraped text,
or published adventure modules are included.

## License

Apache License 2.0 - the same licence as the Mistral base.

This model is a derivative of **Mistral-7B-Instruct-v0.3**, Copyright Mistral AI,
licensed under Apache 2.0 (https://www.apache.org/licenses/LICENSE-2.0). The
NOTICE crediting Mistral AI ships embedded in the model (Apache 2.0 section 4(d)).
A copy of the full Apache 2.0 license text is available at the link above and in
the project repository.
