from rolls import roll_values, rolls_message
from model import generate_response, active_model
import ui
from scoring import select_best_candidate
from progression import (
    parse_state_changes, apply_state_changes, pending_level_ups,
    prompt_level_up, is_dead, prompt_death,
)
import copy, re

TOKEN_LIMIT = 4096
ROLLS_TOKEN_RESERVE = 30
ACTION_TOKEN_RESERVE = 200
SUMMARY_UPDATE_INTERVAL = 5

SECTION_HEADERS = ['OVERALL STORY', 'CURRENT QUEST', 'PLAYER STATUS']

# Header matching is deliberately tolerant of markdown decoration
# ("**CURRENT QUEST**:", "## CURRENT QUEST:") because the summariser model
# adds it despite being told not to; [\s*_]* allows decoration between the
# header and its colon, and the lookahead allows it before the next header.
_SECTION_PATTERN = re.compile(
    r'(OVERALL STORY|CURRENT QUEST|PLAYER STATUS)[\s*_]*:\s*(.*?)'
    r'(?=[\s*_#]*(?:OVERALL STORY|CURRENT QUEST|PLAYER STATUS)[\s*_]*:|\Z)',
    re.IGNORECASE | re.DOTALL
)

# Phrases suggesting a quest concluded (success or failure). Treated as also
# touching the overall story, since resolving a quest is the kind of beat that
# moves the wider narrative forward.
QUEST_RESOLUTION_KEYWORDS = [
    'quest complete', 'quest is complete', 'quest finished', 'quest failed',
    'quest accomplished', 'quest is over', 'quest concluded',
    'objective complete', 'objective is complete', 'objective achieved',
    'objective failed', 'mission accomplished', 'mission complete',
    'mission failed', 'task complete', 'task is complete', 'task accomplished',
    'task failed', 'goal achieved', 'goal accomplished',
    'you have completed', "you've completed", 'you complete the',
    'you completed the', 'you have fulfilled', 'you fulfill',
    'you failed the quest', 'you failed the mission',
    'puzzle solved', 'mystery solved', 'you found the', 'you rescue', 'you rescued',
    'you save the', 'you saved the', 'you claim the', 'you claimed the',
    'you defeat', 'you defeated', 'you have defeated', 'you slay', 'you slew',
    'you have slain', 'you vanquish', 'you vanquished', 'you triumph', 'victory',
    'you have won', 'curse is lifted', 'curse is broken', 'the day is saved',
]

# Phrases marking a major narrative beat that moves the overall story without
# being a quest resolution or a player-status change: revelations, NPC deaths,
# betrayals, new allies, and world/faction events. Touches OVERALL STORY only.
# Curated for precision - location/arrival words are omitted because they fire
# on routine movement rather than story-shifting events.
STORY_BEAT_KEYWORDS = [
    'you learn that', 'you discover', 'is revealed', 'reveals that',
    'the truth about', 'the secret of', 'prophecy', 'prophet',
    'betray', 'alliance', 'an ally', 'new ally', 'nemesis', 'rival',
    'join you', 'joins you', 'joins your', 'join your party',
    'is dead', 'has died', 'lies dead', 'is slain', 'murder', 'assassinat',
    'declare war', 'declares war', 'war breaks out', 'invasion', 'invade',
    'rebellion', 'uprising', 'plague', 'famine', 'kingdom falls',
    'the city falls', 'crowned', 'coronation', 'time passes', 'years pass',
]

# Phrases suggesting the player's status (HP, inventory, level, etc.) changed.
# Favours narrative condition and acquisition words over generic item nouns,
# since a STATE line already forces a PLAYER STATUS refresh on mechanical change.
STATUS_CHANGE_KEYWORDS = [
    'hit point', 'hp', 'health', 'damage', 'wound', 'injur', 'heal', 'bleed',
    'unconscious', 'exhaust', 'fatigue', 'poison', 'paralyz', 'paralys',
    'stunned', 'blinded', 'cursed', 'disease', 'infect', 'starv', 'hungr',
    'thirst', 'cured', 'revive', 'resurrect', 'you collapse', 'you die',
    'you perish', 'level up', 'leveled up', 'levels up', 'gain a level',
    'gained a level', 'experience point', 'xp', 'gain experience',
    'gains experience', 'inventory', 'equip', 'pick up', 'picked up',
    'you gain', 'you lose', 'you acquire', 'you obtain', 'you are given',
    'hands you', 'you steal', 'you stole', 'you pocket', 'you discard',
    'you drop the', 'you buy', 'you bought', 'you sell', 'you sold',
    'you purchase', 'you barter', 'loot', 'treasure', 'potion', 'weapon',
    'armor', 'armour', 'gold piece', 'gold coin', 'silver coin', 'coins',
]

