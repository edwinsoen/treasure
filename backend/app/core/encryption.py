from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def make_fernet(key_hex: str) -> Fernet:
    """Return a Fernet instance derived from the 32-byte hex key.

    Used for OAuth token encryption — Fernet handles nonce and MAC internally.
    """
    fernet_key = base64.urlsafe_b64encode(bytes.fromhex(key_hex))
    return Fernet(fernet_key)


def encrypt_field(value: str, key_hex: str) -> str:
    """AES-256-GCM encrypt a string field for storage.

    Returns a hex string of the form: nonce(12 bytes) + ciphertext + tag(16 bytes).
    """
    aesgcm = AESGCM(bytes.fromhex(key_hex))
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, value.encode(), None)
    return (nonce + ciphertext).hex()


def decrypt_field(encoded: str, key_hex: str) -> str:
    """Decrypt a value produced by *encrypt_field*."""
    aesgcm = AESGCM(bytes.fromhex(key_hex))
    raw = bytes.fromhex(encoded)
    nonce, ciphertext = raw[:12], raw[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
