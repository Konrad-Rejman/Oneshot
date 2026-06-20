'''
Terminal presentation layer (ROADMAP 2.4), built on rich.

Every print/input in the game goes through this module: GM narrative scrolls
above, and each turn ends with a status-bar panel (character name, HP, level,
XP, token count) rendered directly above the pinned input line. GM speech,
system messages, game events (level-ups, death), warnings/errors and the
colour-coded D20 pool each have a distinct style, defined once below.

Centralising terminal I/O here keeps the path open for a future full-screen
TUI (textual): only these functions would need reimplementing - the game
logic never touches print()/input() directly.

The style helpers roll_style and hp_style are pure functions (tested in
tests/test_ui.py); everything else is thin rich rendering. Arbitrary game
text is always wrapped in Text() or printed with markup=False so model
output and exception messages containing brackets are never parsed as
rich markup.
'''
import sys

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

try:
    import msvcrt  # Windows-only raw key reads, for the interactive select menu
except ImportError:
    msvcrt = None

console = Console(highlight=False)

# One style per kind of output, so the game's look is defined in one place.
SYSTEM_STYLE = 'dim'           # instructions, menus' help lines, confirmations
EVENT_STYLE = 'bold magenta'   # game events: level-ups, death, resurrection
WARN_STYLE = 'yellow'          # recoverable problems, input corrections
ERROR_STYLE = 'bold red'       # failures
PROMPT_STYLE = 'bold green'    # the input line
HEADING_STYLE = 'bold cyan'    # menu titles and the GM rule label
GM_RULE_STYLE = 'cyan'         # GM separator rule and status-bar border

def roll_style(value):
    '''
    Style for a D20 value, one colour per consequence tier of the rules
    prompt: 1-5 critical failure (red), 6-10 partial failure (yellow),
    11-15 partial success (cyan), 16-20 full success (green), with the
    naturals emphasised (bold red 1, bold bright green 20).
    '''
    if value == 1:
        return 'bold red'
    if value <= 5:
        return 'red'
    if value <= 10:
        return 'yellow'
    if value <= 15:
        return 'cyan'
    if value == 20:
        return 'bold bright_green'
    return 'green'

def hp_style(hp, max_hp):
    '''
    Style for the HP readout: green above two thirds of max, yellow above
    one third, red at or below one third (integer arithmetic, no rounding).
    '''
    if hp * 3 > max_hp * 2:
        return 'green'
    if hp * 3 > max_hp:
        return 'yellow'
    return 'red'

def system(message):
    '''Dim system/instruction message.'''
    console.print(Text(str(message), style=SYSTEM_STYLE))

def event(message):
    '''Game event the player should not miss: level-up, death, resurrection.'''
    console.print(Text(str(message), style=EVENT_STYLE))

def warn(message):
    console.print(Text(str(message), style=WARN_STYLE))

def error(message):
    console.print(Text(str(message), style=ERROR_STYLE))

def heading(message):
    console.print()
    console.print(Text(str(message), style=HEADING_STYLE))

def menu(title, entries):
    '''Numbered menu: styled title, then "  1. entry" lines.'''
    heading(title)
    for i, entry in enumerate(entries, start=1):
        line = Text(f'  {i}. ', style=SYSTEM_STYLE)
        line.append(str(entry))
        console.print(line)

def _interactive_keys():
    '''
    True when arrow-key selection is possible: msvcrt is present (Windows) and
    both ends of the terminal are a real tty. Otherwise select() falls back to
    a numbered prompt, keeping headless and non-Windows runs working.
    '''
    return msvcrt is not None and sys.stdin.isatty() and sys.stdout.isatty()

def _render_select(title, options, index, help_text):
    body = Text()
    body.append(str(title), style=HEADING_STYLE)
    for i, (label, _) in enumerate(options):
        body.append('\n')
        if i == index:
            body.append('> ', style=PROMPT_STYLE)
            body.append(str(label), style=PROMPT_STYLE)
        else:
            body.append('  ', style=SYSTEM_STYLE)
            body.append(str(label))
    if help_text:
        body.append('\n\n')
        body.append(str(help_text), style=SYSTEM_STYLE)
    return body

