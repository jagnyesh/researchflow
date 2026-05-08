"""
Rate Limiting Middleware for ResearchFlow API

Implements rate limiting to prevent API abuse, brute-force attacks, and DoS attempts.

Rate Limits:
- Global: 100 requests/minute per IP
- Authentication endpoints (/auth/login): 5 requests/minute (brute-force prevention)
- Heavy query endpoints: 10 requests/minute
- Default for unspecified endpoints: 100 requests/minute

Uses SlowAPI (based on Flask-Limiter) for rate limiting.
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, FastAPI

# Create limiter instance
# Key function: Uses client IP address for rate limit tracking
# Default limits can be overridden per endpoint
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


def setup_rate_limiting(app: FastAPI):
    """
    Configure rate limiting for FastAPI application

    Args:
        app: FastAPI application instance

    Sets up:
    - Global rate limiter
    - Rate limit exceeded exception handler
    - Rate limit headers in responses
    """
    # Add rate limiter to app state
    app.state.limiter = limiter

    # Add rate limit exceeded exception handler
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Decorator for endpoint-specific rate limits
# Usage: @limiter.limit("5/minute")
def rate_limit(limit_string: str):
    """
    Decorator for applying custom rate limits to endpoints

    Args:
        limit_string: Rate limit string (e.g., "5/minute", "10/hour")

    Returns:
        Decorator function

    Example:
        @router.post("/auth/login")
        @limiter.limit("5/minute")
        async def login(...):
            ...
    """
    return limiter.limit(limit_string)


# Pre-defined rate limit decorators for common use cases
def auth_rate_limit():
    """
    Strict rate limit for authentication endpoints

    Limit: 5 requests/minute
    Purpose: Prevent brute-force password attacks
    """
    return limiter.limit("5/minute")


def query_rate_limit():
    """
    Moderate rate limit for heavy query endpoints

    Limit: 10 requests/minute
    Purpose: Prevent resource exhaustion from expensive queries
    """
    return limiter.limit("10/minute")


def default_rate_limit():
    """
    Default rate limit for general endpoints

    Limit: 100 requests/minute
    Purpose: General API abuse prevention
    """
    return limiter.limit("100/minute")


# Rate limit for specific endpoint types
RATE_LIMITS = {
    "auth": "5/minute",  # Authentication (login, logout, refresh)
    "query": "10/minute",  # Heavy queries (SQL-on-FHIR, analytics)
    "api": "100/minute",  # General API endpoints
    "public": "200/minute",  # Public endpoints (health checks, etc.)
}


def get_rate_limit_for_endpoint(endpoint_type: str) -> str:
    """
    Get rate limit string for endpoint type

    Args:
        endpoint_type: Type of endpoint (auth, query, api, public)

    Returns:
        Rate limit string (e.g., "5/minute")
    """
    return RATE_LIMITS.get(endpoint_type, RATE_LIMITS["api"])
