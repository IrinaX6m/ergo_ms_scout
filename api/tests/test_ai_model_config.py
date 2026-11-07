"""Выбор модели Scout не зависит от модели по умолчанию других потребителей."""

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ..services.errors import ScoutError
from ..services.plan_suggestions import _generate


class ScoutAIModelTests(SimpleTestCase):
    def test_explicit_model_uses_provider_profile_and_blank_preserves_default(self):
        with patch('modules.scout.api.services.plan_suggestions.bridge') as provider:
            provider.call.return_value='{}'
            with override_settings(SCOUT_AI_MODEL=' qwen3.5:4b '):
                self.assertEqual(_generate('sample'),'{}')
                self.assertEqual(provider.call.call_args.kwargs['config']['model'],'qwen3.5:4b')
                self.assertTrue(provider.call.call_args.kwargs['skip_env_injection'])
            with override_settings(SCOUT_AI_MODEL=''):
                _generate('sample')
                self.assertNotIn('model',provider.call.call_args.kwargs['config'])
                self.assertFalse(provider.call.call_args.kwargs['skip_env_injection'])

    def test_bad_server_model_does_not_call_provider(self):
        with patch('modules.scout.api.services.plan_suggestions.bridge') as provider:
            for model in (None,'name\nother','x'*201):
                with override_settings(SCOUT_AI_MODEL=model):
                    with self.assertRaises(ScoutError) as failure:
                        _generate('sample')
                    self.assertEqual(failure.exception.code,'model_unavailable')
            provider.call.assert_not_called()
