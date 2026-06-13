'''
Deterministic validators for the Phase 3 training pipeline (ROADMAP 3.1).

Every piece of generated text (scene, summary, player action, GM response)
passes through these checks before it may enter the dataset; the fine-tune
then bakes in the behaviours the filters enforce - exact STATE-line grammar,
dice consumed from the pool left-to-right, plain-text output, staying in
character. Checks are deliberately strict: a rejected good example costs one
retry, an accepted bad example pollutes the dataset.

These are stricter than the game's runtime parsers on purpose: the game
tolerates markdown-decorated STATE lines (progression.py) because the base
model misbehaves, but training data must show only the canonical format.

Pure functions over strings (plus the roll pool) - no model calls, no game
imports - so the test suite covers them like the rest of the deterministic
logic (tests/test_training_validators.py). Each check returns a list of
human-readable failure reasons, empty when the text passes.
'''
import re

# A roll announcement: a 1-2 digit number in the same clause as a form of
# "roll" ("you roll a 13", "rolling an 18"). The window stops at sentence
# punctuation so a check announced without its number ("Roll a Wisdom
# check...") is not paired with a number from the next sentence.
_ROLL_ANNOUNCE = re.compile(
    r'\broll(?:s|ed|ing)?\b[^.!?\n]{0,60}?\b(\d{1,2})\b', re.IGNORECASE)

# Canonical STATE line and entry grammar - the exact format the rules prompt
# mandates, with none of the runtime parser's markdown tolerance.
_STATE_LINE = re.compile(r'^STATE:\s*(.*?)\s*$')
_STATE_ENTRY_PATTERNS = [
    re.compile(r'^HP [+-]\d+$'),
    re.compile(r'^XP \+\d+$'),
    re.compile(r'^GAIN \S.*$'),
    re.compile(r'^LOSE \S.*$'),
]

# Output-format bans (the OUTPUT FORMAT rules section): markdown markers
# anywhere, list bullets/numbering at line starts, and square brackets (which
# also catch instruction-template leakage like "[INST]").
_BANNED_CHARS = ('*', '#', '`', '[', ']')
_BULLET_LINE = re.compile(r'^\s*(?:-\s|\d+\.\s)')

# Character breaks and instruction leakage (the PERSONA rules section). All
# lowercase; matched as substrings of the lowercased text. Phrases an NPC
# could plausibly speak in dialogue ("I cannot help you") are deliberately
# not listed - only wording that can't appear in honest in-world narration.
_META_PHRASES = [
    'as an ai', 'language model', 'ai model',
    'system message', 'roll list', 'pre-rolled', 'the player',
    'as the game master', 'as your game master', 'state line',
    'character sheet', 'status block', 'these instructions',
]

# The three summary section headers, strict plain form at line start.
_SUMMARY_HEADERS = ['OVERALL STORY', 'CURRENT QUEST', 'PLAYER STATUS']


def find_announced_rolls(text):
    '''Roll values announced in the narration, in order of appearance.'''
    return [int(value) for value in _ROLL_ANNOUNCE.findall(text)]


def check_dice(text, pool, require_check=True):
    '''
    The dice contract: every announced roll value must be drawn from the
    pre-rolled pool left-to-right (a strict prefix of it), and an action that
    warrants a check must announce at least one roll.
    '''
    announced = find_announced_rolls(text)
    reasons = []
    if require_check and not announced:
        reasons.append('no roll announced for a check-worthy action')
    if len(announced) > len(pool):
        reasons.append(f'announced {len(announced)} rolls, pool has {len(pool)}')
    elif any(not 1 <= value <= 20 for value in announced):
        reasons.append(f'announced roll outside 1-20: {announced}')
    elif announced != pool[:len(announced)]:
        reasons.append(f'announced rolls {announced} are not the pool prefix {pool[:len(announced)]}')
    return reasons


def check_state_line(text):
    '''
    Exactly one STATE line, as the last line, every entry matching the
    canonical grammar ("HP -3", "XP +25", "GAIN torch", "LOSE rope") or the
    single word "none".
    '''
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return ['empty response']
    state_lines = [line for line in lines if line.upper().startswith('STATE')]
    if not state_lines:
        return ['missing STATE line']
    if len(state_lines) > 1:
        return ['more than one STATE line']
    match = _STATE_LINE.match(lines[-1])
    if state_lines[0] != lines[-1] or not match:
        return ['STATE line is not the canonical final line']
    body = match.group(1)
    if body.lower() == 'none':
        return []
    reasons = []
    for raw_entry in body.split(';'):
        entry = raw_entry.strip()
        if not entry or not any(p.match(entry) for p in _STATE_ENTRY_PATTERNS):
            reasons.append(f'malformed STATE entry: {raw_entry.strip()!r}')
    return reasons


