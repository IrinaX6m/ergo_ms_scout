"""Проверки загрузки выбранной картинки через обычное соединение и профиль прокси."""

import gzip
import io
import zlib
from base64 import b64decode
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from urllib3.response import HTTPResponse

from modules.scout.api.services import http_fetch, proxy_http, public_http
from modules.scout.api.services.errors import FetchError


_URL = 'http://catalog.example/images/main'
# Однопиксельные изображения каждого поддерживаемого формата.
_JPEG = b64decode(
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a'
    'HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA'
    'AAAAAAAAAAAACP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AP7//2Q=='
)
_PNG = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR42mNgAAAAAgAB5Sfe/AAAAABJRU5ErkJggg==')
_GIF = b64decode('R0lGODdhAQABAIEAAAAAAAAAAAAAAAAAACwAAAAAAQABAAAIBAABBAQAOw==')
_WEBP = b64decode('UklGRhoAAABXRUJQVlA4TA4AAAAvAAAAAAcQEf0PRET/Aw==')


def _connection(body=b'', media=None, *, status='200 OK', headers=()):
    lines = [f'HTTP/1.1 {status}', f'Content-Length: {len(body)}', *headers]
    if media is not None:
        lines.append(f'Content-Type: {media}')
    connection = Mock()
    connection.makefile.return_value = io.BytesIO(('\r\n'.join(lines) + '\r\n\r\n').encode('ascii') + body)
    return connection


class ImageTransportTests(SimpleTestCase):
    def test_direct_download_preserves_image_bytes_and_normalizes_mime(self):
        for media, body in [('jpeg', _JPEG), ('png', _PNG), ('gif', _GIF), ('webp', _WEBP)]:
            with self.subTest(media=media):
                response = _connection(body, f'IMAGE/{media}; charset=binary')
                with patch.object(public_http, '_connect_public', return_value=response):
                    image = public_http.fetch_public_image(_URL, timeout_seconds=2, max_bytes=len(body))
                self.assertEqual(image['body'], body)
                self.assertEqual(image['content_type'], 'image/' + media)
                self.assertEqual(image['final_url'], _URL)

    def test_direct_download_requires_matching_mime_and_bytes(self):
        cases = [
            (None, _JPEG), ('application/octet-stream', _JPEG), ('image/jpeg', _PNG),
            ('image/png', b'<html></html>'), ('text/html', b'<html></html>'),
            ('image/svg+xml', b'<svg/>'), ('image/gif', b''),
        ]
        for media, body in cases:
            with self.subTest(media=media), patch.object(public_http, '_connect_public',
                    return_value=_connection(body, media)), self.assertRaises(FetchError) as error:
                public_http.fetch_public_image(_URL, timeout_seconds=2, max_bytes=1024)
            self.assertEqual(error.exception.code, 'unsupported_image')

    def test_byte_limit_applies_to_received_and_decompressed_content(self):
        compressed = gzip.compress(_JPEG)
        self.assertLess(len(compressed), len(_JPEG))
        for body, headers in [(_JPEG, ()), (compressed, ('Content-Encoding: gzip',))]:
            with self.subTest(headers=headers), patch.object(public_http, '_connect_public',
                    return_value=_connection(body, 'image/jpeg', headers=headers)), self.assertRaises(FetchError) as error:
                public_http.fetch_public_image(_URL, timeout_seconds=2, max_bytes=len(_JPEG) - 1)
            self.assertEqual(error.exception.code, 'too_large')

    def test_gzip_read_failure_is_reported_as_bad_encoding(self):
        compressed = gzip.compress(_JPEG)
        stream = Mock()
        stream.read.side_effect = zlib.error('incorrect compressed data')
        with (
            patch.object(http_fetch, '_gzip_stream', return_value=stream),
            patch.object(public_http, '_connect_public', return_value=_connection(
                compressed, 'image/jpeg', headers=('Content-Encoding: gzip',),
            )),
            self.assertRaises(FetchError) as error,
        ):
            public_http.fetch_public_image(_URL, timeout_seconds=2, max_bytes=1024)
        self.assertEqual(error.exception.code, 'bad_encoding')
        self.assertFalse(error.exception.retryable)
        stream.close.assert_called_once_with()

    def test_redirects_share_the_download_deadline_and_return_the_final_url(self):
        final = 'http://images.example/photo.png'
        redirect = _connection(status='302 Found', headers=(f'Location: {final}',))
        image = _connection(_PNG, 'image/png')
        with patch.object(public_http, '_connect_public', side_effect=[redirect, image]) as connect:
            result = public_http.fetch_public_image(_URL, timeout_seconds=2, max_bytes=len(_PNG))
        self.assertEqual(result['body'], _PNG)
        self.assertEqual(result['final_url'], final)
        self.assertEqual([call.args[0][0] for call in connect.call_args_list], ['catalog.example', 'images.example'])
        self.assertGreater(connect.call_args_list[0].kwargs['deadline'], 0)
        self.assertEqual(connect.call_args_list[0].kwargs['deadline'], connect.call_args_list[1].kwargs['deadline'])

    def test_proxy_download_uses_the_selected_profile_and_a_deadline(self):
        url = 'https://images.example/photo.webp'
        profile = SimpleNamespace(ip='192.0.2.10', port=443, tls_name='proxy.example', username=None)
        pool = SimpleNamespace(conn_kw={})
        manager = Mock()
        manager.connection_from_url.return_value = pool
        manager.request.return_value = HTTPResponse(
            body=io.BytesIO(_WEBP), status=200, reason='OK', headers={'Content-Type': 'image/webp'},
            preload_content=False,
        )
        with (
            patch.object(proxy_http, '_origin_ip', return_value='93.184.216.34'),
            patch.object(proxy_http, 'load_proxy', return_value=profile) as load,
            patch.object(proxy_http.urllib3, 'ProxyManager', return_value=manager),
        ):
            image = proxy_http.fetch_proxy_image(url, revision_id='revision', owner='owner',
                                                 timeout_seconds=2, max_bytes=len(_WEBP))
        self.assertEqual(image['body'], _WEBP)
        self.assertEqual(image['content_type'], 'image/webp')
        self.assertEqual(image['final_url'], url)
        load.assert_called_once_with('revision', 'owner')
        self.assertIsNotNone(pool.conn_kw['scout_socket_deadline'])
        manager.clear.assert_called()
