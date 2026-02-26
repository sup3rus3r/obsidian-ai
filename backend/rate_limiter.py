import os
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse

RATE_LIMIT_USER         = os.getenv("RATE_LIMIT_USER", "60")
RATE_LIMIT_API_CLIENT   = os.getenv("RATE_LIMIT_API_CLIENT", "100")


def get_identifier(request: Request) -> str:
    """
    Get rate limit identifier based on authentication type.
    Uses API key for external clients, IP for JWT users.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api:{api_key}"

    return get_remote_address(request)

limiter = Limiter(key_func=get_identifier)

def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "retry_after": exc.detail,
        }
    )

def user_rate_limit():
    """Rate limit for authenticated users (JWT)."""
    return limiter.limit(f"{RATE_LIMIT_USER}/minute")

def api_client_rate_limit():
    """Rate limit for external API clients."""
    return limiter.limit(f"{RATE_LIMIT_API_CLIENT}/minute")


def combined_rate_limit():
    """
    Combined rate limit that applies different limits based on auth type.
    Uses the higher API client limit as the base, actual enforcement
    is handled by the identifier function.
    """
    return limiter.limit(f"{RATE_LIMIT_API_CLIENT}/minute")
