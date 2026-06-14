'''
Deterministic logic in ui.py (ROADMAP 2.4): the pure style helpers, plus
capture-based checks that the dice line and status bar render the right
values. Pure rendering aesthetics (colours on the wire, box characters) are
deliberately not asserted on - only that the data the player needs is there.
'''
import re

import ui
from character import Character
from progression import Progression


def _character(name='Hero'):
    return Character(
        name=name, race='Elf', char_class='Ranger', background='A scout.',
        stats={'Strength': 6, 'Dexterity': 6, 'Constitution': 6,
               'Intelligence': 6, 'Wisdom': 6, 'Charisma': 6},
    )


# --- roll_style: one colour per consequence tier, naturals emphasised ---

def test_roll_style_natural_one_is_emphasised():
    assert ui.roll_style(1) == 'bold red'


def test_roll_style_critical_failure_tier():
    assert ui.roll_style(2) == ui.roll_style(5) == 'red'


def test_roll_style_partial_failure_tier():
    assert ui.roll_style(6) == ui.roll_style(10) == 'yellow'


def test_roll_style_partial_success_tier():
    assert ui.roll_style(11) == ui.roll_style(15) == 'cyan'


def test_roll_style_full_success_tier():
    assert ui.roll_style(16) == ui.roll_style(19) == 'green'


def test_roll_style_natural_twenty_is_emphasised():
    assert ui.roll_style(20) == 'bold bright_green'


# --- hp_style: green above 2/3, yellow above 1/3, red at or below 1/3 ---

def test_hp_style_full_and_above_two_thirds_is_green():
    assert ui.hp_style(10, 10) == 'green'
    assert ui.hp_style(7, 10) == 'green'


def test_hp_style_exactly_two_thirds_is_yellow():
    assert ui.hp_style(2, 3) == 'yellow'


def test_hp_style_middle_band_is_yellow():
    assert ui.hp_style(6, 10) == 'yellow'
    assert ui.hp_style(4, 10) == 'yellow'


def test_hp_style_exactly_one_third_is_red():
    assert ui.hp_style(1, 3) == 'red'


def test_hp_style_low_and_zero_is_red():
    assert ui.hp_style(3, 10) == 'red'
    assert ui.hp_style(0, 10) == 'red'


# --- rendering: the values the player needs appear, in order ---

def test_dice_renders_all_values_in_order():
    with ui.console.capture() as capture:
        ui.dice([1, 7, 13, 19, 20])
    assert re.search(r'\b1\b\D+\b7\b\D+\b13\b\D+\b19\b\D+\b20\b', capture.get())


def test_status_bar_shows_name_hp_level_xp_and_tokens():
    progression = Progression(max_hp=12, hp=5, level=3, xp=240)
    with ui.console.capture() as capture:
        ui.status_bar(_character('Hero'), progression, 1234)
    out = capture.get()
    assert 'Hero' in out
    assert '5/12' in out
    assert 'Level' in out and '3' in out
    assert 'XP' in out and '240' in out
    assert 'Tokens' in out and '1234' in out


def test_status_bar_shows_model_when_given_and_omits_when_not():
    progression = Progression(max_hp=12, hp=12, level=1, xp=0)
    with ui.console.capture() as capture:
        ui.status_bar(_character(), progression, 0, 'gm-istral')
    assert 'gm-istral' in capture.get()
    with ui.console.capture() as capture:
        ui.status_bar(_character(), progression, 0)
    assert 'Model' not in capture.get()
