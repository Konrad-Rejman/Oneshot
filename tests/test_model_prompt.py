'''Loose contract for model.py:_build_prompt_from_memory, plus the
deterministic parts of the model toggle (ROADMAP 3): name matching against
the installed-model list and the active-model switch. installed_models()
itself queries Ollama and is deliberately untested.

Deliberately avoids asserting the exact framing (role casing, separators):
ROADMAP Phase 3 fine-tuning may change the prompt format. What must hold is
that every message's content reaches the model, in order.
'''
import model
from model import _build_prompt_from_memory, is_installed


def test_all_contents_present_in_order():
    memory = [
        {'role': 'system', 'content': 'the rules text'},
        {'role': 'user', 'content': 'the player action'},
        {'role': 'assistant', 'content': 'the gm response'},
    ]
    prompt = _build_prompt_from_memory(memory)
    positions = [prompt.find(m['content']) for m in memory]
    assert all(p >= 0 for p in positions)
    assert positions == sorted(positions)


def test_empty_memory_no_crash():
    assert _build_prompt_from_memory([]) == ''


def test_missing_keys_default_without_raising():
    prompt = _build_prompt_from_memory([{'content': 'no role here'}, {'role': 'user'}])
    assert 'no role here' in prompt


# --- model toggle (ROADMAP 3) ---

def test_is_installed_untagged_name_matches_any_tag():
    assert is_installed('oneshot-gm', ['mistral:instruct', 'oneshot-gm:latest'])
    assert is_installed('oneshot-gm', ['oneshot-gm'])


def test_is_installed_tagged_name_requires_exact_match():
    assert is_installed('mistral:instruct', ['mistral:instruct'])
    assert not is_installed('mistral:instruct', ['mistral:latest'])


def test_is_installed_absent_model_and_empty_list():
    assert not is_installed('oneshot-gm', ['mistral:instruct'])
    assert not is_installed('oneshot-gm', [])


def test_set_active_model_switches_and_restores():
    original = model.active_model()
    try:
        model.set_active_model(model.FINETUNED_MODEL_NAME)
        assert model.active_model() == model.FINETUNED_MODEL_NAME
        assert model.MODEL_NAME == model.FINETUNED_MODEL_NAME
    finally:
        model.set_active_model(original)
    assert model.active_model() == original


def test_default_active_model_is_base():
    assert model.BASE_MODEL_NAME == 'mistral:instruct'
    # The module must start sessions on the base model.
    assert model.active_model() == model.BASE_MODEL_NAME