def _estimate_tokens(messages):
    return sum(len(msg.get('content', '')) for msg in messages) // 4

def _trim_presend(memory):
    '''
    Pre-send safety trim: drop oldest old messages (index 2) until the prompt
    fits under the token limit. Memory layout: [rules, summary, ...old
    interactions..., action] — rules, summary and the trailing action are
    never dropped. Mutates memory in place.
    '''
    while _estimate_tokens(memory) > TOKEN_LIMIT and len(memory) > 3:
        memory.pop(2)

def _trim_to_memory_budget(memory, rules_content, summary_text, character_text=''):
    '''
    Post-summary trim: drop oldest messages (index 0) until memory fits the
    budget left after rules, the character sheet, the rolls reserve, the
    updated summary and the action reserve. Can empty memory entirely if the
    budget is negative. Mutates memory in place.
    '''
    rules_tokens = len(rules_content) // 4
    character_tokens = len(character_text) // 4
    summary_tokens = len(summary_text) // 4
    memory_budget = TOKEN_LIMIT - rules_tokens - character_tokens - ROLLS_TOKEN_RESERVE - summary_tokens - ACTION_TOKEN_RESERVE
    while _estimate_tokens(memory) > memory_budget and memory:
        memory.pop(0)

def _contains_keyword(text, keywords):
    '''
    Return True if any keyword appears in text. Keywords may be multi-word
    phrases ('quest complete') or word stems ('injur', which should match
    "injured" and "injuries").
    '''
    return any(re.search(r'\b' + re.escape(keyword), text) for keyword in keywords)

def _classify_exchange(action, response):
    '''
    Classify which summary section(s) a turn's exchange likely affects, by
    keyword match on quest-resolution, story-beat and status-change phrases.
    Returns a (possibly empty) set of affected section headers.
    '''
    text = (action + ' ' + response).lower()

    affected = set()
    if _contains_keyword(text, QUEST_RESOLUTION_KEYWORDS):
        affected.add('CURRENT QUEST')
        affected.add('OVERALL STORY')
    if _contains_keyword(text, STORY_BEAT_KEYWORDS):
        affected.add('OVERALL STORY')
    if _contains_keyword(text, STATUS_CHANGE_KEYWORDS):
        affected.add('PLAYER STATUS')

    return affected

def _affected_sections(action, response, state_changed):
    '''
    Summary sections this turn's exchange affects: the keyword
    classification, plus PLAYER STATUS whenever the GM's STATE line reported
    a mechanical change (HP/XP/items) - those belong in the status
    section even when the narration dodges the keyword lists.
    '''
    affected = _classify_exchange(action, response)
    if state_changed:
        affected.add('PLAYER STATUS')
    return affected

def _clean_body(body):
    '''
    Strip stray markdown decoration and whitespace from the edges of a
    section body; inner formatting is left alone.
    '''
    return re.sub(r'^[\s*_#]+|[\s*_]+$', '', body)

def _find_sections(text, headers):
    '''
    Extract whichever of the given section headers appear in text as
    {header: body}. Sections whose body is empty are treated as missing, so
    a bare heading can never blank out a section.
    '''
    found = {}
    for match in _SECTION_PATTERN.finditer(text):
        header = match.group(1).upper()
        if header in headers:
            body = _clean_body(match.group(2))
            if body:
                found[header] = body
    return found

def _apply_forced_update(affected_sections, turns_since_update):
    '''
    Staleness guard: when the keyword classifier found nothing and the
    summary hasn't changed for SUMMARY_UPDATE_INTERVAL turns (counting the
    current one), force a full refresh of every section. Keyword-classified
    sections always pass through untouched. The counter only resets on a
    successful update, so a failed forced refresh retries next turn instead
    of waiting another full interval.
    '''
    if not affected_sections and turns_since_update >= SUMMARY_UPDATE_INTERVAL:
        return list(SECTION_HEADERS)
    return affected_sections

def _parse_requested_sections(text, headers):
    '''
    Extract the given section headers from text as {header: body}.
    Returns None if any requested header is missing.
    '''
    found = _find_sections(text, headers)
    if all(header in found for header in headers):
        return found
    return None

