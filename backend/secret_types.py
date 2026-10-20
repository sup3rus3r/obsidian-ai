"""Field schemas for typed Secrets Vault entries. Used by secrets_router.py
to validate a secret's fields payload and decide which fields to mask in
list responses, and by the frontend to render the right form per type."""

import json

SECRET_TYPE_SCHEMAS: dict[str, dict[str, dict]] = {
    "generic": {
        "value": {"label": "Value", "sensitive": True},
    },
    "credit_card": {
        "number": {"label": "Card Number", "sensitive": True},
        "expiry": {"label": "Expiry (MM/YY)", "sensitive": False},
        "cvv": {"label": "CVV", "sensitive": True},
        "cardholder_name": {"label": "Cardholder Name", "sensitive": False},
    },
    "login": {
        "username": {"label": "Username", "sensitive": False},
        "password": {"label": "Password", "sensitive": True},
    },
    "smtp": {
        "host": {"label": "SMTP Host", "sensitive": False},
        "port": {"label": "Port", "sensitive": False},
        "username": {"label": "Username", "sensitive": False},
        "password": {"label": "Password", "sensitive": True},
        "from_address": {"label": "From Address", "sensitive": False},
        "use_tls": {"label": "Use TLS (true/false)", "sensitive": False},
    },
}


def validate_fields(secret_type: str, fields: dict) -> None:
    """Raise ValueError if fields don't match the declared type's schema."""
    schema = SECRET_TYPE_SCHEMAS.get(secret_type)
    if schema is None:
        raise ValueError(f"Unknown secret_type: {secret_type}")
    missing = [f for f in schema if f not in fields or not str(fields[f]).strip()]
    if missing:
        raise ValueError(f"Missing required field(s) for {secret_type}: {', '.join(missing)}")
    unknown = [f for f in fields if f not in schema]
    if unknown:
        raise ValueError(f"Unknown field(s) for {secret_type}: {', '.join(unknown)}")


def decrypt_fields(secret_type: str, encrypted_value_raw: str) -> dict[str, str]:
    """Decrypt every field for a secret, tolerating the pre-typed legacy shape
    (encrypted_value was a single Fernet ciphertext, not a JSON blob). Every
    consumer of UserSecret.encrypted_value must go through this, not
    decrypt_api_key directly — the raw column is a JSON blob of
    {field: fernet_ciphertext}, not a bare Fernet token."""
    from encryption import decrypt_api_key

    schema = SECRET_TYPE_SCHEMAS.get(secret_type, SECRET_TYPE_SCHEMAS["generic"])
    try:
        blob = json.loads(encrypted_value_raw)
        if not isinstance(blob, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError, TypeError):
        blob = {"value": encrypted_value_raw}

    decrypted = {}
    for field in schema:
        ciphertext = blob.get(field)
        if not ciphertext:
            continue
        try:
            decrypted[field] = decrypt_api_key(ciphertext)
        except Exception:
            continue
    return decrypted
