'''Contract for rolls.py: five D20 values, reproducible under seeding.

The numbers are parsed from after the colon — the preamble itself contains
a digit ("D20") that must not be counted. ROADMAP 2.4 split the generation
(roll_values) from the message rendering (rolls_message) so the UI can show
the same values colour-coded; rolls() must stay equivalent to composing the
two.
'''
import random
import re

from rolls import roll_num, roll_values, rolls, rolls_message


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


def test_roll_values_contract():
    random.seed(5)
    values = roll_values()
    assert len(values) == roll_num == 5
    assert all(1 <= v <= 20 for v in values)


def test_rolls_message_round_trips_values():
    values = [1, 5, 10, 15, 20]
    assert parse_rolls(rolls_message(values)) == values


def test_rolls_equals_message_of_values():
    # rolls() must consume the RNG exactly like roll_values(), so the same
    # seed produces the same message either way.
    random.seed(42)
    expected = rolls()
    random.seed(42)
    assert rolls_message(roll_values()) == expected
