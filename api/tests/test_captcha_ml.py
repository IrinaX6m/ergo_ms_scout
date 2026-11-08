"""Локальность, границы изображения, ответ/отказ модели и занятое место."""

import base64
import io
import json
from threading import Event
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from PIL import Image, ImageDraw, PngImagePlugin

from ..services import captcha_ml
from ..services.errors import ScoutError


def picture(size=(160, 60)):
    image = Image.new('RGB', size, 'white')
    ImageDraw.Draw(image).line((5, 5, 20, 20), fill='black', width=2)
    meta = PngImagePlugin.PngInfo()
    meta.add_text('token', 'sentinel-private-metadata')
    result = io.BytesIO()
    image.save(result, format='PNG', pnginfo=meta)
    return result.getvalue()


@override_settings(SCOUT_CAPTCHA_ML_ENABLED=True, SCOUT_CAPTCHA_ML_MODEL='qwen3.5:4b',
                   SCOUT_CAPTCHA_ML_TIMEOUT_SECONDS=5, BRIDGE_TRANSPORT='local',
                   MODULE_RUNTIME='monolith', OLLAMA_FRAMEWORK_TRANSPORT='local')
class CaptchaMLTests(SimpleTestCase):
    def test_only_normalized_pixels_go_to_new_local_operation(self):
        with patch.object(captcha_ml.bridge, 'call', return_value='{"answer":"48271"}') as call:
            self.assertEqual(captcha_ml.recognize_text(picture(), alphabet='0123456789', min_length=5, max_length=5), '48271')
        self.assertEqual(call.call_args.args, ('ollama_framework.chat_local',))
        payload = call.call_args.kwargs
        self.assertEqual(payload['model'], 'qwen3.5:4b')
        images = payload['messages'][1]['images']
        normalized = base64.b64decode(images[0])
        self.assertNotIn(b'sentinel', normalized)
        with Image.open(io.BytesIO(normalized)) as image:
            self.assertEqual(image.info, {})

    def test_disabled_remote_transport_cloud_model_or_missing_model_never_calls_bridge(self):
        for config in ({'SCOUT_CAPTCHA_ML_ENABLED': False}, {'BRIDGE_TRANSPORT': 'http'},
                       {'OLLAMA_FRAMEWORK_TRANSPORT': 'http'}, {'MODULE_RUNTIME': 'microservice'},
                       {'SCOUT_CAPTCHA_ML_MODEL': ''}, {'SCOUT_CAPTCHA_ML_MODEL': 'test:cloud'}):
            with self.subTest(config=config), override_settings(**config), patch.object(captcha_ml.bridge, 'call') as call:
                with self.assertRaises(ScoutError) as error:
                    captcha_ml.recognize_text(picture())
                self.assertEqual(error.exception.code, 'captcha_model_unavailable')
                call.assert_not_called()

    def test_bad_or_oversized_images_are_not_sent(self):
        for data in (b'', b'x' * (256 * 1024 + 1), b'<svg/>', b'file:///private.png', picture((1024, 1024))):
            with self.subTest(length=len(data)), patch.object(captcha_ml.bridge, 'call') as call:
                with self.assertRaises(ScoutError) as error:
                    captcha_ml.recognize_text(data)
                self.assertEqual(error.exception.code, 'captcha_image_invalid')
                call.assert_not_called()

    def test_uniform_blank_is_rejected_before_model_can_invent_an_answer(self):
        output = io.BytesIO()
        Image.new('RGB', (240, 80), 'white').save(output, format='PNG')
        with patch.object(captcha_ml.bridge, 'call') as call:
            with self.assertRaises(ScoutError) as error:
                captcha_ml.recognize_text(output.getvalue())
            self.assertEqual(error.exception.code, 'captcha_unrecognized')
            call.assert_not_called()

    def test_invalid_or_abstaining_model_response(self):
        for response, code in ((None, 'captcha_model_unavailable'), ('{"answer":null}', 'captcha_unrecognized'),
                               ('[]', 'captcha_model_invalid'), ('{"answer":"https://bad"}', 'captcha_model_invalid'),
                               ('{"answer":"12345","token":"sentinel"}', 'captcha_model_invalid'),
                               ('{"answer":12345}', 'captcha_model_invalid'), ('x'*513, 'captcha_model_invalid'),
                               ('{"answer":"AB123"}', 'captcha_model_invalid')):
            with self.subTest(code=code), patch.object(captcha_ml.bridge, 'call', return_value=response):
                with self.assertRaises(ScoutError) as error:
                    captcha_ml.recognize_text(picture(), alphabet='0123456789', min_length=5, max_length=5)
                self.assertEqual(error.exception.code, code)
                self.assertNotIn('sentinel', str(error.exception))

    def test_busy_slot_is_not_queued(self):
        self.assertTrue(captcha_ml._SLOTS.acquire(blocking=False))
        try:
            with patch.object(captcha_ml.bridge, 'call') as call:
                with self.assertRaises(ScoutError) as error:
                    captcha_ml.recognize_text(picture())
                self.assertEqual(error.exception.code, 'captcha_model_busy')
                call.assert_not_called()
        finally:
            captcha_ml._SLOTS.release()

    @override_settings(SCOUT_CAPTCHA_ML_TIMEOUT_SECONDS=1)
    def test_timeout_keeps_slot_until_model_call_finishes(self):
        release, finished = Event(), Event()

        def invoke(*args, **kwargs):
            try:
                release.wait(5)
                return json.dumps({'answer': '12345'})
            finally:
                finished.set()

        with patch.object(captcha_ml.bridge, 'call', side_effect=invoke):
            try:
                with self.assertRaises(ScoutError) as error:
                    captcha_ml.recognize_text(picture())
                self.assertEqual(error.exception.code, 'captcha_model_timeout')
                self.assertFalse(captcha_ml._SLOTS.acquire(blocking=False))
            finally:
                release.set()
                finished.wait(5)
                self.assertTrue(captcha_ml._SLOTS.acquire(timeout=1))
                captcha_ml._SLOTS.release()
