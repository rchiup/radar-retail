"""Proxy handling.

A proxy is configured as a single URL, the format every HTTP tool understands:

    http://host:port
    http://user:password@host:port

Playwright needs it split into server/username/password, hence the helper below.
"""

from typing import Optional
from urllib.parse import unquote, urlsplit


def normalize(proxy_url: Optional[str]) -> Optional[str]:
    """Return the proxy URL with a scheme, or None when no proxy is configured."""
    if not proxy_url or not proxy_url.strip():
        return None
    proxy_url = proxy_url.strip()
    if "://" not in proxy_url:
        proxy_url = f"http://{proxy_url}"
    return proxy_url


def for_playwright(proxy_url: Optional[str]) -> Optional[dict]:
    """Split a proxy URL into Playwright's {server, username, password} form."""
    normalized = normalize(proxy_url)
    if not normalized:
        return None

    parts = urlsplit(normalized)
    if not parts.hostname:
        raise ValueError(f"Invalid proxy URL: {proxy_url!r}")

    server = f"{parts.scheme}://{parts.hostname}"
    if parts.port:
        server = f"{server}:{parts.port}"

    result = {"server": server}
    if parts.username:
        result["username"] = unquote(parts.username)
    if parts.password:
        result["password"] = unquote(parts.password)
    return result
