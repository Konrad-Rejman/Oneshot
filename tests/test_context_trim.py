'''Behavior contracts for the token-budget logic in context.py.

These protect the memory-trimming guarantees described in CLAUDE.md: the
prompt never exceeds TOKEN_LIMIT, and rules / summary / the current action
are never trimmed away by the pre-send trim.
'''
from context import (
    ACTION_TOKEN_RESERVE,
    ROLLS_TOKEN_RESERVE,
    TOKEN_LIMIT,
    _estimate_tokens,
    _trim_presend,
    _trim_to_memory_budget,
)


def msg(tokens, label='m'):
    # 1 token == 4 chars under the len // 4 heuristic
    return {'role': 'user', 'content': label.ljust(tokens * 4, 'x')}


class TestEstimateTokens:
    def test_empty(self):
        assert _estimate_tokens([]) == 0

    def test_missing_content_key(self):
        assert _estimate_tokens([{'role': 'user'}]) == 0

    def test_four_chars_per_token(self):
        assert _estimate_tokens([{'role': 'user', 'content': 'x' * 8}]) == 2

    def test_floor_division_on_total(self):
        # 2 + 2 chars -> 4 // 4 == 1 token, not 0 + 0
        messages = [{'role': 'user', 'content': 'xx'},
                    {'role': 'user', 'content': 'xx'}]
        assert _estimate_tokens(messages) == 1


class TestTrimPresend:
    def test_under_limit_unchanged(self):
        memory = [msg(100, 'rules'), msg(100, 'summary'),
                  msg(100, 'old'), msg(100, 'action')]
        snapshot = [m['content'] for m in memory]
        _trim_presend(memory)
        assert [m['content'] for m in memory] == snapshot

    def test_drops_oldest_interactions_first(self):
        # 6 x 1000 tokens = 6000 > 4096; two oldest interactions must go.
        memory = [msg(1000, 'rules'), msg(1000, 'summary'),
                  msg(1000, 'old1'), msg(1000, 'old2'),
                  msg(1000, 'old3'), msg(1000, 'action')]
        _trim_presend(memory)
        labels = [m['content'].rstrip('x') for m in memory]
        assert labels == ['rules', 'summary', 'old3', 'action']
        assert _estimate_tokens(memory) <= TOKEN_LIMIT

    def test_three_messages_never_trimmed(self):
        # At length 3 the layout is [rules, summary, action]; pop(2) would
        # delete the current action, so the guard must leave it untouched
        # even when over the limit.
        memory = [msg(3000, 'rules'), msg(3000, 'summary'), msg(3000, 'action')]
        _trim_presend(memory)
        assert len(memory) == 3

    def test_terminates_when_framing_alone_exceeds_limit(self):
        # Everything between summary and action gets dropped, then the loop
        # stops at length 3 even though the prompt is still over the limit.
        memory = [msg(2000, 'rules'), msg(2000, 'summary'),
                  msg(10, 'old1'), msg(10, 'old2'), msg(5000, 'action')]
        _trim_presend(memory)
        labels = [m['content'].rstrip('x') for m in memory]
        assert labels == ['rules', 'summary', 'action']
        assert _estimate_tokens(memory) > TOKEN_LIMIT  # documented outcome


class TestTrimToMemoryBudget:
    def test_budget_math_drops_oldest_first(self):
        rules_content = 'r' * 400      # 100 tokens
        summary = 's' * 400            # 100 tokens
        budget = TOKEN_LIMIT - 100 - ROLLS_TOKEN_RESERVE - 100 - ACTION_TOKEN_RESERVE
        # Four 1000-token messages: 4000 > budget (3666); exactly one pop
        # brings it to 3000 <= budget.
        memory = [msg(1000, 'old1'), msg(1000, 'old2'),
                  msg(1000, 'old3'), msg(1000, 'old4')]
        _trim_to_memory_budget(memory, rules_content, summary)
        labels = [m['content'].rstrip('x') for m in memory]
        assert labels == ['old2', 'old3', 'old4']
        assert _estimate_tokens(memory) <= budget

    def test_noop_within_budget(self):
        memory = [msg(10, 'old1'), msg(10, 'old2')]
        _trim_to_memory_budget(memory, 'r' * 400, 's' * 400)
        assert len(memory) == 2

    def test_negative_budget_empties_memory(self):
        # Rules alone exceed TOKEN_LIMIT, so every message must go.
        memory = [msg(10, 'old1'), msg(10, 'old2')]
        _trim_to_memory_budget(memory, 'r' * (TOKEN_LIMIT * 4 + 400), 's' * 400)
        assert memory == []

    def test_empty_memory_no_crash(self):
        memory = []
        _trim_to_memory_budget(memory, 'r' * (TOKEN_LIMIT * 8), 's')
        assert memory == []
