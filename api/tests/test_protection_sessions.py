"""Владелец/запуск/сеть, шифрование, лимит, fencing, пауза и отмена браузерного шага."""

import io
from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.request import Request
from uuid import uuid4

from cryptography.fernet import Fernet
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from ..models import ProtectionSession
from ..services.errors import FetchError
from ..services.http_fetch import _LimitedRedirect
from ..services.protection_sessions import (claim_session, clear_expired_sessions, fetch_with_challenge,
                                           read_session, release_session, save_session, session_headers)
from ..services.runs import create_job, explore_job
from ..services.tasks_exec import _claim, _fail

ORIGIN = 'https://source.test'
SECRET = 'sentinel-source-cookie'
KEY = Fernet.generate_key().decode()


def result():
    return {'page': {'body': b'<h1>Result</h1>', 'status': 200, 'content_type': 'text/html',
                     'charset': 'utf-8', 'final_url': ORIGIN + '/'},
            'cookies': [{'name': 'hc', 'value': SECRET, 'domain': 'source.test', 'path': '/',
                         'expires': -1, 'secure': True, 'httpOnly': True}], 'user_agent': 'Scout test browser'}


@override_settings(SCOUT_BROWSER_ENABLED=True, SCOUT_BROWSER_ORIGINS=[ORIGIN],
                   SCOUT_BROWSER_KEYS={'test': KEY}, SCOUT_BROWSER_ACTIVE_KEY='test')
