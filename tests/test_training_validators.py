'''
Validators gating the Phase 3 training data (training/validators.py).

These are the quality filters whose behaviour the fine-tune bakes in, so
they are tested like the game's other deterministic logic: pure string
checks, no model calls.
'''
from training import validators as v


GOOD_RESPONSE = (
    'You press against the cold wall and edge forward. Roll a Dexterity '
    'check... you roll a 14... your boots find the silent gaps between the '
    'rubble and the guard never turns. Beyond him the corridor opens onto '
    'the vault door you have been seeking.\n'
    'STATE: XP +20'
)
POOL = [14, 3, 19, 7, 11]


# --- find_announced_rolls / check_dice ---

def test_announced_rolls_found_in_order():
    text = 'you roll a 14... later you roll a 3 and stumble'
    assert v.find_announced_rolls(text) == [14, 3]


def test_announcement_without_number_in_same_sentence_not_paired():
    # The window stops at sentence punctuation, so the 9 in the next
    # sentence is not paired with the first "Roll".
    assert v.find_announced_rolls('Roll a Wisdom check. The 9 guards wait.') == []


def test_dice_pool_prefix_accepted():
    assert v.check_dice('you roll a 14', POOL) == []
    assert v.check_dice('you roll a 14, then you roll a 3', POOL) == []


def test_dice_wrong_value_rejected():
    assert v.check_dice('you roll a 17', POOL)


def test_dice_out_of_order_rejected():
    assert v.check_dice('you roll a 3, then you roll a 14', POOL)


def test_dice_missing_check_rejected_only_when_required():
    assert v.check_dice('no rolls here', POOL, require_check=True)
    assert v.check_dice('no rolls here', POOL, require_check=False) == []


def test_dice_more_announcements_than_pool_rejected():
    text = ', '.join(f'you roll a {n}' for n in [14, 3, 19, 7, 11, 2])
    assert v.check_dice(text, POOL)


# --- check_state_line: strict canonical grammar ---

def test_state_line_canonical_entries_accepted():
    text = 'You win.\nSTATE: HP -3; XP +25; GAIN torch; LOSE rope; SLOT 1 -1'
    assert v.check_state_line(text) == []


def test_state_line_none_accepted():
    assert v.check_state_line('You wait.\nSTATE: none') == []


def test_state_line_missing_rejected():
    assert v.check_state_line('You wait quietly.') == ['missing STATE line']


def test_state_line_not_last_rejected():
    assert v.check_state_line('STATE: none\nYou wait.')


def test_state_line_duplicated_rejected():
    assert v.check_state_line('STATE: none\nYou wait.\nSTATE: none')


def test_state_line_markdown_decoration_rejected():
    # The runtime parser tolerates this; training data must not contain it.
    assert v.check_state_line('You win.\n**STATE**: HP -3')


def test_state_line_malformed_entries_rejected():
    assert v.check_state_line('You win.\nSTATE: HP minus three')
    assert v.check_state_line('You win.\nSTATE: XP -10')  # XP only goes up
    assert v.check_state_line('You win.\nSTATE: SLOT 0 -1')


# --- plain text / meta / person / length ---

def test_plain_text_bans_markdown_and_brackets():
    assert v.check_plain_text('plain prose only') == []
    assert v.check_plain_text('some *emphasis*')
    assert v.check_plain_text('# heading')
    assert v.check_plain_text('[INST] leak')
    assert v.check_plain_text('- a bullet line')
    assert v.check_plain_text('1. a numbered line')


def test_plain_text_allows_state_line_minus_sign():
    assert v.check_plain_text('STATE: HP -3; XP +25') == []


def test_no_meta_bans_character_breaks():
    assert v.check_no_meta('As an AI language model I cannot')
    assert v.check_no_meta('The player should now decide')
    assert v.check_no_meta('You step into the hall.') == []


def test_no_meta_allows_npc_dialogue():
    assert v.check_no_meta('The guard sighs: I cannot help you, traveller.') == []


def test_second_person_required_near_start():
    assert v.check_second_person('You creep forward.') == []
    assert v.check_second_person('The cave is dark. ' * 30)


# --- composite gates ---

def test_good_gm_response_passes():
    assert v.validate_gm_response(GOOD_RESPONSE, POOL) == []


def test_gm_response_without_state_line_fails():
    text = GOOD_RESPONSE.rsplit('\n', 1)[0]
    assert v.validate_gm_response(text, POOL)


def test_gm_response_with_wrong_roll_fails():
    assert v.validate_gm_response(GOOD_RESPONSE.replace('14', '15'), POOL)


def test_scene_rejects_rolls_and_state_lines():
    assert v.validate_scene('You stand at the gate of the ruined keep, '
                            'its doors hanging open into darkness. Somewhere '
                            'below, water drips onto stone.') == []
    assert v.validate_scene('You stand at the gate. You roll a 12. ' + 'x' * 80)
    assert v.validate_scene('You stand at the gate of the ruined keep, '
                            'doors open.\nSTATE: none')


def test_action_requires_first_person_prose():
    assert v.validate_action('I try to pick the lock with my lockpicks.') == []
    assert v.validate_action('The rogue picks the lock carefully there.')
    assert v.validate_action('I roll a 15 to pick the lock immediately.')


def test_narration_accepts_plain_prose_without_mechanics():
    good = ('You wrench the iron handle and the door grinds open, but the '
            'hinges shriek loud enough to wake the whole corridor. Somewhere '
            'ahead, boots begin to move toward you.')
    assert v.validate_narration(good) == []


def test_narration_rejects_dice_talk():
    # The mechanics are added by the pipeline; narration must not mention them.
    base = ('You creep along the ledge and reach the far side safely, your '
            'heart pounding in the dark. ')
    assert v.validate_narration(base + 'You roll a 14 to keep your balance.')
    assert v.validate_narration(base + 'The dice favour you this time.')


def test_narration_rejects_state_line_and_meta():
    base = ('You steady your breath and the tremor in your hands fades as the '
            'ancient hall settles into silence around you once more. ')
    assert v.validate_narration(base + '\nSTATE: none')
    assert v.validate_narration('The player should now decide. ' + base)


def test_summary_requires_all_sections_in_order():
    good = ('OVERALL STORY: A quest unfolds.\n'
            'CURRENT QUEST: Find the relic.\n'
            'PLAYER STATUS: Healthy and equipped.')
    assert v.validate_summary(good) == []
    assert v.validate_summary('OVERALL STORY: A quest unfolds.')
    assert v.validate_summary(good.replace('CURRENT QUEST:', 'QUEST:'))
    assert v.validate_summary('PLAYER STATUS: Fine.\n'
                              'CURRENT QUEST: Find it.\n'
                              'OVERALL STORY: A tale.')
