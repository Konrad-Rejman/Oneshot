'''Contract for rolls.py: five D20 values, reproducible under seeding.

The numbers are parsed from after the colon — the preamble itself contains
a digit ("D20") that must not be counted.
'''
import random
import re

from rolls import rolls


def parse_rolls(message):
    return [int(n) for n in re.findall(r'\d+', message.split(':')[-1])]


def test_five_rolls_in_d20_range():
    random.seed(1234)
    values = parse_rolls(rolls())
    assert len(values) == 5
    assert all(1 <= v <= 20 for v in values)


def test_same_seed_reproduces_message():
    random.seed(99)
    first = rolls()
    random.seed(99)
    second = rolls()
    assert first == second


def test_full_range_reachable():
    # Over many seeded draws both extremes should appear.
    random.seed(7)
    seen = set()
    for _ in range(200):
        seen.update(parse_rolls(rolls()))
    assert {1, 20} <= seen
