import os

import pytest
from cryptography.exceptions import InvalidTag

from app.core.encryption import decrypt_field, encrypt_field, make_fernet


class TestFieldEncryption:
    def test_round_trip(self):
        key = os.urandom(32).hex()
        plaintext = "ACC-1234567890"
        assert decrypt_field(encrypt_field(plaintext, key), key) == plaintext

    def test_different_ciphertexts_same_plaintext(self):
        """Each encrypt call uses a fresh nonce — ciphertexts must not be identical."""
        key = os.urandom(32).hex()
        ct1 = encrypt_field("value", key)
        ct2 = encrypt_field("value", key)
        assert ct1 != ct2

    def test_wrong_key_raises(self):
        key1 = os.urandom(32).hex()
        key2 = os.urandom(32).hex()
        ct = encrypt_field("secret", key1)
        with pytest.raises(InvalidTag):
            decrypt_field(ct, key2)

    def test_tampered_ciphertext_raises(self):
        key = os.urandom(32).hex()
        ct = encrypt_field("secret", key)
        tampered = ct[:-2] + ("00" if ct[-2:] != "00" else "ff")
        with pytest.raises(InvalidTag):
            decrypt_field(tampered, key)

    def test_unicode_round_trip(self):
        key = os.urandom(32).hex()
        plaintext = "café — account nº 42"
        assert decrypt_field(encrypt_field(plaintext, key), key) == plaintext


class TestFernet:
    def test_round_trip(self):
        key = os.urandom(32).hex()
        fernet = make_fernet(key)
        token = "oauth-token-value-here"
        encrypted = fernet.encrypt(token.encode())
        assert fernet.decrypt(encrypted).decode() == token

    def test_same_key_hex_produces_consistent_fernet(self):
        key = os.urandom(32).hex()
        f1 = make_fernet(key)
        f2 = make_fernet(key)
        ct = f1.encrypt(b"test")
        assert f2.decrypt(ct) == b"test"

    def test_different_key_cannot_decrypt(self):
        from cryptography.fernet import InvalidToken

        key1 = os.urandom(32).hex()
        key2 = os.urandom(32).hex()
        f1 = make_fernet(key1)
        f2 = make_fernet(key2)
        ct = f1.encrypt(b"secret")
        with pytest.raises(InvalidToken):
            f2.decrypt(ct)
