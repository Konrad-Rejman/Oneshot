'''
Synthetic training-data generator for Phase 3 (ROADMAP 3.1).

Every example is one full game turn in the exact shape the model sees in
production: the prompt is assembled with the same code the game uses
(gm_rules.RULES_TEXT + Character.to_prompt + Progression.to_prompt +
rolls_message, flattened by model._build_prompt_from_memory), so the
training and inference formats cannot drift.

All prose is written by the local base model itself (self-distillation;
see training/COMPLIANCE.md for why): from a structural spec (specs.py) the
model writes a three-section summary, an opening scene and a player action,
then answers the assembled production prompt as the GM. Several GM
candidates are sampled at different temperatures and the first one to pass
every validator (validators.py) is kept - the fine-tune learns from the
filtered best of the base model's own behaviour, which is where the quality
gain comes from.

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
from training import specs, validators  # noqa: E402

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
        f'Your character attempts the following: {spec["action_kind"]}.'
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


def generate_example(spec, model, candidates, timeout, attempts, rejections):
    '''
    Run all four stages for one spec. Returns a dataset record dict or
    None when any stage fails validation on every attempt.
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

    prompt_text = _build_prompt_from_memory(build_gm_memory(spec, summary, scene, action))
    for temperature in CANDIDATE_TEMPERATURES[:candidates]:
        response = call_ollama(prompt_text, model, temperature, 700, timeout)
        reasons = validators.validate_gm_response(response, spec['rolls'],
                                                  require_check=spec['requires_check'])
        if not reasons:
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
                    'character': spec['character'].to_dict(),
                    'progression': spec['progression'].to_dict(),
                    'generator_model': model,
                    'temperature': temperature,
                },
            }
        rejections.update(reasons)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate synthetic GM training data.')
    parser.add_argument('--n', type=int, default=25,
                        help='examples to add (default 25; full dataset target is 300+)')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--model', default=BASE_MODEL_NAME,
                        help='Ollama model that writes the data (default: the base game model)')
    parser.add_argument('--candidates', type=int, default=4,
                        help='GM response candidates tried per example (default 4)')
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
            record = generate_example(spec, args.model, args.candidates,
                                      args.timeout, args.stage_attempts, rejections)
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
