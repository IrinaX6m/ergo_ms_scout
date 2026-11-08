"""Ограниченный CONNECT-шлюз браузера: публичный закреплённый IP, TLS проверяет Chrome."""

import base64
import select
import socket
import socketserver
import ssl
from threading import BoundedSemaphore, Event, Lock, Thread
from time import monotonic
from urllib.parse import urlsplit

from .errors import FetchError
from .public_http import _trusted_ip


class BrowserEgress:
    def __init__(self, origin, *, proxy=None, seconds=45, max_bytes=16 * 1024 * 1024):
        source = urlsplit(origin)
        self.authorities = {(source.hostname, source.port or 443)} | {
            (host, 443) for host in ('smartcaptcha.yandexcloud.net', 'smartcaptcha.cloud.yandex.ru',
                                    'captcha-api.yandex.ru', 'yastatic.net', 'avatars.mds.yandex.net')
        }
        self.proxy = proxy
        self.deadline = monotonic() + seconds
        self.max_bytes = max_bytes
        self.cancelled = Event()
        self.lock = Lock()
        self.slots = BoundedSemaphore(12)
        self.sockets = set()
        self.transferred = 0
        self.connections = 0
        self.denied = set()
        self.failure = None
        gateway = self

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = False
            daemon_threads = True

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                if not gateway.slots.acquire(blocking=False):
                    return
                try:
                    gateway._handle(self)
                except (OSError, ValueError, FetchError):
                    # Ни URL целиком, ни заголовки, ни ошибки стороннего прокси не журналируем.
                    pass
                finally:
                    gateway.slots.release()

        self.server = Server(('127.0.0.1', 0), Handler)

    def __enter__(self):
        self.thread = Thread(target=self.server.serve_forever, name='scout-browser-egress', daemon=True)
        self.thread.start()
        return self

    @property
    def address(self):
        return 'http://127.0.0.1:' + str(self.server.server_address[1])

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            for sock in tuple(self.sockets):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def __exit__(self, *args):
        self.cancel()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _handle(self, handler):
        client = handler.connection
        client.settimeout(3)
        first = handler.rfile.readline(4097)
        total = len(first)
        while line := handler.rfile.readline(4097):
            total += len(line)
            if total > 16 * 1024 or len(line) > 4096:
                return
            if line == b'\r\n':
                break
        method, authority, protocol = first.decode('ascii').strip().split()
        if method != 'CONNECT' or protocol not in ('HTTP/1.0', 'HTTP/1.1'):
            return
        parsed = urlsplit('https://' + authority)
        host, port = parsed.hostname, parsed.port or 443
        if (parsed.username is not None or parsed.password is not None or parsed.path
                or parsed.query or parsed.fragment or (host, port) not in self.authorities):
            with self.lock:
                self.denied.add(host or '')
            client.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
            return
        with self.lock:
            self.connections += 1
            if self.connections > 100:
                return
        remaining = min(8, self.deadline - monotonic())
        if self.cancelled.is_set() or remaining <= 0:
            return
        try:
            upstream = self._connect(host, port, remaining)
        except FetchError as exc:
            self.failure = (exc.code, str(exc), exc.retryable)
            return
        except (OSError, ssl.SSLError):
            self.failure = ('proxy_unavailable' if self.proxy else 'network',
                            'Не удалось открыть соединение браузера', False)
            return
        with upstream:
            with self.lock:
                self.sockets.update((client, upstream))
            try:
                client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                while not self.cancelled.is_set() and monotonic() < self.deadline:
                    readers, _, _ = select.select((client, upstream), (), (), 0.2)
                    for source in readers:
                        data = source.recv(64 * 1024)
                        if not data:
                            return
                        with self.lock:
                            self.transferred += len(data)
                            if self.transferred > self.max_bytes:
                                self.failure = ('captcha_browser_budget', 'Превышен объём браузерной проверки', False)
                                return
                        (upstream if source is client else client).sendall(data)
            finally:
                with self.lock:
                    self.sockets.discard(client)
                    self.sockets.discard(upstream)

    def _connect(self, host, port, timeout):
        from .proxy_http import _origin_ip
        if self.proxy is None:
            trusted = _trusted_ip(host, port)
            ip = str(trusted) if trusted is not None else _origin_ip(host, self.deadline)
            # Числовой адрес закреплён после ограниченного разрешения имени.
            return socket.create_connection((ip, port), timeout=min(timeout, max(.05, self.deadline - monotonic())))
        # Сначала определяем публичный IP цели; CONNECT внешнему прокси передаёт именно его.
        ip = _origin_ip(host, self.deadline)
        target = f'[{ip}]:{port}' if ':' in ip else f'{ip}:{port}'
        raw = socket.create_connection((self.proxy.ip, self.proxy.port), timeout=timeout)
        try:
            tunnel = ssl.create_default_context().wrap_socket(raw, server_hostname=self.proxy.tls_name)
        except (ssl.SSLError, ssl.CertificateError):
            raw.close()
            raise FetchError('proxy_tls_error', 'Не удалось проверить TLS прокси', retryable=False) from None
        except BaseException:
            raw.close()
            raise
        try:
            auth = ''
            if self.proxy.username is not None:
                credentials = f'{self.proxy.username}:{self.proxy.password}'.encode()
                auth = 'Proxy-Authorization: Basic ' + base64.b64encode(credentials).decode() + '\r\n'
            tunnel.sendall((f'CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n' + auth + '\r\n').encode('ascii'))
            response = bytearray()
            while not response.endswith(b'\r\n\r\n') and len(response) <= 16384:
                if self.cancelled.is_set() or monotonic() >= self.deadline:
                    raise FetchError('proxy_unavailable', 'Истекло время подключения прокси', retryable=False)
                tunnel.settimeout(max(.05, min(1, self.deadline - monotonic())))
                piece = tunnel.recv(1)
                if not piece:
                    break
                response += piece
            status = bytes(response).split(b'\r\n', 1)[0].split()
            if len(response) > 16384 or not response.endswith(b'\r\n\r\n') or len(status) < 2 or status[1] != b'200':
                code = 'proxy_auth_failed' if len(status) > 1 and status[1] == b'407' else 'proxy_unavailable'
                raise FetchError(code, 'Прокси не открыл браузерное соединение', retryable=False)
            tunnel.settimeout(max(.05, min(8, self.deadline - monotonic())))
            return tunnel
        except BaseException:
            tunnel.close()
            raise
