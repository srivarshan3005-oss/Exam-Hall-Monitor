from fastapi import Request
from .config import settings


def client_ip(request: Request) -> str:
    """Client address. X-Forwarded-For is honoured only when TRUST_PROXY=true (right-most hop)."""
    if settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[-1].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]
