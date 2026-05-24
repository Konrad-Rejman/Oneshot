from rolls import rolls
from rouge_score import rouge_scorer
from sklearn.metrics.pairwise import cosine_similarity
import time, copy, spacy

nlp = spacy.load('en_core_web_md')

def context_update(chatlogs, context_logs, memory, rules, client, model, hierarchical_summary, tokens, save, backup, n=2):
    try:
        old_chatlogs = copy.deepcopy(chatlogs)
        old_context_logs = copy.deepcopy(context_logs)
        old_memory = copy.deepcopy(memory)
        old_tokens = copy.deepcopy(tokens)

        rouge = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)

        action = input('\nDescribe the players\' actions: ')
        chatlogs.append({'role': 'user',  'parts': [{'text': action}]}) # Add Player input to chat history

        # Generate random rolls for model to use
        rolls_message = rolls()
        # Add rules and other messages to memory
        if memory[0] == rules:
            memory = [rules, rolls_message, {'role': 'user', 'parts': [{'text': hierarchical_summary}]}] + memory[1:] + [{'role': 'user',  'parts': [{'text': action}]}] # Construct memory (rules, rolls, summary, last n interactions, user action)
        else:
            memory = [rules, rolls_message, {'role': 'user', 'parts': [{'text': hierarchical_summary}]}] + memory + [{'role': 'user',  'parts': [{'text': action}]}] # Construct memory (rules, rolls, summary, last n interactions, user action)
        
        # Get response from model
        try:
            response = client.models.generate_content(model=model, contents=memory)
        except KeyboardInterrupt:
            save()
            quit()
        except Exception as e:
            try:
                time.sleep(1.1)
                response = client.models.generate_content(model=model, contents=memory)
            except:
                try:
                    time.sleep(2.1)
                    response = client.models.generate_content(model=model, contents=memory)
                except:
                    try:
                        time.sleep(4.1)
                        response = client.models.generate_content(model=model, contents=memory)
                    except Exception as e:
                        print(e)
                        backup(old_chatlogs, old_context_logs, old_memory, old_tokens)
                        quit()

        # Save data
        context = [response.usage_metadata.prompt_token_count] + memory.copy()
        tokens += response.usage_metadata.prompt_token_count # Add tokens processed to token counter
        chatlogs.append({'role': 'model',  'parts': [{'text': response.text}]}) # Add GM response to chat history
        memory.append({'role': 'model',  'parts': [{'text': response.text}]}) # Add response to memory

        # Change memory to be ready for summary update
        memory.remove(rules) # Remove rules message
        memory.remove(rolls_message) # Remove rolls message from memory
        memory.remove({'role': 'user', 'parts': [{'text': hierarchical_summary}]}) # Remove summary message from memory

        # If memory is more than last n interactions (GM, Player) remove earliest interactions
        if len(memory) > 2*n:
            memory = memory[-2*n:] # memory = last n interactions

        # Construct reference to compare summaries against
        last_n_interactions = ''
        for prompt in memory:
            last_n_interactions += (prompt['parts'][0]['text'] + '\n\n')
        reference_summary = hierarchical_summary + '\n\nLAST INTERACTIONS:\n\n' + last_n_interactions

        # Update the summary based on most recent context, getting three potential updated summaries separated by a BREAK string
        instructions = [{'role': 'user', 'parts': [{'text':
            f'''TASK: Update the Summary to reflect recent interactions. 

            1. Do not remove the current headings (OVERALL STORY, CURRENT QUEST, PLAYER STATUS) or change the structure. 
            2. Give exactly THREE alternative updated summaries. 
            3. Separate the summaries by a line containing only: BREAK. 
            4. Do not add any text before the first summary or after the last summary.

            This is the old summary: {hierarchical_summary}
            These are the last interactions: {last_n_interactions}
            '''
            }]
        }]
        try:
            time.sleep(5.1)
            hierarchical_summaries = client.models.generate_content(model=model, contents=instructions)
        except KeyboardInterrupt:
            save()
            quit()
        except Exception as e:
            try:
                time.sleep(1.1)
                hierarchical_summaries = client.models.generate_content(model=model, contents=instructions)
            except:
                try:
                    time.sleep(2.1)
                    hierarchical_summaries = client.models.generate_content(model=model, contents=instructions)
                except:
                    try:
                        time.sleep(4.1)
                        hierarchical_summaries = client.models.generate_content(model=model, contents=instructions)
                    except Exception as e:
                        print(e)
                        backup(old_chatlogs, old_context_logs, old_memory, old_tokens)
                        quit()
        context[0] += hierarchical_summaries.usage_metadata.prompt_token_count
        tokens += hierarchical_summaries.usage_metadata.prompt_token_count # Add tokens processed to token counter
        hierarchical_summaries = hierarchical_summaries.text

        # If summaries created correctly, else continue using old summary
        if hierarchical_summaries != None:
            hierarchical_summaries = hierarchical_summaries.split('BREAK')

            # Scores dict for storing Rouge scores
            scores = {
                'rouge1': [],
                'rouge2': [],
                'rougeL': []
            }

            # Get Rouge to score each summary
            for i in range(len(hierarchical_summaries)):
                r = rouge.score(hierarchical_summaries[i], reference_summary)
                # Add score values to scores list
                for x in r:
                    scores[x].append(r[x])

            # Store cosine similarities
            cos_sim = []
            cos_reference = nlp(reference_summary)

            for i in range(len(hierarchical_summaries)):
                eval_summary = nlp(hierarchical_summaries[i])
                similarity = cosine_similarity([cos_reference.vector], [eval_summary.vector])[0][0] # Cosine Similarity of summary with refrence summary
                cos_sim.append(similarity)

            # Combine all scores, weighted towards Cosine Similarity for abstractive meaning
            overall_scores = [
                0.5 * cos_sim[i] + 0.2 * scores['rouge1'][i].fmeasure + 0.2 * scores['rouge2'][i].fmeasure + 0.2 * scores['rougeL'][i].fmeasure for i in range(len(hierarchical_summaries))
            ]

            # Select best summary
            best = 0
            if len(overall_scores) > 1:
                for i in range(len(overall_scores)):
                    if overall_scores[i] > overall_scores[best]:
                        best = i
            hierarchical_summary = hierarchical_summaries[best]

        print('\nGM:\n\n' + response.text)
    
        # Save context
        context_logs.append(context)

    except KeyboardInterrupt:
        save() # Save session data
        quit() # End program

    except Exception as e:
        print(e)
        backup(old_chatlogs, old_context_logs, old_memory, old_tokens)
        quit()

    return tokens, memory, hierarchical_summary