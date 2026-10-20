"""Field schemas for typed Secrets Vault entries. Used by secrets_router.py
to validate a secret's fields payload and decide which fields to mask in
list responses, and by the frontend to render the right form per type."""

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
