'''
Synthetic training-data generator for Phase 3 (ROADMAP 3.1).

Every example is one full game turn in the exact shape the model sees in
production: the prompt is assembled with the same code the game uses
(gm_rules.RULES_TEXT + Character.to_prompt + Progression.to_prompt +
rolls_message, flattened by model._build_prompt_from_memory), so the
training and inference formats cannot drift.

All prose is written by the local base model itself (self-distillation;
see training/COMPLIANCE.md for why): from a structural spec (specs.py) the
model writes a three-section summary, an opening scene, a player action and
the GM narration. The turn's mechanics are not left to the model - the check
announcement, the consequence tier (with the CHARACTER stat shift) and the
canonical STATE line are computed deterministically from the spec in
outcomes.py, and the model is asked only to narrate the given outcome. This
guarantees every example demonstrates the right stat, the correct dice and a
populated, valid STATE line, which the base model rarely produced on its
own. Each stage is retried at a higher temperature until it passes its
validator (validators.py); the assembled response must still pass the full
production gate.

Usage (Ollama running, from the repo root):

    python -m training.generate_dataset --n 300

Appends to training/data/dataset.jsonl (gitignored) and is resumable: rerun
to grow the dataset. One JSONL record per example: {"id", "prompt",
"response", "meta"}; train_qlora.py consumes the prompt/response pair.
'''
import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from gm_rules import RULES_TEXT  # noqa: E402
from model import _build_prompt_from_memory, OLLAMA_API, BASE_MODEL_NAME  # noqa: E402
from rolls import rolls_message  # noqa: E402
from training import outcomes, specs, validators  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent / 'data' / 'dataset.jsonl'

# Temperatures tried per GM candidate, in order; variety without drifting
# into incoherence. Auxiliary stages (summary/scene/action) start at the
# first value and step up on each retry.
CANDIDATE_TEMPERATURES = [0.7, 0.8, 0.9, 1.0]


def call_ollama(prompt, model, temperature, num_predict, timeout):
    payload = {
        'model': model,
        'prompt': prompt,
        'stream': False,
        'options': {'temperature': temperature, 'num_predict': num_predict},
    }
    resp = requests.post(OLLAMA_API, json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f'Ollama returned {resp.status_code}: {resp.text[:200]}')
    return resp.json().get('response', '').strip()


# --- stage prompts -------------------------------------------------------
# These instructions never enter the dataset - only the model's answers do.
# Spec values are slotted in after a colon rather than inline so missing
# articles ("a old library") never reach the generated prose.

def summary_prompt(spec):
    p = spec['progression']
    c = spec['character']
    items = ', '.join(p.inventory) if p.inventory else 'nothing'
    return (
        'Write a story summary for a fantasy RPG session in exactly this format, '
        'plain text, no markdown, each section one or two short sentences:\n'
        'OVERALL STORY: ...\nCURRENT QUEST: ...\nPLAYER STATUS: ...\n\n'
        f'Base it on these facts. The hero is this kind of character: {c.race} {c.char_class}. '
        f'Their goal concerns: {spec["goal"]}. They are in this location: {spec["location"]}, '
        f'dealing with this threat: {spec["threat"]}. '
        f'They have {p.hp} of {p.max_hp} HP and carry: {items}.'
    )


def scene_prompt(spec):
    return (
        'You are the Game Master of a fantasy pen-and-paper RPG. Write the opening '
        'narration of one scene. Address the player in second person, present tense. '
        'Three to five sentences of plain text, no markdown, no special characters. '
        'Do not mention dice or numbers, do not resolve anything, and end on the '
        'situation confronting the player.\n'
        f'The scene is set in this location: {spec["location"]}. '
        f'The player faces this threat: {spec["threat"]}. '
        f'Their wider goal concerns: {spec["goal"]}.'
    )


