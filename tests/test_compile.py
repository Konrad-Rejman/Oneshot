'''Layer 1: every top-level source file must at least compile.

Uses py_compile (no import), so main.py's interactive top-level code never runs.
The top-level glob naturally excludes .venv312, __pycache__ and tests/.
'''
import pathlib
import py_compile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = sorted(ROOT.glob('*.py'))


def test_sources_found():
    names = {path.name for path in SOURCES}
    assert {'main.py', 'context.py', 'model.py', 'rolls.py', 'scenarios.py'} <= names


@pytest.mark.parametrize('source', SOURCES, ids=lambda p: p.name)
def test_compiles(source):
    py_compile.compile(str(source), doraise=True)
