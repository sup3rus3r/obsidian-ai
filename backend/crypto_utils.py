import base64
import hashlib
import json
import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")


def decrypt_payload(encrypted_data: str) -> dict:
    """
    Decrypt data encrypted by CryptoJS AES.
    CryptoJS uses OpenSSL-compatible format with "Salted__" prefix.
    """
    raw = base64.b64decode(encrypted_data)

    if raw[:8] != b"Salted__":
        raise ValueError("Invalid encrypted data format")

    salt = raw[8:16]
    ciphertext = raw[16:]

    key, iv = _evp_bytes_to_key(ENCRYPTION_KEY.encode(), salt, 32, 16)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)

    return json.loads(decrypted.decode("utf-8"))


def _evp_bytes_to_key(password: bytes, salt: bytes, key_len: int, iv_len: int):
    """
    OpenSSL EVP_BytesToKey key derivation function.
    Used by CryptoJS for password-based encryption.
    """
    dtot = b""
    d = b""
    while len(dtot) < key_len + iv_len:
        d = hashlib.md5(d + password + salt).digest()
        dtot += d
    return dtot[:key_len], dtot[key_len:key_len + iv_len]
