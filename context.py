from rolls import rolls
from rouge_score import rouge_scorer
from sklearn.metrics.pairwise import cosine_similarity
from model import generate_response
import copy, spacy

nlp = spacy.load('en_core_web_md')

def context_update(chatlogs, context_logs, memory, rules, hierarchical_summary, tokens, save, backup, n=3):

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

        context = [prompt_tokens] + memory.copy()

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

        if len(memory) > 2 * n:
            memory = memory[-2*n:]

        last_n_interactions = ""

        for prompt in memory:

            last_n_interactions += (
                prompt['content']
                + "\n\n"
            )

        reference_summary = (
            hierarchical_summary
            + "\n\nLAST INTERACTIONS:\n\n"
            + last_n_interactions
        )

        instructions = [{
            'role': 'user',
            'content':
            f'''TASK: Update the Summary.

            1. Do not remove the current headings (OVERALL STORY, CURRENT QUEST, PLAYER STATUS) or change the structure. 
            2. Give exactly THREE alternative updated summaries. 
            3. Separate the summaries by a line containing only: BREAK. 
            4. Do not add any text before the first summary or after the last summary.

            This is the old summary: {hierarchical_summary}
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

            hierarchical_summaries = (
                hierarchical_summaries.split("BREAK")
            )

            scores = {
                'rouge1': [],
                'rouge2': [],
                'rougeL': []
            }

            for summary in hierarchical_summaries:

                r = rouge.score(
                    summary,
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

            for summary in hierarchical_summaries:

                similarity = cosine_similarity(
                    [cos_reference.vector],
                    [nlp(summary).vector]
                )[0][0]

                cos_sim.append(similarity)

            overall_scores = [

                0.5 * cos_sim[i]
                + 0.2 * scores['rouge1'][i].fmeasure
                + 0.2 * scores['rouge2'][i].fmeasure
                + 0.2 * scores['rougeL'][i].fmeasure

                for i in range(
                    len(hierarchical_summaries)
                )
            ]

            hierarchical_summary = (
                hierarchical_summaries[
                    overall_scores.index(
                        max(overall_scores)
                    )
                ]
            )

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