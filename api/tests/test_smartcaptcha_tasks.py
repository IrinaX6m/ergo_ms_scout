"""Текстовая картинка в настоящем Chrome, отказ, устаревший ответ и прерывание ML."""

import os
from tempfile import TemporaryDirectory
from threading import Event
from time import sleep
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import SimpleTestCase

from ..services import smartcaptcha_browser as browser, smartcaptcha_tasks as tasks
from ..services.errors import FetchError, ScoutError
from .fixtures.smartcaptcha_site import SmartCaptchaSite


class TaskFramePolicyTests(SimpleTestCase):
    def test_only_exact_https_provider_origins_are_accepted(self):
        self.assertTrue(tasks.is_provider_frame('https://smartcaptcha.yandexcloud.net/advanced.html'))
        self.assertTrue(tasks.is_provider_frame('https://smartcaptcha.cloud.yandex.ru/advanced.html'))
        for url in ('http://smartcaptcha.yandexcloud.net/', 'https://smartcaptcha.yandexcloud.net.evil.test/',
                    'https://user@smartcaptcha.yandexcloud.net/', 'https://smartcaptcha.yandexcloud.net:444/',
                    'https://checko.ru/advanced', 'https://127.0.0.1/advanced'):
            self.assertFalse(tasks.is_provider_frame(url))


class TextTaskBrowserTests(SimpleTestCase):
    def setUp(self):
        if os.name != 'nt' or not os.path.isfile('C:/Program Files/Google/Chrome/Application/chrome.exe'):
            self.skipTest('Requires installed Chrome')
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.site = SmartCaptchaSite(folder.name)
        self.addCleanup(self.site.close)
        self.site.text_task = True
        self.enterContext(patch.dict(os.environ, {'SCOUT_TRUSTED_FETCH_ENDPOINTS': '127.0.0.1:' + str(self.site.port)}))
        arguments = browser._launch_arguments

        def pinned(gateway, channel):
            result = arguments(gateway, channel)
            result['args'].append('--ignore-certificate-errors-spki-list=' + self.site.spki)
            return result

        self.enterContext(patch.object(browser, '_launch_arguments', side_effect=pinned))
        # Только тестовая форма. В продукте same-origin iframe не заменяет провайдера.
        self.enterContext(patch.object(tasks, 'is_provider_frame', side_effect=lambda u: u == self.site.origin + '/advanced'))

    def test_image_is_read_once_and_only_verified_target_html_is_returned(self):
        with patch.object(tasks, 'recognize_phrase', return_value=self.site.text_answer) as model:
            result = browser.fetch_browser_html(self.site.origin + '/catalog', seconds=15)
        self.assertEqual((result['image_tasks'], result['ml_calls'], result['page']['status']), (1, 1, 200))
        self.assertEqual(self.site.text_submissions, [True])
        self.assertTrue(model.call_args.args[0].startswith(b'\x89PNG'))
        self.assertNotIn(b'fixture-answer', result['page']['body'])
        self.assertFalse(any(key in result for key in ('answer', 'image', 'image_url')))

    def test_rejected_answers_are_bounded_and_no_target_page_is_returned(self):
        with patch.object(tasks, 'recognize_phrase', return_value='00000') as model:
            with self.assertRaises(FetchError) as error:
                browser.fetch_browser_html(self.site.origin + '/catalog', seconds=15)
        self.assertEqual(error.exception.code, 'captcha_attempts_exhausted')
        self.assertEqual(self.site.text_submissions, [False, False])
        self.assertEqual(model.call_count, 2)
        self.assertFalse(any(hit['method'] == 'POST' for hit in self.site.hits))

    def test_changed_challenge_discards_the_old_model_answer(self):
        self.site.refresh_text = True

        def recognize(*args, **kwargs):
            if self.site.task_version == 1:
                self.site.task_version = 2
                sleep(.4)
                return '00000'
            return self.site.text_answer

        with patch.object(tasks, 'recognize_phrase', side_effect=recognize):
            result = browser.fetch_browser_html(self.site.origin + '/catalog', seconds=15)
        self.assertEqual(result['page']['status'], 200)
        self.assertEqual(self.site.text_submissions, [True])
        self.assertEqual((result['image_tasks'], result['ml_calls']), (1, 2))

    def test_cancel_during_inference_does_not_submit_a_late_answer(self):
        cancel, release, finished = Event(), Event(), Event()

        def recognize(*args, **kwargs):
            cancel.set()
            try:
                release.wait(5)
                return self.site.text_answer
            finally:
                finished.set()

        with patch.object(tasks, 'recognize_phrase', side_effect=recognize):
            try:
                with self.assertRaises(FetchError) as error:
                    browser.fetch_browser_html(self.site.origin + '/catalog', seconds=15, should_continue=lambda: not cancel.is_set())
                self.assertEqual(error.exception.code, 'captcha_browser_cancelled')
            finally:
                release.set()
                finished.wait(5)
        self.assertFalse(self.site.text_submissions)

    def test_model_failure_does_not_submit_or_fall_back(self):
        with patch.object(tasks, 'recognize_phrase', side_effect=ScoutError('captcha_model_unavailable', 'Unavailable')):
            with self.assertRaises(FetchError) as error:
                browser.fetch_browser_html(self.site.origin + '/catalog', seconds=15)
        self.assertEqual(error.exception.code, 'captcha_model_unavailable')
        self.assertFalse(self.site.text_submissions)