def _select_fallback(title, options):
    '''Numbered-menu equivalent of select() for non-interactive terminals.'''
    menu(title, [label for label, _ in options])
    while True:
        raw = ask('Enter a number:').strip()
        try:
            return options[int(raw) - 1][1]
        except (ValueError, IndexError):
            warn('Please enter a listed number.')

def select(title, options, help_text='Use the arrow keys to move, Enter to choose.'):
    '''
    Arrow-key menu: render options with a cursor and return the chosen option's
    value. options is a list of (label, value) pairs. Up/Down move (wrapping),
    Enter chooses; Ctrl+C propagates as KeyboardInterrupt so the game's
    save/exit flow is unaffected. Falls back to a numbered prompt when the
    terminal can't be read raw (_interactive_keys).
    '''
    if not options:
        return None
    if not _interactive_keys():
        return _select_fallback(title, options)

    index = 0
    with Live(_render_select(title, options, index, help_text),
              console=console, auto_refresh=False, transient=True) as live:
        while True:
            key = msvcrt.getwch()
            if key == '\x03':  # Ctrl+C: preserve the input()/KeyboardInterrupt contract
                raise KeyboardInterrupt
            if key in ('\x00', '\xe0'):  # arrow keys arrive as a two-char sequence
                arrow = msvcrt.getwch()
                if arrow == 'H':
                    index = (index - 1) % len(options)
                elif arrow == 'P':
                    index = (index + 1) % len(options)
            elif key in ('\r', '\n'):
                return options[index][1]
            live.update(_render_select(title, options, index, help_text), refresh=True)

def ask(prompt=''):
    '''
    Styled input line; the labelled replacement for input(). A blank prompt
    shows a bare "> ". KeyboardInterrupt propagates, so Ctrl+C save/exit
    flows behave exactly as they did with input().
    '''
    label = f'{prompt} ' if prompt else '> '
    return console.input(Text(label, style=PROMPT_STYLE))

def read_line():
    '''Unstyled line read, for multi-line text entry (scenario editing).'''
    return console.input()

def gm_header():
    '''Separator rule announcing new turn.'''
    console.print()
    console.print(Rule(Text('', style=HEADING_STYLE), style=GM_RULE_STYLE, align='left'))
    console.print()

def gm_chunk(text):
    '''One streamed chunk of GM narration; the terminal handles wrapping.'''
    console.print(text, end='', soft_wrap=True, markup=False)

def gm_end():
    '''Finish a streamed GM message.'''
    console.print()

def gm_message(text):
    '''A complete (non-streamed) GM message: opening scenes, resumed stories.'''
    gm_header()
    console.print(Text(str(text)))

def dice(values):
    '''The turn's pre-rolled D20 pool, colour-coded by consequence tier.'''
    line = Text('Rolls  ', style=SYSTEM_STYLE)
    for i, value in enumerate(values):
        if i:
            line.append('  ')
        line.append(str(value), style=roll_style(value))
    console.print(line)

def status_bar(character, progression, tokens, model_name=None):
    '''
    Status panel rendered above each turn's input line: character name as
    the title, HP (colour-coded), level, XP, cumulative token count and -
    when given - the active GM model, so evaluation sessions comparing the
    base and fine-tuned models (ROADMAP 3) are always identifiable.
    '''
    bar = Text()
    bar.append('HP ', style=SYSTEM_STYLE)
    bar.append(f'{progression.hp}/{progression.max_hp}',
               style=hp_style(progression.hp, progression.max_hp))
    bar.append('   ')
    bar.append('Level ', style=SYSTEM_STYLE)
    bar.append(str(progression.level))
    bar.append('   ')
    bar.append('XP ', style=SYSTEM_STYLE)
    bar.append(str(progression.xp))
    bar.append('   ')
    bar.append('Tokens ', style=SYSTEM_STYLE)
    bar.append(str(tokens))
    if model_name:
        bar.append('   ')
        bar.append('Model ', style=SYSTEM_STYLE)
        bar.append(str(model_name))
    console.print()
    console.print(Panel(bar, title=Text(character.name, style='bold'),
                        title_align='left', border_style=GM_RULE_STYLE,
                        expand=False))
