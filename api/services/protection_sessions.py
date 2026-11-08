"""Зашифрованные cookies одной области. Короткий захват в БД не охватывает браузер."""

import json
import os
import re
from datetime import timedelta
from time import monotonic, sleep, time
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from ..models import ProtectionSession, Run
from .errors import FetchError
from .smartcaptcha_browser import origin_of


def setting(name, default=''):
    return getattr(settings, name, os.environ.get(name, default))


def browser_enabled(url):
    if str(setting('SCOUT_BROWSER_ENABLED')).lower() not in {'1', 'true', 'yes', 'on'}:
        return False
    try:
        origins = setting('SCOUT_BROWSER_ORIGINS', '[]')
        origins = json.loads(origins) if isinstance(origins, str) else origins
        return isinstance(origins, list) and origin_of(url) in origins
    except (FetchError, ValueError, TypeError):
        return False


def _scope(scope, url):
    return {'run_id' if isinstance(scope, Run) else 'visual_snapshot_id': scope.pk,
            'user_public_id': scope.user_public_id, 'origin': origin_of(url)}


def _binding(row):
    return {name: str(getattr(row, name) or '') for name in
            ('run_id', 'visual_snapshot_id', 'user_public_id', 'origin', 'proxy_revision_public_id')}


@sensitive_variables()
def _key(key_id=None):
    try:
        keys = setting('SCOUT_BROWSER_KEYS', '{}')
        keys = json.loads(keys) if isinstance(keys, str) else keys
        selected = key_id or setting('SCOUT_BROWSER_ACTIVE_KEY')
        if not isinstance(selected, str) or not 1 <= len(selected) <= 80:
            raise ValueError
        return selected, Fernet(keys[selected].encode('ascii'))
    except (KeyError, ValueError, TypeError, AttributeError, UnicodeError):
        raise FetchError('captcha_session_unavailable', 'Ключ браузерной сессии недоступен', retryable=False) from None


@sensitive_variables()
def read_session(scope, url, proxy_id):
    row = ProtectionSession.objects.filter(**_scope(scope, url)).first()
    if row is None or not row.ciphertext or row.expires_at <= timezone.now():
        return None
    if str(row.proxy_revision_public_id or '') != str(proxy_id or ''):
        raise FetchError('captcha_session_unavailable', 'Сетевой выход браузерной сессии не совпадает', retryable=False)
    try:
        _, key = _key(row.key_id)
        value = json.loads(key.decrypt(row.ciphertext.encode(), ttl=1200))
        if value.pop('binding') != _binding(row):
            raise ValueError
        return value
    except (InvalidToken, ValueError, TypeError, KeyError):
        raise FetchError('captcha_session_unavailable', 'Браузерная сессия не прошла проверку', retryable=False) from None


def claim_session(scope, url, proxy_id):
    _key()
    with transaction.atomic():
        # Область сериализует создание первой строки, без ожидания пользователя под блокировкой.
        type(scope).objects.select_for_update().get(pk=scope.pk)
        row, _ = ProtectionSession.objects.get_or_create(**_scope(scope, url), defaults={
            'proxy_revision_public_id': proxy_id, 'expires_at': timezone.now() + timedelta(minutes=20),
        })
        row = ProtectionSession.objects.select_for_update().get(pk=row.pk)
        if row.busy_until and row.busy_until > timezone.now():
            return None
        if row.busy_until:
            # Истёкший незавершённый захват восстанавливается; старый результат отсечёт generation.
            row.attempt_count = max(0, row.attempt_count - 1)
        if row.attempt_count >= 2 or str(row.proxy_revision_public_id or '') != str(proxy_id or ''):
            raise FetchError('captcha_attempts_exhausted', 'Лимит браузерных проверок запуска исчерпан', retryable=False)
        row.attempt_count += 1
        row.generation += 1
        row.busy_until = timezone.now() + timedelta(seconds=65)
        row.save(update_fields=['attempt_count', 'generation', 'busy_until'])
        return row


