from rolls import rolls
from rouge_score import rouge_scorer
from sklearn.metrics.pairwise import cosine_similarity
from model import generate_response
import copy, re, spacy

nlp = spacy.load('en_core_web_md')

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

def _contains_keyword(text, keywords):
    return any(re.search(r'\b' + re.escape(keyword) + r'\b', text) for keyword in keywords)

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

        rouge = rouge_scorer.RougeScorer(
            ['rouge1', 'rouge2', 'rougeL'],
            use_stemmer=True
        )

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
        # memory layout: [rules, summary, ...old interactions..., action]
        while _estimate_tokens(memory) > TOKEN_LIMIT and len(memory) > 3:
            memory.pop(2)

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

            reference_summary = (
                old_affected_text
                + "\n\nLAST INTERACTIONS:\n\n"
                + last_n_interactions
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

                    scores = {
                        'rouge1': [],
                        'rouge2': [],
                        'rougeL': []
                    }

                    for text in candidate_texts:

                        r = rouge.score(
                            text,
                            reference_summary
                        )

                        for metric in r:
                            scores[metric].append(
                                r[metric]
                            )

                    cos_sim = []

                    cos_reference = nlp(
                        reference_summary
                    )

                    for text in candidate_texts:

                        similarity = cosine_similarity(
                            [cos_reference.vector],
                            [nlp(text).vector]
                        )[0][0]

                        cos_sim.append(similarity)

                    overall_scores = [

                        0.5 * cos_sim[i]
                        + 0.2 * scores['rouge1'][i].fmeasure
                        + 0.2 * scores['rouge2'][i].fmeasure
                        + 0.2 * scores['rougeL'][i].fmeasure

                        for i in range(
                            len(candidates)
                        )
                    ]

                    best = candidates[overall_scores.index(max(overall_scores))]

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
        rules_tokens = len(rules['content']) // 4
        summary_tokens = len(hierarchical_summary) // 4
        memory_budget = TOKEN_LIMIT - rules_tokens - ROLLS_TOKEN_RESERVE - summary_tokens - ACTION_TOKEN_RESERVE
        while _estimate_tokens(memory) > memory_budget and memory:
            memory.pop(0)

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