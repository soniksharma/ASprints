"""Validation for page URLs before any browser or network activity."""

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit


class UrlPolicyError(ValueError):
    """Raised when a page URL is malformed or outside the public web scope."""


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan")


def is_public_address(address: str) -> bool:
    """Return whether *address* is a globally routable IPv4 or IPv6 literal."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_global and not parsed.is_multicast and not parsed.is_unspecified and not parsed.is_reserved


def normalize_page_url(value: str) -> str:
    """Return a normalized HTTP(S) URL while rejecting local destinations."""
    if not isinstance(value, str):
        raise UrlPolicyError("Enter a valid website URL.")
    value = value.strip()
    if not value or len(value) > 2048 or any(char.isspace() for char in value):
        raise UrlPolicyError("Enter a URL under 2,048 characters with no embedded spaces.")
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except ValueError as error:
        raise UrlPolicyError("Enter a valid website URL.") from error
    if scheme not in {"http", "https"}:
        raise UrlPolicyError("Only HTTP and HTTPS website URLs can be scanned.")
    if not host or parts.username is not None or parts.password is not None:
        raise UrlPolicyError("Enter a URL with a hostname and without embedded credentials.")

    host = host.rstrip(".").lower()
    if not host or host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        raise UrlPolicyError("Local and private network hosts cannot be scanned.")
    try:
        parsed_ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        parsed_ip = None
    if parsed_ip is not None:
        if not is_public_address(parsed_ip.compressed) or "%" in host:
            raise UrlPolicyError("Local and private network hosts cannot be scanned.")
        host = f"[{parsed_ip.compressed}]" if parsed_ip.version == 6 else parsed_ip.compressed
    else:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise UrlPolicyError("Enter a valid public website hostname.") from error
        labels = host.split(".")
        if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
            raise UrlPolicyError("Enter a valid public website hostname.")

    if port is not None and not 1 <= port <= 65535:
        raise UrlPolicyError("Enter a valid website port.")
    if (scheme, port) in {("http", 80), ("https", 443)}:
        port = None
    netloc = host if port is None else f"{host}:{port}"
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))