@sensitive_variables()
def save_session(row, result):
    key_id, key = _key()
    cookies = result['cookies']
    if len(cookies) > 64 or len(json.dumps(cookies)) > 24 * 1024:
        raise FetchError('captcha_session_unavailable', 'Сессия больше допустимого размера', retryable=False)
    value = {'binding': _binding(row), 'cookies': cookies, 'user_agent': result['user_agent']}
    encrypted = key.encrypt(json.dumps(value, separators=(',', ':')).encode()).decode()
    changed = ProtectionSession.objects.filter(pk=row.pk, generation=row.generation).update(
        ciphertext=encrypted, key_id=key_id, expires_at=timezone.now() + timedelta(minutes=20), busy_until=None,
    )
    if not changed:
        raise FetchError('captcha_session_unavailable', 'Браузерная сессия уже заменена', retryable=False)


def release_session(row, *, interrupted=False):
    updates = {'busy_until': None}
    if interrupted:
        updates['attempt_count'] = F('attempt_count') - 1
    ProtectionSession.objects.filter(pk=row.pk, generation=row.generation).update(**updates)


@sensitive_variables()
def session_headers(value, url):
    if not value:
        return {}
    ua = value['user_agent']
    if not isinstance(ua, str) or len(ua) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in ua):
        raise FetchError('captcha_session_unavailable', 'Недопустимые данные браузерной сессии', retryable=False)
    host, path = urlsplit(url).hostname, urlsplit(url).path or '/'
    pairs = []
    for cookie in value['cookies']:
        if cookie['domain'].lstrip('.') != host or cookie.get('expires', -1) not in (-1, 0) and cookie['expires'] <= time():
            continue
        prefix = cookie.get('path') or '/'
        if path != prefix and not (path.startswith(prefix) and (prefix.endswith('/') or path[len(prefix):].startswith('/'))):
            continue
        name, content = cookie['name'], cookie['value']
        if (not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                or any(ord(c) < 33 or ord(c) > 126 or c in ';,' for c in content)):
            raise FetchError('captcha_session_unavailable', 'Недопустимые данные браузерной сессии', retryable=False)
        pairs.append(name + '=' + content)
    joined = '; '.join(pairs)
    if len(joined) > 8192:
        raise FetchError('captcha_session_unavailable', 'Сессия больше допустимого размера', retryable=False)
    return {'User-Agent': ua, 'Cookie': joined}


def fetch_with_challenge(fetch, url, *, scope, proxy_id=None, should_continue=lambda: True, **kwargs):
    if not browser_enabled(url):
        return fetch(url, **kwargs)
    value = read_session(scope, url, proxy_id)
    try:
        return fetch(url, **kwargs, **({'request_headers': session_headers(value, url)} if value else {}))
    except FetchError as exc:
        if exc.code != 'yandex_captcha':
            raise
    deadline = monotonic() + 50
    while True:
        if not should_continue():
            raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
        row = claim_session(scope, url, proxy_id)
        if row is not None:
            break
        if monotonic() >= deadline:
            raise FetchError('captcha_browser_busy', 'Истекло ожидание браузерной сессии', retryable=False)
        sleep(.3)
        newer = read_session(scope, url, proxy_id)
        if newer and newer != value:
            return fetch(url, **kwargs, request_headers=session_headers(newer, url))
    from .proxy_profiles import load_proxy
    from .smartcaptcha_browser import fetch_browser_html
    interrupted = False
    try:
        proxy = load_proxy(proxy_id, scope.user_public_id) if proxy_id else None
        result = fetch_browser_html(url, cookies=(value or {}).get('cookies', []), proxy=proxy,
                                    max_bytes=kwargs['max_bytes'], url_allowed=kwargs.get('url_allowed'),
                                    channel=str(setting('SCOUT_BROWSER_CHANNEL', 'chrome')),
                                    should_continue=should_continue)
        if not should_continue():
            raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
        save_session(row, result)
        if isinstance(scope, Run):
            from .journal import append_event
            append_event(scope.pk, 'Флажок SmartCaptcha пройден; целевая страница получена.'
                         if result.get('challenge_present') else 'Целевая страница получена в отдельной браузерной сессии.')
        return result['page']
    except FetchError as exc:
        interrupted = exc.code == 'captcha_browser_cancelled'
        raise
    finally:
        release_session(row, interrupted=interrupted)


def clear_expired_sessions():
    ids = list(ProtectionSession.objects.filter(expires_at__lte=timezone.now()).exclude(ciphertext='').values_list('pk', flat=True)[:100])
    ProtectionSession.objects.filter(pk__in=ids, expires_at__lte=timezone.now()).update(ciphertext='', key_id='')
