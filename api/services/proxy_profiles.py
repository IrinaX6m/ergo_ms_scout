"""Версии прокси и зашифрованные реквизиты Scout."""

import ipaddress
import json
import os
import re
from dataclasses import dataclass, field
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from ..models import ProxyProfile, ProxyProfileRevision, Run, VisualSnapshot
from .constants import OCCUPYING_STATUSES
from .errors import FetchError, ScoutError
from .public_http import _public_address
from .url_norm import canonical_host

PROXY_FAILURES = frozenset({'proxy_unavailable', 'proxy_auth_failed', 'proxy_tls_error',
                            'proxy_blocked', 'proxy_credentials_unavailable'})
PROXY_RETRY_DELAYS = (1, 3)


@dataclass(frozen=True)
class ProxyConnection:
    ip: str
    port: int
    tls_name: str
    username: str | None = field(repr=False)
    password: str | None = field(repr=False)


def _mapping(name):
    try:
        values = getattr(settings, name, None)
        if values is None:
            values = json.loads(os.environ.get(name, '{}'))
        return values if isinstance(values, dict) else {}
    except ValueError:
        return {}


def ip_authority(ip, port):
    return f'[{ip}]:{port}' if ':' in ip else f'{ip}:{port}'


def endpoint_name(ip, port):
    configured = _mapping('SCOUT_PROXY_ENDPOINTS').get(ip_authority(ip, port))
    if not _public_address(ip) or not isinstance(configured, str):
        raise FetchError('proxy_blocked', 'Адрес прокси не разрешён', retryable=False)
    name = canonical_host(configured)
    if not name or not re.fullmatch(r'[a-z0-9.:-]+', name):
        raise FetchError('proxy_blocked', 'Адрес прокси не разрешён', retryable=False)
    return name


def _require_enabled():
    enabled = getattr(settings, 'SCOUT_PROXY_ENABLED', None)
    if enabled is None:
        enabled = os.environ.get('SCOUT_PROXY_ENABLED') == '1'
    if enabled is not True:
        raise FetchError('proxy_blocked', 'Режим прокси выключен', retryable=False)


def _unavailable():
    return FetchError('proxy_credentials_unavailable', 'Реквизиты прокси недоступны', retryable=False)


@sensitive_variables()
def _cipher(key_id):
    key = _mapping('SCOUT_PROXY_KEYS').get(key_id)
    if not isinstance(key, str) or not key:
        raise _unavailable()
    try:
        return Fernet(key.encode('ascii'))
    except (TypeError, ValueError, UnicodeError):
        raise _unavailable() from None


def _binding(revision):
    return [str(revision.public_id), str(revision.profile.user_public_id), revision.ip, revision.port,
            endpoint_name(revision.ip, revision.port)]


@sensitive_variables()
def _seal(revision, key_id, username, password):
    secret = json.dumps([_binding(revision), username, password]).encode('ascii')
    revision.key_id = key_id
    revision.ciphertext = _cipher(key_id).encrypt(secret).decode('ascii')


@sensitive_variables()
def _open_secret(revision):
    if not revision.ciphertext or revision.profile.revoked_at:
        raise _unavailable()
    try:
        binding, username, password = json.loads(_cipher(revision.key_id).decrypt(revision.ciphertext.encode('ascii')))
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise _unavailable() from None
    credentials_valid = (
        revision.auth_type == 'none' and username is None and password is None
        or revision.auth_type == 'basic' and _valid_credentials(username, password)
    )
    if binding != _binding(revision) or not credentials_valid:
        raise _unavailable()
    return username, password


def _valid_credentials(username, password):
    return (
        isinstance(username, str) and re.fullmatch(r'[\x21-\x39\x3b-\x7e]{1,128}', username)
        and isinstance(password, str) and re.fullmatch(r'[\x20-\x7e]{1,256}', password)
    )


def _active_key_id():
    key_id = getattr(settings, 'SCOUT_PROXY_ACTIVE_KEY', None) or os.environ.get('SCOUT_PROXY_ACTIVE_KEY', '')
    if not isinstance(key_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key_id):
        raise _unavailable()
    return key_id


