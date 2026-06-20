'''
Contracts for ownership.py: the visibility and edit/delete-permission rules
shared by the character and scenario stores.
'''
import ownership
from ownership import is_owner, entry_label, visible_records, migrate_records


def rec(name, owner):
    return {'name': name, 'owner': owner}


class TestIsOwner:
    def test_matching_owner(self):
        assert is_owner(rec('Hero', 'alice'), 'alice')

    def test_other_owner(self):
        assert not is_owner(rec('Hero', 'alice'), 'bob')

    def test_unowned_is_nobody(self):
        assert not is_owner(rec('Hero', ownership.UNOWNED), 'alice')


class TestEntryLabel:
    def test_tags_name_with_owner(self):
        assert entry_label(rec('Gandalf', 'alice')) == 'Gandalf (alice)'


class TestVisibleRecords:
    records = [rec('A', 'alice'), rec('B', 'bob'), rec('C', 'alice')]

    def test_own_only_hides_others_and_keeps_order(self):
        assert visible_records(self.records, 'alice', show_others=False) == [
            rec('A', 'alice'), rec('C', 'alice')
        ]

    def test_show_others_includes_everyone_in_order(self):
        assert visible_records(self.records, 'alice', show_others=True) == self.records

    def test_user_with_nothing_sees_empty_when_hidden(self):
        assert visible_records(self.records, 'carol', show_others=False) == []


class TestMigrateRecords:
    def test_claims_only_unowned_records(self):
        records = [rec('A', ownership.UNOWNED), rec('B', 'bob')]
        migrate_records(records, 'alice')
        assert records == [rec('A', 'alice'), rec('B', 'bob')]

    def test_returns_same_list_object(self):
        records = [rec('A', ownership.UNOWNED)]
        assert migrate_records(records, 'alice') is records
