"""Сетевые границы: разрешение CONNECT, закрытый DNS и настоящий изолированный Chrome."""

import os
import socket
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import SimpleTestCase

from ..services.browser_egress import BrowserEgress
from ..services.errors import FetchError
from ..services.smartcaptcha_browser import fetch_browser_html
from .fixtures.smartcaptcha_site import SmartCaptchaSite


class BrowserEgressTests(SimpleTestCase):
    def test_failed_gateway_creation_releases_the_browser_slot(self):
        from ..services import smartcaptcha_browser
        with patch.object(smartcaptcha_browser, 'BrowserEgress', side_effect=OSError):
            with self.assertRaises(FetchError) as error:
                fetch_browser_html('https://source.test/')
            self.assertEqual(error.exception.code, 'captcha_browser_unavailable')
        self.assertTrue(smartcaptcha_browser._SLOTS.acquire(blocking=False))
        smartcaptcha_browser._SLOTS.release()

    def connect(self, gateway, host):
        with socket.socket() as conn:
            conn.settimeout(3)
            conn.connect(gateway.server.server_address)
            conn.sendall(f'CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n'.encode())
            return conn.recv(1000)

    def test_private_and_similar_provider_names_are_rejected_before_dns(self):
        with BrowserEgress('https://source.test', seconds=3) as gateway:
            with patch('modules.scout.api.services.public_http.socket.getaddrinfo') as dns:
                for host in ('127.0.0.1', '169.254.169.254', 'localhost', 'smartcaptcha.yandexcloud.net.evil.test'):
                    self.assertIn(b'403', self.connect(gateway, host))
                dns.assert_not_called()

    def test_allowed_name_resolving_to_private_address_is_not_connected(self):
        with BrowserEgress('https://source.test', seconds=3) as gateway:
            with patch('modules.scout.api.services.public_http.socket.getaddrinfo', return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]):
                with self.assertRaises(FetchError) as error:
                    gateway._connect('source.test', 443, 1)
            self.assertEqual(error.exception.code, 'url_blocked')

    def test_proxy_failure_does_not_try_a_direct_connection(self):
        from types import SimpleNamespace
        proxy = SimpleNamespace(ip='127.0.0.1', port=1, tls_name='fixture.test', username=None, password=None)
        with BrowserEgress('https://source.test', proxy=proxy, seconds=3) as gateway:
            with patch('modules.scout.api.services.proxy_http._origin_ip', return_value='8.8.8.8'), \
                 patch('modules.scout.api.services.browser_egress.socket.create_connection', side_effect=OSError) as connect:
                with self.assertRaises(OSError):
                    gateway._connect('source.test', 443, 1)
                connect.assert_called_once_with(('127.0.0.1', 1), timeout=1)

    def test_real_browser_solves_own_form_and_returns_raw_html_without_token(self):
        if os.name != 'nt' or not os.path.isfile('C:/Program Files/Google/Chrome/Application/chrome.exe'):
            self.skipTest('Requires installed Chrome; run the separate live check on this host')
        with TemporaryDirectory() as directory:
            fixture = SmartCaptchaSite(directory)
            self.addCleanup(fixture.close)
            from ..services import smartcaptcha_browser

            arguments = smartcaptcha_browser._launch_arguments

            def pinned_arguments(gateway, channel):
                options = arguments(gateway, channel)
                options['args'].append('--ignore-certificate-errors-spki-list=' + fixture.spki)
                return options

            with patch.dict(os.environ, {'SCOUT_TRUSTED_FETCH_ENDPOINTS': '127.0.0.1:' + str(fixture.port)}), \
                 patch.object(smartcaptcha_browser, '_launch_arguments', side_effect=pinned_arguments):
                result = fetch_browser_html(fixture.origin + '/catalog', seconds=15,
                                            url_allowed=lambda url: urlsplit(url).path == '/catalog')
                self.assertTrue(result['challenge_present'])
                self.assertEqual(result['page']['status'], 200)
                self.assertIn(b'<h1>Product /catalog</h1>', result['page']['body'])
                self.assertNotIn(b'fixture-answer', result['page']['body'])
                self.assertTrue(any(c['name'] == 'hc' for c in result['cookies']))
                self.assertEqual(sum(h['method'] == 'POST' for h in fixture.hits), 1)

    def test_real_browser_does_not_disable_tls_verification(self):
        if os.name != 'nt' or not os.path.isfile('C:/Program Files/Google/Chrome/Application/chrome.exe'):
            self.skipTest('Requires installed Chrome')
        with TemporaryDirectory() as directory:
            fixture = SmartCaptchaSite(directory)
            self.addCleanup(fixture.close)
            with patch.dict(os.environ, {'SCOUT_TRUSTED_FETCH_ENDPOINTS': '127.0.0.1:' + str(fixture.port)}):
                with self.assertRaises(FetchError) as error:
                    fetch_browser_html(fixture.origin + '/catalog', seconds=10)
                self.assertEqual(error.exception.code, 'captcha_browser_network')
                self.assertFalse(fixture.hits)
