import requests
import json
import ui

OLLAMA_API = "http://localhost:11434/api/generate"
OLLAMA_TAGS_API = "http://localhost:11434/api/tags"

# Model toggle (ROADMAP 3): the base model is always available; the
# fine-tuned model (training/, registered with `ollama create oneshot-gm`)
# is offered at startup when installed. MODEL_NAME is the active model used
# by generate_response - switch it only through set_active_model.
BASE_MODEL_NAME = "mistral:instruct"
FINETUNED_MODEL_NAME = "oneshot-gm"
MODEL_NAME = BASE_MODEL_NAME

def set_active_model(name):
    '''Switch the model generate_response uses for the rest of the session.'''
    global MODEL_NAME
    MODEL_NAME = name

def active_model():
    return MODEL_NAME

def installed_models():
    '''
    Model names installed in the local Ollama (empty list if the query
    fails - the game then keeps the base model).
    '''
    try:
        resp = requests.get(OLLAMA_TAGS_API, timeout=5)
        return [m.get('name', '') for m in resp.json().get('models', [])]
    except Exception:
        return []

def is_installed(name, installed):
    '''
    True if name matches an installed model exactly, or matches one ignoring
    its tag: "oneshot-gm" matches "oneshot-gm:latest". A name that carries
    its own tag ("mistral:instruct") must match exactly.
    '''
    if ':' in name:
        return name in installed
    return any(entry == name or entry.split(':', 1)[0] == name for entry in installed)

def choose_model():
    '''
    Startup model toggle: when the fine-tuned model is installed in Ollama,
    ask which model runs the GM this session (blank defaults to base, so
    evaluation sessions are an explicit choice); when it is not installed,
    keep the base model without showing a menu. Returns the active model.
    '''
    if not is_installed(FINETUNED_MODEL_NAME, installed_models()):
        set_active_model(BASE_MODEL_NAME)
        return MODEL_NAME
    ui.menu('Choose the Game Master model for this session:', [
        f'{BASE_MODEL_NAME} (base)',
        f'{FINETUNED_MODEL_NAME} (fine-tuned)',
    ])
    while True:
        choice = ui.ask('Model (blank for base):').strip()
        if choice in ('', '1'):
            set_active_model(BASE_MODEL_NAME)
            break
        if choice == '2':
            set_active_model(FINETUNED_MODEL_NAME)
            break
        ui.warn('Please enter 1, 2, or leave blank for the base model.')
    ui.system(f'Game Master model: {MODEL_NAME}')
    return MODEL_NAME

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
        ui.gm_header()

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
            if stream:
                ui.gm_chunk(chunk)
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
                    ui.gm_chunk(chunk)
                response_text += chunk

    if stream:
        ui.gm_end()

    # Return response + prompt token count
    return response_text.strip(), prompt_eval_count