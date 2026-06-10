from rolls import rolls
from model import generate_response
from scoring import select_best_candidate
import copy, re

TOKEN_LIMIT = 4096
ROLLS_TOKEN_RESERVE = 30
ACTION_TOKEN_RESERVE = 200

SECTION_HEADERS = ['OVERALL STORY', 'CURRENT QUEST', 'PLAYER STATUS']

_SECTION_PATTERN = re.compile(
    r'(OVERALL STORY|CURRENT QUEST|PLAYER STATUS)\s*:\s*(.*?)(?=(?:OVERALL STORY|CURRENT QUEST|PLAYER STATUS)\s*:|\Z)',
    re.IGNORECASE | re.DOTALL
)

# Phrases suggesting a quest concluded (success or failure). Treated as also
# touching the overall story, since resolving a quest is the kind of beat that
# moves the wider narrative forward.
QUEST_RESOLUTION_KEYWORDS = [
    'quest complete', 'quest is complete', 'quest finished', 'quest failed',
    'objective complete', 'objective achieved', 'mission accomplished',
    'mission complete', 'mission failed', 'you have completed', "you've completed",
    'puzzle solved', 'mystery solved', 'you found the', 'you rescue', 'you rescued',
    'you defeat', 'you defeated', 'you have defeated',
]

# Phrases suggesting the player's status (HP, inventory, level, etc.) changed.
STATUS_CHANGE_KEYWORDS = [
    'hit point', 'hp', 'health', 'damage', 'wound', 'injur', 'heal', 'bleed',
    'unconscious', 'exhaust', 'fatigue', 'poison', 'level up', 'leveled up',
    'experience point', 'xp', 'spell slot', 'inventory', 'equip', 'pick up',
    'picked up', 'you gain', 'you lose', 'potion', 'weapon', 'armor', 'armour',
    'gold piece',
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

def _trim_to_memory_budget(memory, rules_content, summary_text):
    '''
    Post-summary trim: drop oldest messages (index 0) until memory fits the
    budget left after rules, the rolls reserve, the updated summary and the
    action reserve. Can empty memory entirely if the budget is negative.
    Mutates memory in place.
    '''
    rules_tokens = len(rules_content) // 4
    summary_tokens = len(summary_text) // 4
    memory_budget = TOKEN_LIMIT - rules_tokens - ROLLS_TOKEN_RESERVE - summary_tokens - ACTION_TOKEN_RESERVE
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
    keyword match on quest-resolution and status-change phrases. Returns a
    (possibly empty) set of affected section headers.
    '''
    text = (action + ' ' + response).lower()

    affected = set()
    if _contains_keyword(text, QUEST_RESOLUTION_KEYWORDS):
        affected.add('CURRENT QUEST')
        affected.add('OVERALL STORY')
    if _contains_keyword(text, STATUS_CHANGE_KEYWORDS):
        affected.add('PLAYER STATUS')

    return affected

def _parse_requested_sections(text, headers):
    '''
    Extract the given section headers from text as {header: body}.
    Returns None if any requested header is missing.
    '''
    found = {}
    for match in _SECTION_PATTERN.finditer(text):
        header = match.group(1).upper()
        if header in headers:
            found[header] = match.group(2).strip()

    if all(header in found for header in headers):
        return found
    return None

def _parse_sections(text):
    return _parse_requested_sections(text, SECTION_HEADERS)

def _build_summary(sections):
    return '\n\n'.join(f'{header}: {sections[header]}' for header in SECTION_HEADERS)

def context_update(chatlogs, context_logs, memory, rules, hierarchical_summary, tokens, save, backup):

    try:
        old_chatlogs = copy.deepcopy(chatlogs)
        old_context_logs = copy.deepcopy(context_logs)
        old_memory = copy.deepcopy(memory)
        old_tokens = copy.deepcopy(tokens)

        action = input("\nDescribe the players' actions: ")

        chatlogs.append({
            'role': 'user',
            'content': action
        })

        rolls_message = rolls()
        # Preserve original rules content so we can restore it later
        original_rules_content = rules['content']
        rules['content'] = original_rules_content + rolls_message

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

        # Pre-send safety trim: drop oldest old messages until prompt fits under token limit
        _trim_presend(memory)

        try:
            # Response streamed by function
            response_text, prompt_tokens = generate_response(memory, stream=True)

        except KeyboardInterrupt:

            save()
            quit()

        except Exception as e:

            print(e)

            backup(
                old_chatlogs,
                old_context_logs,
                old_memory,
                old_tokens
            )

            quit()

        context = [prompt_tokens] + copy.deepcopy(memory)

        tokens += prompt_tokens

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
                if header in _classify_exchange(action, response_text)
            ]
        else:
            # Doesn't match the expected three-section structure (e.g. a
            # hand-written scenario summary) - fall back to regenerating it whole.
            affected_sections = list(SECTION_HEADERS)

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

            instructions = [{
                'role': 'user',
                'content':
                f'''TASK: Update ONLY the following section(s) of the Summary: {section_list}.

                1. Output exactly those section(s) and nothing else. Start each one on its own line with its heading written exactly as shown, e.g. "CURRENT QUEST: ...".
                2. Do not output any other section, heading, or commentary.
                3. Give exactly THREE alternative updated versions of the section(s).
                4. Separate the alternatives by a line containing only: BREAK.
                5. Do not add any text before the first alternative or after the last alternative.

                This is the current text of the section(s) to update: {old_affected_text}
                These are the last interactions: {last_n_interactions}
                '''
            }]

            try:

                hierarchical_summaries, summary_tokens = (generate_response(instructions))
                tokens += summary_tokens

            except Exception:

                print("ERROR: Hierarchical Summaries not obtained.")
                hierarchical_summaries = None

            if hierarchical_summaries:

                candidates = [
                    parsed for parsed in (
                        _parse_requested_sections(candidate, affected_sections)
                        for candidate in hierarchical_summaries.split("BREAK")
                    )
                    if parsed is not None
                ]

                if candidates:

                    candidate_texts = [
                        '\n\n'.join(f'{header}: {parsed[header]}' for header in affected_sections)
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

                else:
                    print("WARNING: No valid summary candidates contained the required section(s); keeping the previous summary.")

        # Post-summary trim: trim persistent memory using updated summary's actual token cost
        _trim_to_memory_budget(memory, rules['content'], hierarchical_summary)

        context_logs.append(context)

    except KeyboardInterrupt:

        save()
        quit()

    except Exception as e:

        print(e)

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
        hierarchical_summary
    )