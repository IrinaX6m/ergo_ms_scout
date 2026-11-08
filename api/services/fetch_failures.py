"""Окончательные отказы загрузки, после которых очередь источника не продолжают."""

from .challenges import CHALLENGE_FAILURES
from .proxy_profiles import PROXY_FAILURES

STOP_FETCH_FAILURES = PROXY_FAILURES | CHALLENGE_FAILURES | frozenset({
    'captcha_browser_scope', 'captcha_browser_busy', 'captcha_browser_cancelled', 'captcha_browser_timeout',
    'captcha_browser_unavailable', 'captcha_browser_network', 'captcha_browser_budget', 'captcha_browser_response',
    'captcha_task_unsupported', 'captcha_not_cleared', 'captcha_session_unavailable', 'captcha_attempts_exhausted',
    'captcha_model_unavailable', 'captcha_model_busy', 'captcha_model_timeout', 'captcha_model_invalid',
    'captcha_unrecognized', 'captcha_image_invalid', 'captcha_config',
})
