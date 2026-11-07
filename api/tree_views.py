"""Чтение DOM-метаданных: владельцы, сроки, пределы и безопасные ошибки."""

import json
import logging
import math

from django.db import DatabaseError
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework import exceptions
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from src.core.utils.base.base_views import BaseAPIView

from .models import VisualSnapshot
from .permissions import CanConfigureScout
from .services.errors import ScoutError
from .services.retention_locks import read_resource
from .services.visual_rules import VisualDocument
from .services.visual_snapshots import SNAPSHOT_TTL, snapshot_status
from .services.visual_tree import (
    MISSING, MAX_RESPONSE_BYTES, VisualTree, check_tree_version, invalid, search_terms, validate_keys,
)

logger = logging.getLogger('modules.scout')
_STATUSES = {
    'snapshot_not_found': 404, 'node_not_found': 404,
    'snapshot_not_ready': 409, 'tree_version_changed': 409,
    'invalid_query': 400, 'node_not_child': 400, 'invalid_cursor': 400, 'cursor_expired': 400,
    'request_too_large': 413, 'unsupported_media_type': 415,
    'tree_too_large': 422, 'tree_depth_exceeded': 422, 'storage_unavailable': 503,
}


class _DOMReadThrottle(UserRateThrottle):
    scope = 'scout_dom_read'
    rate = '240/minute'


class _DOMSearchThrottle(UserRateThrottle):
    scope = 'scout_dom_search'
    rate = '60/minute'


def _query(request, allowed):
    if any(len(values) != 1 for _, values in request.query_params.lists()):
        raise invalid()
    data = request.query_params.dict()
    validate_keys(data, allowed)
    return data


class _TreeView(BaseAPIView):
    permission_classes = [IsAuthenticated, CanConfigureScout]
    throttle_classes = [*BaseAPIView.throttle_classes, _DOMReadThrottle]
    renderer_classes = [JSONRenderer]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response

    @sensitive_variables()
    def handle_exception(self, exc):
        headers = {}
        path = None
        if isinstance(exc, ScoutError) and exc.code in _STATUSES:
            code, status, detail, path = exc.code, _STATUSES[exc.code], str(exc), exc.path
        elif isinstance(exc, (exceptions.AuthenticationFailed, exceptions.NotAuthenticated)):
            code, status, detail = 'authentication_failed', 401, 'Требуется аутентификация'
            headers['WWW-Authenticate'] = 'Bearer'
        elif isinstance(exc, exceptions.PermissionDenied):
            code, status, detail = 'permission_denied', 403, 'Недостаточно прав'
        elif isinstance(exc, exceptions.Throttled):
            code, status, detail = 'throttled', 429, 'Слишком частые запросы'
            if exc.wait is not None:
                headers['Retry-After'] = str(math.ceil(exc.wait))
        elif isinstance(exc, exceptions.MethodNotAllowed):
            code, status, detail = 'method_not_allowed', 405, 'Метод не поддерживается'
        elif isinstance(exc, exceptions.NotAcceptable):
            code, status, detail = 'not_acceptable', 406, 'Доступен формат JSON'
        elif isinstance(exc, DatabaseError):
            code, status, detail = 'storage_unavailable', 503, 'Хранилище временно недоступно'
        else:
            # Нельзя записывать исключение: в нём могут быть HTML, поиск или курсор.
            logger.error('SCOUT не прочитал метаданные дерева')
            code, status, detail = 'internal_error', 500, 'Не удалось прочитать дерево'
        return Response({'code': code, 'detail': detail, **({'path': path} if path else {})}, status=status, headers=headers)

    def _snapshot(self, request, public_id):
        snapshot = VisualSnapshot.objects.filter(
            public_id=public_id, user_public_id=request.user.public_id,
            created_at__gt=timezone.now() - SNAPSHOT_TTL,
        ).first()
        if snapshot is None:
            raise ScoutError('snapshot_not_found', 'Снимок недоступен')
        return snapshot

    @sensitive_variables()
    def _read(self, request, public_id, action):
        snapshot = self._snapshot(request, public_id)
        with read_resource(f'visual:{snapshot.pk}'):
            snapshot = self._snapshot(request, public_id)
            if snapshot_status(snapshot)[0] != 'ready':
                raise ScoutError('snapshot_not_ready', 'Снимок не готов для чтения дерева')
            data, operation = action()
            required = operation != 'branch' or any(k in data for k in ('parent_id', 'cursor', 'around_node_id'))
            check_tree_version(snapshot, data.get('tree_version', MISSING), required=required)
            if len(snapshot.body) > 1_000_000:
                raise ScoutError('tree_too_large', 'Снимок превышает допустимый объём')
            try:
                document = VisualDocument(bytes(snapshot.body), snapshot.charset)
            except ScoutError as exc:
                if exc.code == 'too_large':
                    raise ScoutError('tree_too_large', 'Слишком много узлов для дерева') from None
                raise
            tree = VisualTree(document, snapshot)
            if operation == 'branch':
                result = tree.branch(data)
            elif operation == 'detail':
                result = tree.detail(self.kwargs['node_id'])
            else:
                query, tag = search_terms(data)
                result = tree.search(data, query, tag)
            if len(JSONRenderer().render(result)) > MAX_RESPONSE_BYTES:
                raise ScoutError('tree_too_large', 'Ответ дерева превышает допустимый объём')
            return Response(result)


class VisualTreeView(_TreeView):
    def get(self, request, public_id):
        return self._read(request, public_id, lambda: (
            _query(request, ('parent_id', 'around_node_id', 'limit', 'cursor', 'tree_version')), 'branch',
        ))


class VisualTreeNodeView(_TreeView):
    def get(self, request, public_id, node_id):
        return self._read(request, public_id, lambda: (_query(request, ('tree_version',)), 'detail'))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise invalid()
        result[key] = value
    return result


class VisualTreeSearchView(_TreeView):
    throttle_classes = [*BaseAPIView.throttle_classes, _DOMSearchThrottle]

    @sensitive_variables()
    def post(self, request, public_id):
        def body():
            _query(request, ())
            if request.content_type != 'application/json':
                raise ScoutError('unsupported_media_type', 'Поиск принимает JSON')
            raw = request.stream.read(4097) if request.stream is not None else b''
            if len(raw) > 4096:
                raise ScoutError('request_too_large', 'Запрос поиска превышает допустимый объём')
            try:
                data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
            except (ValueError, UnicodeError, RecursionError):
                raise invalid() from None
            validate_keys(data, ('q', 'tag', 'limit', 'cursor', 'tree_version'))
            return data, 'search'

        return self._read(request, public_id, body)
