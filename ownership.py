'''
Per-user ownership of the shared character and scenario stores.

Characters and scenarios are visible to everyone but tagged with the username
that created them, and only that owner may edit or delete them. These pure
helpers carry that rule; character.py and scenarios.py store records as
{'name', 'owner', ...payload} lists and lean on them, and ui.py renders the
labels. Saved stories use a different mechanism (per-user directories in
saves.py), so they are not handled here.
'''

# Owner stamped on records that predate the ownership system, claimed by the
# first user to run (character.migrate_characters / scenarios.migrate_scenarios).
UNOWNED = None

def is_owner(record, user):
    '''True if user created record, i.e. may edit or delete it.'''
    return record.get('owner') == user

def entry_label(record):
    '''Menu label tagging a record with its creator, e.g. "Gandalf (alice)".'''
    return f"{record['name']} ({record['owner']})"

def visible_records(records, user, show_others):
    '''
    Records to list in a picker, in their stored order: always the user's own,
    plus every other user's only when show_others is set.
    '''
    return [r for r in records if show_others or is_owner(r, user)]

def migrate_records(records, user):
    '''
    Stamp user onto every record left UNOWNED by the pre-ownership format,
    in place; returns records. A no-op once all records have an owner.
    '''
    for record in records:
        if record.get('owner') is UNOWNED:
            record['owner'] = user
    return records
