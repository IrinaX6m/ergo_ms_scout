"""API редактора. Все операции работают с временными снимками текущего пользователя."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from src.core.utils.base.base_views import BaseAPIView

from .integrations import error_payload, error_status
from .models import VisualSnapshot
from .permissions import CanConfigureScout, CanRunScout
from .services.access import require_user_public_id
from .services.errors import ScoutError
from .services.visual_rules import VisualDocument
from .services.visual_snapshots import SNAPSHOT_TTL, create_snapshot, enqueue_snapshot, snapshot_status


class _SnapshotCreateThrottle(UserRateThrottle):
    scope = 'scout_visual_snapshot'
    rate = '30/hour'


class VisualSnapshotCreateView(BaseAPIView):
    permission_classes = [IsAuthenticated, CanConfigureScout, CanRunScout]
    throttle_classes = [*BaseAPIView.throttle_classes, _SnapshotCreateThrottle]

    def post(self, request):
        try:
            data = _request_object(request.data)
            snapshot = create_snapshot(
                require_user_public_id(request.user), data.get('url'), data.get('proxy_profile_revision_public_id'),
            )
        except ScoutError as exc:
            return Response(error_payload(exc), status=error_status(exc))
        transaction.on_commit(lambda: enqueue_snapshot(snapshot.public_id), using=snapshot._state.db)
        return Response({'public_id': str(snapshot.public_id), 'status': 'loading'}, status=202)


class VisualSnapshotDetailView(BaseAPIView):
    permission_classes = [IsAuthenticated, CanConfigureScout]

    def get(self, request, public_id):
        snapshot = _get_snapshot(request.user, public_id)
        status, error = snapshot_status(snapshot)
        result = {'public_id': str(snapshot.public_id), 'status': status}
        if status == 'ready':
            document = VisualDocument(bytes(snapshot.body), snapshot.charset)
            result.update(final_url=snapshot.final_url, html=document.editor_html())
        if error is not None:
            result['error'] = error
        return Response(result, headers={'Cache-Control': 'no-store'})


class VisualSnapshotCheckView(BaseAPIView):
    permission_classes = [IsAuthenticated, CanConfigureScout]

    def post(self, request, public_id):
        snapshot = _get_snapshot(request.user, public_id)
        status, _ = snapshot_status(snapshot)
        if status != 'ready':
            return Response({'code': 'snapshot_not_ready', 'detail': 'Снимок недоступен для проверки'}, status=409)
        try:
            data = _request_object(request.data)
            document = VisualDocument(bytes(snapshot.body), snapshot.charset)
            result = document.check(source_url=snapshot.source_url, record=data.get('record'), field=data.get('field'))
        except ScoutError as exc:
            return Response(error_payload(exc), status=error_status(exc))
        return Response(result)


def _request_object(data):
    if not isinstance(data, dict):
        raise ScoutError('invalid', 'Тело запроса должно быть объектом')
    return data


def _get_snapshot(user, public_id):
    return get_object_or_404(
        VisualSnapshot,
        public_id=public_id,
        user_public_id=getattr(user, 'public_id', None),
        created_at__gt=timezone.now() - SNAPSHOT_TTL,
    )
