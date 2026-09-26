"""Fetch user-submitted public URLs without reaching private network addresses."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import parse_qsl, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
MAX_RESPONSE_BYTES = 2_000_000
SENSITIVE_QUERY_KEYS = {"token", "access_token", "api_key", "apikey", "password", "secret", "auth", "session"}
USER_AGENT = "pstack-budget-watch/0.2 (+contact: operations)"
IPV6_TRANSLATION_PREFIXES = (
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 well-known prefix
    ipaddress.ip_network("::/96"),         # deprecated IPv4-compatible form
)


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global and not (
        isinstance(address, ipaddress.IPv6Address)
        and any(address in prefix for prefix in IPV6_TRANSLATION_PREFIXES)
    )


def validate_public_url(url: str) -> str:
    """Accept public HTTP(S) URLs only; no embedded credentials or secret query keys."""
    value = url.strip()
    if not value or len(value) > MAX_URL_LENGTH or any(ord(char) < 32 for char in value):
        raise ValueError("invalid URL length or control character")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None or parts.fragment):
        raise ValueError("URL must be a public HTTP(S) address without credentials or fragment")
    host = parts.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("private hostname is not allowed")
    if any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise ValueError("URL query appears to contain a credential")
    if port is not None and port not in {80, 443}:
        raise ValueError("only standard HTTP(S) ports are allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise ValueError("hostname must be fully qualified") from None
    else:
        if not _is_public_address(str(address)):
            raise ValueError("private IP address is not allowed")
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _public_address(host: str, port: int, resolver=socket.getaddrinfo) -> str:
    answers = resolver(host, port, type=socket.SOCK_STREAM)
    addresses = {answer[4][0] for answer in answers}
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise ValueError("URL resolves to a private or invalid address")
    return sorted(addresses)[0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str):
        super().__init__(host, port, timeout=30)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str):
        super().__init__(host, port, timeout=30, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch_public(url: str, resolver=socket.getaddrinfo) -> tuple[int, bytes, str, str]:
    """Resolve once, verify all DNS answers, pin the connection, and refuse redirects."""
    normalized = validate_public_url(url)
    parts = urlsplit(normalized)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    address = _public_address(host, port, resolver)
    connection = (_PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection)(host, port, address)
    try:
        target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        connection.request("GET", target, headers={"User-Agent": USER_AGENT, "Accept": "text/html, application/rss+xml, application/xml"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ValueError("redirects are not followed for user-submitted URLs")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size limit")
        return response.status, body, response.getheader("ETag", ""), response.getheader("Last-Modified", "")
    finally:
        connection.close()