class ProtectionSessionTests(TestCase):
    def setUp(self):
        self.owner = uuid4()
        self.scout_run = self.new_run(self.owner)

    def new_run(self, owner):
        job = create_job(user_public_id=owner, title='Protection fixture', seed_urls=[ORIGIN + '/'],
                         fields=[{'name': 'title', 'kind': 'css', 'selector': 'h1'}])
        return explore_job(job=job, user_public_id=owner)

    def test_automatic_pass_returns_only_page_and_reuses_encrypted_source_cookie(self):
        fetch = Mock(side_effect=[FetchError('yandex_captcha', 'CAPTCHA', retryable=False), result()['page']])
        with patch('modules.scout.api.services.smartcaptcha_browser.fetch_browser_html', return_value=result()) as browser:
            page = fetch_with_challenge(fetch, ORIGIN + '/', scope=self.scout_run, max_bytes=1000000, timeout_seconds=20)
            self.assertEqual(page, result()['page'])
            browser.assert_called_once()
            fetch_with_challenge(fetch, ORIGIN + '/next', scope=self.scout_run, max_bytes=1000000, timeout_seconds=20)
            self.assertEqual(browser.call_count, 1)
        self.assertEqual(fetch.call_args.kwargs['request_headers']['Cookie'], 'hc=' + SECRET)
        stored = ProtectionSession.objects.get()
        self.assertNotIn(SECRET, stored.ciphertext)
        self.assertEqual((stored.attempt_count, stored.busy_until), (1, None))
        self.assertNotIn('cookies', page)

    def test_another_owner_run_origin_and_proxy_cannot_reuse_the_secret(self):
        row = claim_session(self.scout_run, ORIGIN + '/', None)
        save_session(row, result())
        type(self.scout_run).objects.filter(pk=self.scout_run.pk).update(status='failed')
        other = self.new_run(uuid4())
        self.assertIsNone(read_session(other, ORIGIN + '/', None))
        self.assertIsNone(read_session(self.scout_run, 'https://other.test/', None))
        with self.assertRaises(FetchError):
            read_session(self.scout_run, ORIGIN + '/', uuid4())
        copied = claim_session(other, ORIGIN + '/', None)
        row.refresh_from_db()
        ProtectionSession.objects.filter(pk=copied.pk).update(ciphertext=row.ciphertext, key_id=row.key_id)
        with self.assertRaises(FetchError):
            read_session(other, ORIGIN + '/', None)

    def test_busy_budget_expiry_and_stale_writer(self):
        first = claim_session(self.scout_run, ORIGIN + '/', None)
        self.assertIsNone(claim_session(self.scout_run, ORIGIN + '/', None))
        release_session(first)
        second = claim_session(self.scout_run, ORIGIN + '/', None)
        with self.assertRaises(FetchError):
            save_session(first, result())
        save_session(second, result())
        with self.assertRaises(FetchError) as error:
            claim_session(self.scout_run, ORIGIN + '/', None)
        self.assertEqual(error.exception.code, 'captcha_attempts_exhausted')
        ProtectionSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(read_session(self.scout_run, ORIGIN + '/', None))
        clear_expired_sessions()
        self.assertEqual(ProtectionSession.objects.get().ciphertext, '')

    def test_interrupted_browser_does_not_consume_the_attempt_budget(self):
        fetch = Mock(side_effect=FetchError('yandex_captcha', 'CAPTCHA', retryable=False))
        with patch('modules.scout.api.services.smartcaptcha_browser.fetch_browser_html',
                   side_effect=FetchError('captcha_browser_cancelled', 'Interrupted', retryable=False)):
            with self.assertRaises(FetchError):
                fetch_with_challenge(fetch, ORIGIN + '/', scope=self.scout_run, max_bytes=1000000)
        row = ProtectionSession.objects.get()
        self.assertEqual((row.attempt_count, row.busy_until, row.ciphertext), (0, None, ''))

    def test_pause_requeues_the_step_and_cancel_discards_it(self):
        task = self.scout_run.tasks.get()
        claimed, token = _claim(str(task.public_id), task.fencing_token)
        self.scout_run.status = 'pausing'
        self.scout_run.save(update_fields=['status'])
        _fail(claimed, token, 'captcha_browser_cancelled', 'Interrupted', retryable=False)
        self.scout_run.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual((self.scout_run.status, task.status, self.scout_run.stop_reason), ('paused', 'pending', ''))
        self.scout_run.status = 'exploring'
        self.scout_run.save(update_fields=['status'])
        claimed, token = _claim(str(task.public_id), task.fencing_token)
        self.scout_run.status = 'cancelling'
        self.scout_run.save(update_fields=['status'])
        _fail(claimed, token, 'captcha_browser_cancelled', 'Interrupted', retryable=False)
        self.scout_run.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual((self.scout_run.status, task.status), ('cancelled', 'cancelled'))

    @override_settings(SCOUT_BROWSER_KEYS={})
    def test_missing_secret_key_never_opens_the_browser(self):
        fetch = Mock(side_effect=FetchError('yandex_captcha', 'CAPTCHA', retryable=False))
        with patch('modules.scout.api.services.smartcaptcha_browser.fetch_browser_html') as browser:
            with self.assertRaises(FetchError):
                fetch_with_challenge(fetch, ORIGIN + '/', scope=self.scout_run, max_bytes=1000000)
            browser.assert_not_called()


class CookieBoundaryTests(SimpleTestCase):
    def test_cookie_is_removed_on_cross_origin_redirect_but_preserved_within_origin(self):
        for target, expected in ((ORIGIN + '/next', 'hc=' + SECRET), ('https://other.test/', None),
                                 (ORIGIN + ':444/next', None), ('http://source.test/', None)):
            request = Request(ORIGIN + '/', headers={'Cookie': 'hc=' + SECRET})
            redirected = _LimitedRedirect().redirect_request(request, io.BytesIO(), 302, 'Found', {}, target)
            self.assertEqual(redirected.get_header('Cookie'), expected)

    def test_cookie_domain_path_expiry_and_header_injection(self):
        payload = result()
        self.assertEqual(session_headers(payload, ORIGIN + '/')['Cookie'], 'hc=' + SECRET)
        self.assertEqual(session_headers(payload, 'https://other.test/')['Cookie'], '')
        payload['cookies'][0]['path'] = '/private'
        self.assertEqual(session_headers(payload, ORIGIN + '/private-other')['Cookie'], '')
        self.assertEqual(session_headers(payload, ORIGIN + '/private/child')['Cookie'], 'hc=' + SECRET)
        payload['cookies'][0]['value'] = 'bad\r\nAuthorization: bad'
        with self.assertRaises(FetchError):
            session_headers(payload, ORIGIN + '/private')