def _parse_partial_sections(text, headers):
    '''
    Tolerant variant of _parse_requested_sections: returns whichever of the
    requested sections are present, or None if none are. Used for summary
    candidates when the old summary parses, since the merge step fills any
    section a candidate missed with its previous text.
    '''
    found = _find_sections(text, headers)
    return found if found else None

def _parse_sections(text):
    return _parse_requested_sections(text, SECTION_HEADERS)

def _build_summary(sections):
    return '\n\n'.join(f'{header}: {sections[header]}' for header in SECTION_HEADERS)

def context_update(chatlogs, context_logs, memory, rules, hierarchical_summary, tokens, save, backup, character=None, turns_since_summary_update=0, progression=None):

    try:
        old_chatlogs = copy.deepcopy(chatlogs)
        old_context_logs = copy.deepcopy(context_logs)
        old_memory = copy.deepcopy(memory)
        old_tokens = copy.deepcopy(tokens)

        # Status bar (ROADMAP 2.4) above the pinned input line: name, HP,
        # level, XP, cumulative tokens, read straight off the dataclasses,
        # plus the active GM model (ROADMAP 3 base/fine-tuned toggle).
        if character is not None and progression is not None:
            ui.status_bar(character, progression, tokens, active_model())
        action = ui.ask("Describe the players' actions:")

        chatlogs.append({
            'role': 'user',
            'content': action
        })

        # The turn's D20 pool, shown colour-coded once the action is locked
        # in (the same values the model consumes this turn).
        turn_rolls = roll_values()
        ui.dice(turn_rolls)
        turn_rolls_message = rolls_message(turn_rolls)
        # Character sheet appended to the system prompt each turn (like the
        # rolls) so trims can never drop it; tokens are accounted for in the
        # post-summary budget below.
        character_text = '\n\n' + character.to_prompt() if character else ''
        # Current HP/level/XP/inventory (ROADMAP 2.3), surfaced the same
        # way as the character sheet so the model references them accurately.
        progression_text = '\n\n' + progression.to_prompt() if progression else ''
        # The bare rules content, restored after the model call strips the
        # turn's appended sheet/STATUS/rolls
        original_rules_content = rules['content']
        rules['content'] = original_rules_content + character_text + progression_text + turn_rolls_message

        if memory[0] == rules:

            memory = (
                [rules,
                 {'role': 'user', 'content': hierarchical_summary}]
                + memory[1:]
                + [{'role': 'user', 'content': action}]
            )

        else:

            memory = (
                [rules,
                 {'role': 'user', 'content': hierarchical_summary}]
                + memory
                + [{'role': 'user', 'content': action}]
            )

        _trim_presend(memory)

        try:
            response_text, prompt_tokens = generate_response(memory, stream=True)

        except KeyboardInterrupt:

            save()
            quit()

        except Exception as e:

            ui.error(e)

            backup(
                old_chatlogs,
                old_context_logs,
                old_memory,
                old_tokens
            )

            quit()

        context = [prompt_tokens] + copy.deepcopy(memory)

        tokens += prompt_tokens

        # Strip the machine-read STATE line (ROADMAP 2.3) before the response
        # is stored anywhere; the parsed changes are applied at the end of
        # the turn, after the summary phase, so a crash there backs up a
        # progression consistent with the backed-up chatlogs.
        if progression is not None:
            response_text, state_changes = parse_state_changes(response_text)
        else:
            state_changes = []

        chatlogs.append({
            'role':'assistant',
            'content':response_text
        })

        memory.append({
            'role':'assistant',
            'content':response_text
        })

        rules['content'] = original_rules_content
        memory.remove(rules)

        summary_msg = {
            'role': 'user',
            'content': hierarchical_summary
        }

        if summary_msg in memory:
            memory.remove(summary_msg)

        # Work out which section(s) of the summary this exchange actually
        # touched, so we only regenerate those.
        old_sections = _parse_sections(hierarchical_summary)

        if old_sections is not None:
            affected_sections = [
                header for header in SECTION_HEADERS
                if header in _affected_sections(action, response_text, bool(state_changes))
            ]
        else:
            # Doesn't match the expected three-section structure (e.g. a
            # hand-written scenario summary) - fall back to regenerating it whole.
            affected_sections = list(SECTION_HEADERS)

        # A quiet stretch of narration can dodge the keyword classifier for
        # many turns and let the summary drift out of date; force a full
        # refresh once enough turns pass without a successful update.
        turns_since_summary_update += 1
        affected_sections = _apply_forced_update(affected_sections, turns_since_summary_update)

        if affected_sections:

            last_n_interactions = ""

            for prompt in memory:

                last_n_interactions += (
                    prompt['content']
                    + "\n\n"
                )

            if old_sections is not None:
                old_affected_text = '\n\n'.join(
                    f'{header}: {old_sections[header]}' for header in affected_sections
                )
            else:
                old_affected_text = hierarchical_summary

            # Scoring reference (ROADMAP 1.3): old affected sections + the
            # last two exchanges only, so candidates are judged on what just
            # happened rather than rewarded for echoing older history. The
            # generation prompt below still sees the full memory.
            reference_interactions = '\n\n'.join(
                prompt['content'] for prompt in memory[-4:]
            )

            reference_summary = (
                old_affected_text
                + "\n\nLAST INTERACTIONS:\n\n"
                + reference_interactions
            )

            section_list = ', '.join(affected_sections)

            # The output skeleton and the explicit markdown/numbering ban are
            # load-bearing: mistral:instruct otherwise decorates or renames
            # the headings, which makes candidates unparseable.
            instructions = [{
                'role': 'user',
                'content':
f'''TASK: Update ONLY the following section(s) of the story summary: {section_list}.

Rules:
1. Write THREE alternative updated versions of the section(s): {section_list}.
2. Separate the alternatives with a line containing only the word: BREAK
3. Start each section on its own line as plain uppercase text with a colon, exactly like this: "{affected_sections[0]}: <updated text>".
4. Plain text only. No markdown, no asterisks, no numbering, no commentary, no text before the first alternative or after the last.

Reply in exactly this shape:
<updated section(s), version 1>
BREAK
<updated section(s), version 2>
BREAK
<updated section(s), version 3>

Current text of the section(s) to update:
{old_affected_text}

Latest interactions:
{last_n_interactions}'''
            }]

            try:

                hierarchical_summaries, summary_tokens = (generate_response(instructions))
                tokens += summary_tokens

            except Exception:

                ui.error("ERROR: Hierarchical Summaries not obtained.")
                hierarchical_summaries = None

            if hierarchical_summaries:

                # When the old summary parses, a candidate covering only some
                # of the affected sections is still usable - the merge below
                # keeps the previous text for whatever it missed. Only an
                # unstructured old summary (regenerated whole, nothing to
                # merge into) needs every section present.
                parse = (
                    _parse_requested_sections if old_sections is None
                    else _parse_partial_sections
                )

                candidates = [
                    parsed for parsed in (
                        parse(candidate, affected_sections)
                        for candidate in hierarchical_summaries.split("BREAK")
                    )
                    if parsed is not None
                ]

                if candidates:

                    candidate_texts = [
                        '\n\n'.join(
                            f'{header}: {parsed[header]}'
                            for header in affected_sections if header in parsed
                        )
                        for parsed in candidates
                    ]

                    best = candidates[
                        select_best_candidate(candidate_texts, reference_summary)
                    ]

                    if old_sections is not None:
                        merged_sections = dict(old_sections)
                        merged_sections.update(best)
                        hierarchical_summary = _build_summary(merged_sections)
                    else:
                        hierarchical_summary = '\n\n'.join(
                            f'{header}: {best[header]}' for header in affected_sections
                        )

                    turns_since_summary_update = 0

                else:
                    ui.warn("WARNING: No valid summary candidates contained the required section(s); keeping the previous summary.")

        _trim_to_memory_budget(memory, rules['content'], hierarchical_summary,
                               character_text + progression_text)

        context_logs.append(context)

        # Progression bookkeeping (ROADMAP 2.3): apply the turn's STATE-line
        # changes, then handle any level-up or death they caused.
        if progression is not None:
            apply_state_changes(progression, state_changes)
            if character is not None and pending_level_ups(progression) > 0:
                prompt_level_up(progression, character)
            if is_dead(progression):
                if prompt_death(progression):
                    revival = {
                        'role': 'user',
                        'content': f'(The character died but was resurrected by forces unknown, '
                                   f'awakening with {progression.hp} HP. Continue the story from their revival.)'
                    }
                    chatlogs.append(revival)
                    memory.append(revival)
                else:
                    save()
                    quit()

    except KeyboardInterrupt:

        save()
        quit()

    except Exception as e:

        ui.error(e)

        backup(
            old_chatlogs,
            old_context_logs,
            old_memory,
            old_tokens
        )

        quit()

    return (
        tokens,
        memory,
        hierarchical_summary,
        turns_since_summary_update
    )