@sensitive_variables()
def save_profile(owner, data, profile_id=None):
    _require_enabled()
    if not isinstance(data, dict):
        raise ScoutError('invalid', 'Укажите параметры прокси')
    auth_type = data.get('auth_type', 'basic')
    if auth_type not in ('basic', 'none'):
        raise ScoutError('invalid', 'Выберите basic или none для авторизации прокси')
    required = {'ip', 'port'} | ({'username', 'password'} if auth_type == 'basic' else {'auth_type'})
    if set(data) not in (required, required | {'auth_type'}):
        raise ScoutError('invalid', 'Для basic укажите IP, порт, логин и пароль; для none — IP и порт без реквизитов')
    ip, port = data['ip'], data['port']
    username, password = data.get('username'), data.get('password')
    if not isinstance(ip, str) or '%' in ip or type(port) is not int or not 1 <= port <= 65535:
        raise ScoutError('invalid', 'Проверьте IP и порт прокси')
    try:
        parsed = ipaddress.ip_address(ip)
        if getattr(parsed, 'ipv4_mapped', None):
            raise ValueError
        ip = str(parsed)
    except ValueError:
        raise ScoutError('invalid', 'Проверьте IP и порт прокси') from None
    endpoint_name(ip, port)
    if auth_type == 'basic' and not _valid_credentials(username, password):
        raise ScoutError('invalid', 'Проверьте формат логина и пароля прокси')
    key_id = _active_key_id()
    with transaction.atomic():
        if profile_id is None:
            profile = ProxyProfile.objects.create(user_public_id=owner)
        else:
            profile = ProxyProfile.objects.select_for_update().filter(
                public_id=profile_id, user_public_id=owner, revoked_at__isnull=True,
            ).first()
            if profile is None:
                raise ScoutError('proxy_blocked', 'Профиль прокси недоступен')
        revision = ProxyProfileRevision(profile=profile, ip=ip, port=port, auth_type=auth_type)
        _seal(revision, key_id, username, password)
        revision.save()
        _prune_profile(profile)
    return revision


def validate_revision(revision_id, owner, *, lock=False):
    if revision_id is None:
        return None
    _require_enabled()
    try:
        public_id = UUID(str(revision_id))
    except (ValueError, TypeError):
        raise ScoutError('proxy_blocked', 'Профиль прокси недоступен') from None
    profiles = ProxyProfile.objects.select_for_update() if lock else ProxyProfile.objects
    profile = profiles.filter(user_public_id=owner, revoked_at__isnull=True, revisions__public_id=public_id).first()
    active = profile.revisions.order_by('-pk').first() if profile else None
    if active is None or active.public_id != public_id or not active.ciphertext:
        raise ScoutError('proxy_blocked', 'Профиль прокси недоступен')
    endpoint_name(active.ip, active.port)
    return active.public_id


@sensitive_variables()
def load_proxy(revision_id, owner):
    _require_enabled()
    revision = ProxyProfileRevision.objects.select_related('profile').filter(
        public_id=revision_id, profile__user_public_id=owner, profile__revoked_at__isnull=True,
    ).first()
    if revision is None:
        raise _unavailable()
    tls_name = endpoint_name(revision.ip, revision.port)
    username, password = _open_secret(revision)
    return ProxyConnection(revision.ip, revision.port, tls_name, username, password)


def revoke_profile(profile_id, owner):
    with transaction.atomic():
        profiles = ProxyProfile.objects.select_for_update().filter(public_id=profile_id)
        if owner is not None:
            profiles = profiles.filter(user_public_id=owner)
        profile = profiles.first()
        if profile is None:
            raise ScoutError('proxy_blocked', 'Профиль прокси недоступен')
        profile.revoked_at = timezone.now()
        profile.save(update_fields=['revoked_at'])
        profile.revisions.update(ciphertext='', key_id='')


def _prune_profile(profile):
    active = profile.revisions.order_by('-pk').first()
    if active is None:
        return
    old = profile.revisions.exclude(pk=active.pk).exclude(ciphertext='')
    running = Run.objects.filter(status__in=OCCUPYING_STATUSES, job_revision__proxy_profile_revision_public_id__isnull=False)
    visual = VisualSnapshot.objects.filter(status__in=('queued', 'fetching'), proxy_profile_revision_public_id__isnull=False)
    old.exclude(public_id__in=running.values('job_revision__proxy_profile_revision_public_id')).exclude(
        public_id__in=visual.values('proxy_profile_revision_public_id'),
    ).update(ciphertext='', key_id='')


def prune_proxy_credentials():
    for profile_id in ProxyProfileRevision.objects.exclude(ciphertext='').order_by().values_list('profile_id', flat=True).distinct():
        with transaction.atomic():
            profile = ProxyProfile.objects.select_for_update().filter(pk=profile_id).first()
            if profile:
                _prune_profile(profile)


@sensitive_variables()
def rotate_proxy_keys():
    key_id = _active_key_id()
    _cipher(key_id)
    count = 0
    for profile_id in ProxyProfile.objects.filter(revoked_at__isnull=True).values_list('pk', flat=True).iterator():
        with transaction.atomic():
            profile = ProxyProfile.objects.select_for_update().filter(pk=profile_id, revoked_at__isnull=True).first()
            if not profile:
                continue
            for revision in profile.revisions.exclude(key_id=key_id).exclude(ciphertext=''):
                username, password = _open_secret(revision)
                _seal(revision, key_id, username, password)
                revision.save(update_fields=['key_id', 'ciphertext'])
                count += 1
    return count
