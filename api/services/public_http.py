"""Публичные источники визуального редактора, включая адрес фактического соединения."""

import http.client
import ipaddress
import socket
from time import monotonic
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPSHandler, ProxyHandler

from .errors import FetchError
from .http_fetch import fetch_html

_IPV6_UNICAST = ipaddress.ip_network('2000::/3')


def public_url_allowed(url):
    try:
        parts = urlsplit(url)
        if (
            parts.scheme in ('http', 'https')
            and parts.hostname
            and parts.username is None
            and '%' not in parts.netloc
            and parts.port in (None, 443 if parts.scheme == 'https' else 80)
            and not any(char.isspace() or ord(char) < 32 or char == '\\' for char in url)
        ):
            return True
    except ValueError:
        pass
    raise FetchError('url_blocked', 'Нужен публичный HTTP(S)-адрес страницы', retryable=False)


def fetch_public_html(url, *, timeout_seconds, max_bytes):
    return fetch_html(
        url, timeout_seconds=timeout_seconds, max_bytes=max_bytes, url_allowed=public_url_allowed,
        handlers=(ProxyHandler({}), _PublicHTTPHandler(), _PublicHTTPSHandler()),
    )


def _public_address(address):
    ip = ipaddress.ip_address(address)
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return _public_address(str(ip.ipv4_mapped))
        if ip not in _IPV6_UNICAST or ip.sixtofour is not None or ip.teredo is not None:
            return False
    return ip.is_global and not (ip.is_multicast or ip.is_reserved)


def _connect_public(address, timeout, source_address=None):
    deadline = monotonic() + timeout
    addresses = socket.getaddrinfo(*address, type=socket.SOCK_STREAM)
    if not addresses or any(not _public_address(info[4][0]) for info in addresses):
        raise FetchError('url_blocked', 'Адрес ведёт в закрытую сеть', retryable=False)

    # Подключаемся к уже проверенному IP без повторного разрешения имени.
    last_error = None
    for family, kind, protocol, _, sockaddr in addresses:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError('HTTP connection timed out')
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(remaining)
            if source_address is not None:
                connection.bind(source_address)
            connection.connect(sockaddr)
            return connection
        except OSError as exc:
            connection.close()
            last_error = exc
    raise last_error


class _PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_public


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_public


class _PublicHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(_PublicHTTPConnection, request)


class _PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_PublicHTTPSConnection, request, context=self._context)
