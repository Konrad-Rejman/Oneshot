'''
User accounts: a global registry of login credentials and the persistent
per-user default GM model.

accounts.json (project root, beside characters.json / scenarios.json) is a flat
list of account records:

    {'username': str, 'password_hash': str, 'default_model': str|None}

Passwords are never stored in the clear - only an sha512 hex digest is kept, and
authenticate compares digests. The registry is global (one file, all users),
unlike per-user saves/ which stay the privacy boundary for stories.

The seeded u00 account (password "admin") owns the pre-account characters,
scenarios and saves, so that data stays reachable. Other pre-account owners
reclaim their data by creating an account under their old username, the same
"first to claim" spirit as the migrate_* helpers elsewhere.
'''
import hashlib
import json
import os

ACCOUNTS_FILE = 'accounts.json'

# The pre-account data owner; seeded with this password so existing
# characters/scenarios/saves stay reachable.
SEED_USERNAME = 'u00'
SEED_PASSWORD = 'admin'

def hash_password(password):
    '''sha512 hex digest of password; the only form stored on disk.'''
    return hashlib.sha512(password.encode('utf-8')).hexdigest()

def _load_accounts():
    '''All account records, or [] when the registry file is absent.'''
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _save_accounts(records):
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

def _find(records, username):
    return next((r for r in records if r['username'] == username), None)

def user_exists(username):
    return _find(_load_accounts(), username) is not None

def create_account(username, password):
    '''
    Register a new account with default_model unset and return its record, or
    None if the username is blank or already taken.
    '''
    username = username.strip()
    if not username:
        return None
    records = _load_accounts()
    if _find(records, username) is not None:
        return None
    record = {
        'username': username,
        'password_hash': hash_password(password),
        'default_model': None,
    }
    records.append(record)
    _save_accounts(records)
    return record

def authenticate(username, password):
    '''True when username exists and password matches its stored hash.'''
    record = _find(_load_accounts(), username)
    return record is not None and record['password_hash'] == hash_password(password)

def get_default_model(username):
    '''The user's persisted default GM model, or None if never set.'''
    record = _find(_load_accounts(), username)
    return record.get('default_model') if record else None

def set_default_model(username, model):
    '''Persist the user's default GM model immediately.'''
    records = _load_accounts()
    record = _find(records, username)
    if record is None:
        return
    record['default_model'] = model
    _save_accounts(records)

def ensure_seed():
    '''
    Create the registry with the seeded u00/admin account on first run.
    A no-op once accounts.json exists, so it never overwrites real accounts.
    '''
    if os.path.exists(ACCOUNTS_FILE):
        return
    _save_accounts([{
        'username': SEED_USERNAME,
        'password_hash': hash_password(SEED_PASSWORD),
        'default_model': None,
    }])