def action_prompt(spec, scene):
    return (
        'You are a player in a fantasy pen-and-paper RPG. The Game Master just narrated:\n\n'
        f'{scene}\n\n'
        'Write your character\'s next action as one or two short sentences in first '
        'person, starting with I. Plain text only, no markdown, no quotation marks, '
        'and do not mention dice or numbers. '
        f'Make the action clearly an attempt to {spec["action_kind"]}; do not '
        'substitute a different approach.'
    )


def narration_prompt(spec, scene, action, tier, changes):
    '''
    Asks the model for the prose body of a check turn only. The mechanical
    outcome (which tier, what was lost/gained) is decided in outcomes.py and
    handed in as plain language, so the model writes prose around a fixed
    result instead of inventing one - and the announce/STATE lines are added
    by the pipeline, never the model.
    '''
    return (
        'You are the Game Master of a fantasy pen-and-paper RPG, narrating the result '
        'of the player\'s action in second person, present tense.\n\n'
        f'The scene so far: {scene}\n\n'
        f'The player attempts: {action}\n\n'
        f'They are trying to {spec["action_kind"]}; narrate the result of that specific '
        'attempt, not a different action.\n\n'
        f'What happens: {outcomes.outcome_hint(tier, changes)}\n\n'
        'Write two to four sentences of plain prose narrating only this outcome and the '
        'situation the player now faces. Make the prose match the outcome exactly: if it '
        'is a success, the attempt visibly lands and the player is better off; if it is a '
        'failure, the attempt clearly fails and it costs them. Vary your sentence '
        'openings and do not begin with "As you". No markdown or special characters. Do '
        'not mention dice, rolls, numbers, checks, stats, hit points or experience, and '
        'do not name any game mechanic. Do not write a STATE line or any label, and do '
        'not decide what the player does next.'
    )


def flavour_prompt(spec, scene, action):
    '''Prose body of a no-check turn: conversation or description, nothing resolved by chance.'''
    return (
        'You are the Game Master of a fantasy pen-and-paper RPG, narrating in second '
        'person, present tense.\n\n'
        f'The scene so far: {scene}\n\n'
        f'The player does this: {action}\n\n'
        'This action has no uncertain outcome - it is conversation or looking around, '
        'not a risky attempt. Write two to four sentences of plain prose describing what '
        'the player sees, hears or is told, and the situation they now face. Vary your '
        'sentence openings and do not begin with "As you". No markdown or special '
        'characters. Do not mention dice, rolls or any game mechanic, do not write a '
        'STATE line, and do not decide what the player does next.'
    )


def build_gm_memory(spec, summary, scene, action):
    '''
    The production turn-1 memory layout (context.py:context_update):
    [rules + sheet + STATUS + rolls, summary, opening scene, action].
    '''
    rules_content = (
        RULES_TEXT
        + '\n\n' + spec['character'].to_prompt()
        + '\n\n' + spec['progression'].to_prompt()
        + rolls_message(spec['rolls'])
    )
    return [
        {'role': 'system', 'content': rules_content},
        {'role': 'user', 'content': summary},
        {'role': 'assistant', 'content': scene},
        {'role': 'user', 'content': action},
    ]


# --- generation ----------------------------------------------------------

def generate_stage(prompt, validate, model, num_predict, timeout, attempts, rejections):
    '''
    Generate one auxiliary stage (summary/scene/action), retrying with a
    higher temperature on validation failure. Returns text or None.
    '''
    for attempt in range(attempts):
        temperature = CANDIDATE_TEMPERATURES[min(attempt, len(CANDIDATE_TEMPERATURES) - 1)]
        text = call_ollama(prompt, model, temperature, num_predict, timeout)
        reasons = validate(text)
        if not reasons:
            return text
        rejections.update(reasons)
    return None


