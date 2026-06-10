import pathlib
import sys
import types

# Make the repo root importable regardless of where pytest is invoked from.
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# context.py runs spacy.load('en_core_web_md') at import time (multi-second
# load, requires the model installed). nlp is only used inside context_update,
# which these tests never call, so import context against a fake spacy module
# and restore the real one afterwards.
if 'context' not in sys.modules:
    _real_spacy = sys.modules.get('spacy')
    _fake_spacy = types.ModuleType('spacy')
    _fake_spacy.load = lambda *args, **kwargs: None
    sys.modules['spacy'] = _fake_spacy
    try:
        import context  # noqa: F401  (binds context.nlp = None)
    finally:
        if _real_spacy is not None:
            sys.modules['spacy'] = _real_spacy
        else:
            del sys.modules['spacy']
