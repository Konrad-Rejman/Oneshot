'''Loose contract for model.py:_build_prompt_from_memory.

Deliberately avoids asserting the exact framing (role casing, separators):
ROADMAP Phase 3 fine-tuning may change the prompt format. What must hold is
that every message's content reaches the model, in order.
'''
from model import _build_prompt_from_memory


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