def generate_example(spec, model, timeout, attempts, rejections):
    '''
    Run all stages for one spec (summary, scene, action, then the GM prose
    body wrapped in deterministic mechanics). Returns a dataset record dict
    or None when any stage fails validation on every attempt.
    '''
    summary = generate_stage(summary_prompt(spec), validators.validate_summary,
                             model, 300, timeout, attempts, rejections)
    if summary is None:
        return None
    scene = generate_stage(scene_prompt(spec), validators.validate_scene,
                           model, 400, timeout, attempts, rejections)
    if scene is None:
        return None
    action = generate_stage(action_prompt(spec, scene), validators.validate_action,
                            model, 120, timeout, attempts, rejections)
    if action is None:
        return None

    # The mechanics (check announcement, consequence tier, STATE line) are
    # built deterministically from the spec; the model writes only the prose
    # body so it cannot misname the stat, miscount the dice or drop the STATE
    # line - the failures that dominated the all-model-authored data.
    roll = spec['rolls'][0]
    if spec['requires_check']:
        stat = spec['stat']
        stat_value = spec['character'].stats[stat]
        tier, changes = outcomes.consequences(
            roll, stat, stat_value, spec['progression'].inventory)
        narration = generate_stage(
            narration_prompt(spec, scene, action, tier, changes),
            validators.validate_narration, model, 400, timeout, attempts, rejections)
        if narration is None:
            return None
        state = outcomes.state_line(changes)
        response = (outcomes.announce_line(stat, roll)
                    + '\n\n' + narration + '\n\n' + state)
    else:
        tier, changes, state = None, {}, 'STATE: none'
        narration = generate_stage(
            flavour_prompt(spec, scene, action),
            validators.validate_narration, model, 400, timeout, attempts, rejections)
        if narration is None:
            return None
        response = narration + '\n\n' + state

    # Safety net: the assembled response must still pass the production gate.
    reasons = validators.validate_gm_response(response, spec['rolls'],
                                              require_check=spec['requires_check'])
    if reasons:
        rejections.update(reasons)
        return None

    prompt_text = _build_prompt_from_memory(build_gm_memory(spec, summary, scene, action))
    return {
        'prompt': prompt_text,
        'response': response,
        'meta': {
            'location': spec['location'],
            'threat': spec['threat'],
            'goal': spec['goal'],
            'action_kind': spec['action_kind'],
            'stat': spec['stat'],
            'requires_check': spec['requires_check'],
            'rolls': spec['rolls'],
            'tier': tier,
            'state': state,
            'character': spec['character'].to_dict(),
            'progression': spec['progression'].to_dict(),
            'generator_model': model,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate synthetic GM training data.')
    parser.add_argument('--n', type=int, default=25,
                        help='examples to add (default 25; full dataset target is 300+)')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--model', default=BASE_MODEL_NAME,
                        help='Ollama model that writes the data (default: the base game model)')
    parser.add_argument('--stage-attempts', type=int, default=3,
                        help='retries per auxiliary stage (default 3)')
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--timeout', type=int, default=180,
                        help='seconds per Ollama call (default 180)')
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    existing = sum(1 for _ in args.out.open(encoding='utf-8')) if args.out.exists() else 0
    print(f'Dataset {args.out}: {existing} existing examples; '
          f'adding {args.n} with generator model {args.model}.')

    rejections = Counter()
    accepted = skipped = 0
    started = time.time()
    with args.out.open('a', encoding='utf-8') as out:
        while accepted < args.n:
            spec = specs.sample_spec(rng)
            record = generate_example(spec, args.model, args.timeout,
                                      args.stage_attempts, rejections)
            if record is None:
                skipped += 1
                print(f'  skipped a spec ({spec["action_kind"]}) - all candidates failed validation')
                continue
            record['id'] = existing + accepted
            out.write(json.dumps(record, ensure_ascii=False) + '\n')
            out.flush()
            accepted += 1
            elapsed = time.time() - started
            print(f'  [{accepted}/{args.n}] {spec["action_kind"]} '
                  f'(rolls {spec["rolls"]}) - {elapsed / accepted:.0f}s/example avg')

    print(f'\nDone: {accepted} accepted, {skipped} specs skipped, '
          f'{time.time() - started:.0f}s total.')
    if rejections:
        print('Rejection reasons (candidates and retries, not final skips):')
        for reason, count in rejections.most_common(12):
            print(f'  {count:4d}  {reason}')


if __name__ == '__main__':
    main()
