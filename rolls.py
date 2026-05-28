import random

def rolls():
    # Generate random rolls for model to use
    rolls = '\n\nUse the following random D20 rolls for this interaction to resolve outcomes involving chance: '
    roll_num = 5 # Number of random rolls to pass to model
    for i in range(roll_num - 1): 
        r = random.randint(1, 20)
        rolls = rolls + str(r)
        rolls = rolls + ', '
    r = random.randint(1, 20)
    rolls = rolls + str(r)

    return rolls # Return rolls message