def check_no_state_line(text):
    '''For scenes, actions and summaries, which must not carry a STATE line.'''
    if any(line.strip().upper().startswith('STATE')
           for line in text.splitlines()):
        return ['unexpected STATE line']
    return []


def check_plain_text(text):
    '''The OUTPUT FORMAT contract: no markdown, no bullets, no brackets.'''
    reasons = []
    for char in _BANNED_CHARS:
        if char in text:
            reasons.append(f'banned character {char!r}')
    if any(_BULLET_LINE.match(line) for line in text.splitlines()):
        reasons.append('list bullet or numbering at line start')
    return reasons


def check_no_meta(text):
    '''The PERSONA contract: never break character or surface the rules.'''
    lowered = text.lower()
    return [f'character break / instruction leak: {phrase!r}'
            for phrase in _META_PHRASES if phrase in lowered]


def check_second_person(text):
    '''GM narration must address the player as "you" from the start.'''
    if not re.search(r'\byou\b', text[:300], re.IGNORECASE):
        return ['no second-person address near the start']
    return []


def check_length(text, min_chars, max_chars):
    if len(text) < min_chars:
        return [f'too short ({len(text)} < {min_chars} chars)']
    if len(text) > max_chars:
        return [f'too long ({len(text)} > {max_chars} chars)']
    return []


def validate_gm_response(text, pool, require_check=True,
                         min_chars=120, max_chars=1800):
    '''
    Full gate for a GM response candidate: plain text, in character, second
    person, one canonical STATE line at the end, dice from the pool in order.
    Returns a (possibly empty) list of failure reasons.
    '''
    return (
        check_length(text, min_chars, max_chars)
        + check_plain_text(text)
        + check_no_meta(text)
        + check_second_person(text)
        + check_state_line(text)
        + check_dice(text, pool, require_check)
    )


def validate_scene(text, min_chars=100, max_chars=1200):
    '''
    Gate for a generated opening scene: like a GM response but with no
    STATE line and no dice rolled - nothing is being resolved yet.
    '''
    reasons = (
        check_length(text, min_chars, max_chars)
        + check_plain_text(text)
        + check_no_meta(text)
        + check_second_person(text)
        + check_no_state_line(text)
    )
    if find_announced_rolls(text):
        reasons.append('opening scene announces a roll')
    return reasons


def validate_narration(text, min_chars=80, max_chars=1200):
    '''
    Gate for a generated GM narration (the prose body of a check turn, before
    the deterministic announce/STATE lines are wrapped around it): like a
    scene but it must never talk about dice or rolls, since the mechanics are
    added by the pipeline, not the model.
    '''
    reasons = (
        check_length(text, min_chars, max_chars)
        + check_plain_text(text)
        + check_no_meta(text)
        + check_second_person(text)
        + check_no_state_line(text)
    )
    if find_announced_rolls(text):
        reasons.append('narration announces a roll')
    if re.search(r'\b(roll|rolls|rolled|rolling|dice)\b', text, re.IGNORECASE):
        reasons.append('narration mentions dice or rolling')
    return reasons


def validate_action(text, min_chars=10, max_chars=300):
    '''Gate for a generated player action: short first-person prose.'''
    reasons = (
        check_length(text, min_chars, max_chars)
        + check_plain_text(text)
        + check_no_state_line(text)
    )
    if not re.search(r'\bI\b', text):
        reasons.append('player action is not first person')
    if find_announced_rolls(text):
        reasons.append('player action announces a roll')
    return reasons


def validate_summary(text, max_chars=1200):
    '''
    Gate for a generated three-section summary: all three headers present
    in order at line starts, each with a non-empty body, plain text.
    '''
    reasons = check_plain_text(text) + check_no_state_line(text)
    if len(text) > max_chars:
        reasons.append(f'too long ({len(text)} > {max_chars} chars)')
    positions = []
    for header in _SUMMARY_HEADERS:
        match = re.search(rf'^{header}: *(.+)$', text, re.MULTILINE)
        if not match or not match.group(1).strip():
            reasons.append(f'missing or empty section: {header}')
        else:
            positions.append(match.start())
    if len(positions) == len(_SUMMARY_HEADERS) and positions != sorted(positions):
        reasons.append('sections out of order')
    return reasons
