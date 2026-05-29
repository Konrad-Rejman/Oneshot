import requests
import json

OLLAMA_API = "http://localhost:11434/api/generate"
MODEL_NAME = "mistral:instruct"

def _build_prompt_from_memory(memory):
    parts = []
    for item in memory:
        role = item.get('role', 'user')
        content = item.get('content', '')
        parts.append(f"{role.upper()}:\n{content}\n\n")
    return ''.join(parts)

def generate_response(memory, stream=False):
    '''
    Get a response from local Ollama server and return the full text. Stream as GM output if stream variable is set to True.

    Args:
        memory: list of messages (dicts with 'role' and 'content') or a prompt object
        stream: if True, print tokens to stdout as they arrive. Defaults to False.

    Returns (response_text, prompt_token_estimate)
    '''
    prompt_text = _build_prompt_from_memory(memory)

    payload = {
        'model': MODEL_NAME,
        'prompt': prompt_text,
        'stream': True
    }

    try:
        resp = requests.post(OLLAMA_API, json=payload, stream=True, timeout=60)
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Ollama server: {e}")

    if resp.status_code != 200:
        raise RuntimeError(f"Ollama returned status {resp.status_code}: {resp.text}")

    response_text = ''
    first_chunk = True

    # Stream output as GM
    if stream:
        print("\nGM:\n\n", end='', flush=True)

    for raw_line in resp.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue

        # Normalize to str whether raw_line is bytes or str
        if isinstance(raw_line, bytes):
            line = raw_line.decode('utf-8', errors='ignore').strip()
        else:
            line = raw_line.strip()

        if not line:
            continue

        # Some servers prefix SSE data with 'data: '
        prefix = 'data: '
        if line.startswith(prefix):
            data = line[len(prefix):]
        else:
            data = line

        if data == '[DONE]':
            break

        prompt_eval_count = 0
        try:
            obj = json.loads(data)
            if isinstance(obj, dict) and obj.get('done'):
                prompt_eval_count = obj.get('prompt_eval_count', 0)
        except Exception:
            # Not JSON - treat as raw text chunk
            chunk = data
            print(chunk, end='', flush=True)
            response_text += chunk
            continue

        # Attempt to extract text from several known shapes
        chunk = ''
        if isinstance(obj, dict):
            # Common Ollama fields
            if 'response' in obj and isinstance(obj['response'], str):
                chunk = obj['response']
            elif 'token' in obj and isinstance(obj['token'], str):
                chunk = obj['token']
            elif 'text' in obj and isinstance(obj['text'], str):
                chunk = obj['text']
            elif 'choices' in obj and isinstance(obj['choices'], list):
                # Pull incremental content from choices
                for choice in obj['choices']:
                    if isinstance(choice, dict):
                        if 'delta' in choice and isinstance(choice['delta'], dict):
                            delta = choice['delta']
                            chunk = delta.get('content') or delta.get('text') or chunk
                        chunk = choice.get('text') or chunk

        if chunk:
            if first_chunk:
                chunk = chunk.lstrip()
                first_chunk = False
            if chunk:
                if stream:
                    print(chunk, end='', flush=True)
                response_text += chunk

    if stream:
        print('\n', end='', flush=True)

    # Return response + prompt token count
    return response_text.strip(), prompt_eval_count