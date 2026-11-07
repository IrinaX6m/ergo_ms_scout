"""API метаданных прокси. Реквизиты доступны только на запись."""

import logging
import os

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from src.core.cms.adp.services.permissions import PermissionService
from src.core.utils.base.base_views import BaseAPIView

from .integrations import error_payload, error_status
from .models import ProxyProfile
from .permissions import CanConfigureScout, CanRunScout
from .services.access import require_user_public_id
from .services.errors import ScoutError
from .services.proxy_http import fetch_proxy_html
from .services.proxy_profiles import revoke_profile, save_profile

logger = logging.getLogger('modules.scout')


def _profiles(user):
    return ProxyProfile.objects.filter(user_public_id=require_user_public_id(user), revoked_at__isnull=True)


def _payload(revision):
    return {
        'public_id': str(revision.profile.public_id),
        'revision_public_id': str(revision.public_id),
        'ip': revision.ip,
        'port': revision.port,
        'auth_type': revision.auth_type,
        'credentials_configured': revision.auth_type == 'basic' and bool(revision.ciphertext),
    }


def _reply(data, status=200):
    return Response(data, status=status, headers={'Cache-Control': 'no-store'})


@sensitive_variables()
def _write(request, profile_id=None):
    if not request.is_secure():
        return _reply({'code': 'https_required', 'detail': 'Для ввода реквизитов нужен HTTPS'}, 400)
    try:
        revision = save_profile(require_user_public_id(request.user), request.data, profile_id)
    except ScoutError as exc:
        return _reply(error_payload(exc), error_status(exc))
    except Exception:
        logger.error('SCOUT не записал реквизиты прокси')
        return _reply({'code': 'proxy_credentials_unavailable', 'detail': 'Не удалось сохранить реквизиты прокси'}, 503)
    logger.info('SCOUT обновил профиль прокси %s', revision.profile.public_id)
    return _reply(_payload(revision), 201 if profile_id is None else 200)


@method_decorator(sensitive_post_parameters(), name='dispatch')
class ProxyProfilesView(BaseAPIView):
    permission_classes = [IsAuthenticated, CanConfigureScout]

    def get(self, request):
        revisions = (profile.revisions.order_by('-pk').first() for profile in _profiles(request.user).order_by('-pk')[:100])
        return _reply({'profiles': [_payload(revision) for revision in revisions if revision]})

    def post(self, request):
        return _write(request)


@method_decorator(sensitive_post_parameters(), name='dispatch')
class ProxyProfileView(BaseAPIView):
    permission_classes = [IsAuthenticated, CanConfigureScout]

    def get(self, request, public_id):
        profile = get_object_or_404(_profiles(request.user), public_id=public_id)
        return _reply(_payload(profile.revisions.order_by('-pk').first()))

    def patch(self, request, public_id):
        get_object_or_404(_profiles(request.user), public_id=public_id)
        return _write(request, public_id)

    def delete(self, request, public_id):
        owner = None if PermissionService.is_admin(request.user) else require_user_public_id(request.user)
        try:
            revoke_profile(public_id, owner)
        except ScoutError as exc:
            return _reply(error_payload(exc), 404)
        logger.info('SCOUT отозвал профиль прокси %s', public_id)
        return _reply(None, 204)


class _ProxyCheckThrottle(UserRateThrottle):
    scope = 'scout_proxy_check'
    rate = '10/hour'


class ProxyProfileCheckView(BaseAPIView):
    permission_classes = [IsAuthenticated, CanConfigureScout, CanRunScout]
    throttle_classes = [*BaseAPIView.throttle_classes, _ProxyCheckThrottle]

    def post(self, request, public_id):
        profile = get_object_or_404(_profiles(request.user), public_id=public_id)
        revision = profile.revisions.order_by('-pk').first()
        url = getattr(settings, 'SCOUT_PROXY_CHECK_URL', None) or os.environ.get('SCOUT_PROXY_CHECK_URL')
        if not url:
            return _reply({'status': 'failed', 'code': 'proxy_check_unavailable'})
        try:
            fetch_proxy_html(url, revision_id=revision.public_id, owner=profile.user_public_id,
                             timeout_seconds=5, max_bytes=32_768, same_origin=True)
        except ScoutError as exc:
            logger.info('SCOUT проверил профиль прокси %s, код %s', public_id, exc.code)
            return _reply({'status': 'failed', 'code': exc.code})
        except Exception:
            logger.error('SCOUT не завершил проверку профиля прокси %s', public_id)
            return _reply({'status': 'failed', 'code': 'proxy_check_unavailable'})
        logger.info('SCOUT проверил профиль прокси %s', public_id)
        return _reply({'status': 'ready'})
