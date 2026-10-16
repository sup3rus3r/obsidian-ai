"""Optional ngrok tunnel for exposing this self-hosted backend to the public
internet, so external platforms can reach an agent's public API endpoint
(public_api_router.py) even when the server only has a local/LAN address.

Fully opt-in: only activates if ENABLE_NGROK_TUNNEL is set truthy. Nothing
about normal startup changes if it's unset — no port is opened, no ngrok
process is spawned, and importing this module has no side effects."""

import logging
import os

logger = logging.getLogger(__name__)

_public_url: str | None = None


def is_enabled() -> bool:
    return os.getenv("ENABLE_NGROK_TUNNEL", "").strip().lower() in ("1", "true", "yes")


def get_public_url() -> str | None:
    """Returns the current public tunnel URL, or None if no tunnel is running
    (either disabled, or it failed to start)."""
    return _public_url


def start_tunnel(port: int) -> str | None:
    """Start an ngrok tunnel to the given local port. No-op (returns None) if
    ENABLE_NGROK_TUNNEL isn't set. Never raises — a failed tunnel should not
    prevent the backend itself from starting."""
    global _public_url
    if not is_enabled():
        return None
    try:
        from pyngrok import ngrok, conf

        authtoken = os.getenv("NGROK_AUTHTOKEN")
        if authtoken:
            conf.get_default().auth_token = authtoken

        tunnel = ngrok.connect(port, "http")
        _public_url = tunnel.public_url
        logger.info("ngrok tunnel started: %s -> localhost:%s", _public_url, port)
        return _public_url
    except Exception as e:
        logger.warning("Failed to start ngrok tunnel (continuing without one): %s", e)
        _public_url = None
        return None


def stop_tunnel() -> None:
    global _public_url
    if not is_enabled() or _public_url is None:
        return
    try:
        from pyngrok import ngrok
        ngrok.kill()
    except Exception as e:
        logger.warning("Failed to stop ngrok tunnel cleanly: %s", e)
    finally:
        _public_url = None
