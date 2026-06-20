'''
Contracts for accounts.py: password hashing, authentication, account creation
rules, the persistent per-user default model, and the seeded u00/admin account.
Deliberately avoids the interactive account/login menus.

Tests redirect ACCOUNTS_FILE into tmp_path so the real registry is never touched.
'''
import os

import pytest

import accounts


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, 'ACCOUNTS_FILE', str(tmp_path / 'accounts.json'))


class TestHashPassword:
    def test_is_sha512_hex_and_deterministic(self):
        h = accounts.hash_password('admin')
        assert h == accounts.hash_password('admin')
        assert len(h) == 128
        assert all(c in '0123456789abcdef' for c in h)

    def test_different_passwords_differ(self):
        assert accounts.hash_password('a') != accounts.hash_password('b')


class TestCreateAndAuthenticate:
    def test_create_then_authenticate(self):
        accounts.create_account('alice', 'pw')
        assert accounts.authenticate('alice', 'pw')

    def test_wrong_password_fails(self):
        accounts.create_account('alice', 'pw')
        assert not accounts.authenticate('alice', 'nope')

    def test_unknown_user_fails(self):
        assert not accounts.authenticate('ghost', 'pw')

    def test_rejects_blank_username(self):
        assert accounts.create_account('   ', 'pw') is None
        assert not accounts.user_exists('')

    def test_rejects_duplicate_username(self):
        accounts.create_account('alice', 'pw')
        assert accounts.create_account('alice', 'other') is None
        # The original password still works; the duplicate did not overwrite it.
        assert accounts.authenticate('alice', 'pw')

    def test_new_account_has_no_default_model(self):
        accounts.create_account('alice', 'pw')
        assert accounts.get_default_model('alice') is None

    def test_password_is_not_stored_in_clear(self):
        accounts.create_account('alice', 'secret')
        with open(accounts.ACCOUNTS_FILE, encoding='utf-8') as f:
            assert 'secret' not in f.read()


class TestDefaultModel:
    def test_round_trips_and_persists(self):
        accounts.create_account('alice', 'pw')
        accounts.set_default_model('alice', 'mistral:instruct')
        assert accounts.get_default_model('alice') == 'mistral:instruct'

    def test_set_for_unknown_user_is_noop(self):
        accounts.set_default_model('ghost', 'x')
        assert accounts.get_default_model('ghost') is None


class TestEnsureSeed:
    def test_creates_u00_admin(self):
        accounts.ensure_seed()
        assert accounts.user_exists('u00')
        assert accounts.authenticate('u00', 'admin')
        assert accounts.get_default_model('u00') is None

    def test_is_idempotent_and_does_not_overwrite(self):
        accounts.ensure_seed()
        accounts.set_default_model('u00', 'mistral:instruct')
        accounts.ensure_seed()
        assert accounts.get_default_model('u00') == 'mistral:instruct'
