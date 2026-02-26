"""Fernet-based encryption for storing LLM API keys at rest."""

import os
from cryptography.fernet import Fernet

_key = os.getenv("PROVIDER_KEY_SECRET")
if not _key:
    _key = Fernet.generate_key().decode()

fernet = Fernet(_key.encode() if isinstance(_key, str) else _key)


def encrypt_api_key(api_key: str) -> str:
    return fernet.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    return fernet.decrypt(encrypted_key.encode()).decode()
