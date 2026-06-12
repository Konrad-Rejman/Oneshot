import random

roll_num = 5 # Number of random rolls to pass to model

_ROLLS_PREAMBLE = '\n\nUse the following random D20 rolls for this interaction to resolve outcomes involving chance: '

def roll_values():
    # Generate the turn's random D20 pool; also shown colour-coded to the
    # player (ui.dice), so the values exist separately from the message text
    return [random.randint(1, 20) for _ in range(roll_num)]

def rolls_message(values):
    # Render roll values as the message appended to the system prompt
    return _ROLLS_PREAMBLE + ', '.join(str(v) for v in values)

def rolls():
    # Generate random rolls for model to use
    return rolls_message(roll_values()) # Return rolls message
