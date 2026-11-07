"""Настройка хранения и просмотр/исполнение очистки, строго в границах владельца."""

from django.core import signing
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from src.core.utils.base.base_views import BaseAPIView

from .integrations import error_payload, error_status
from .models import RetentionCleanup, RetentionPreview, Run
from .permissions import CanConfigureScout, CanViewScout
from .services.access import require_user_public_id
from .services.errors import ScoutError
from .services.retention import (
    accept_cleanup, change_hold, cleanup_payload, create_preview, policy_for, policy_payload,
    preview_payload, public_item, run_retention, update_policy,
)


class RetentionView(BaseAPIView):
    def get_permissions(self):
        classes = [IsAuthenticated, CanViewScout]
        if self.request.method != 'GET':
            classes.append(CanConfigureScout)
        return [permission() for permission in classes]

    def handle_exception(self, exc):
        if isinstance(exc, ScoutError):
            return Response(error_payload(exc), status=error_status(exc))
        return super().handle_exception(exc)

    def owner(self, request):
        return require_user_public_id(request.user)

    def run(self, request, public_id):
        return get_object_or_404(
            Run.objects.select_related('job_revision'), public_id=public_id, user_public_id=self.owner(request),
        )


class RetentionPolicyView(RetentionView):
    def get(self, request):
        return Response(policy_payload(policy_for(self.owner(request))))

    def patch(self, request):
        return Response(policy_payload(update_policy(self.owner(request), request.data)))


class RunRetentionView(RetentionView):
    def get(self, request, public_id):
        return Response(run_retention(self.run(request, public_id)))


class RetentionHoldView(RetentionView):
    def put(self, request, public_id):
        return Response(change_hold(self.run(request, public_id), request.data, request.headers.get('Idempotency-Key')))

    def delete(self, request, public_id):
        return Response(change_hold(self.run(request, public_id), request.data,
                                    request.headers.get('Idempotency-Key'), remove=True))


class RetentionPreviewsView(RetentionView):
    def post(self, request):
        return Response(preview_payload(create_preview(self.owner(request), request.data)), status=201)


class RetentionPreviewItemsView(RetentionView):
    def get(self, request, public_id):
        preview = get_object_or_404(RetentionPreview, public_id=public_id, user_public_id=self.owner(request))
        items = [*preview.manifest, *preview.summary['excluded']]
        return Response(_page(request, preview, [public_item(item) for item in items]))


class RetentionCleanupsView(RetentionView):
    def post(self, request):
        return Response(cleanup_payload(accept_cleanup(self.owner(request), request.data)), status=202)


class RetentionCleanupView(RetentionView):
    def get(self, request, public_id):
        cleanup = get_object_or_404(RetentionCleanup, public_id=public_id, user_public_id=self.owner(request))
        return Response(cleanup_payload(cleanup))


class RetentionCleanupItemsView(RetentionView):
    def get(self, request, public_id):
        cleanup = get_object_or_404(RetentionCleanup, public_id=public_id, user_public_id=self.owner(request))
        return Response(_page(request, cleanup, [
            {**public_item(item.specification), 'status': item.status, 'reason': item.reason,
             'deleted_bytes': item.deleted_bytes, 'deleted_rows': item.deleted_rows}
            for item in cleanup.items.all()
        ]))


def _page(request, parent, items):
    try:
        limit = int(request.query_params.get('limit', 50))
        if not 1 <= limit <= 200:
            raise ValueError
    except (TypeError, ValueError):
        raise ScoutError('invalid_limit', 'Размер порции от 1 до 200') from None
    context = [str(parent.public_id), str(parent.user_public_id), parent.__class__.__name__]
    offset = 0
    raw = request.query_params.get('cursor')
    if raw is not None:
        try:
            if len(raw) > 512:
                raise ValueError
            data = signing.loads(raw, salt='scout.retention.items.v1')
            if not isinstance(data, list) or len(data) != 4 or data[:3] != context:
                raise ValueError
            offset = data[3]
            if type(offset) is not int or not 0 <= offset <= len(items):
                raise ValueError
        except (signing.BadSignature, ValueError, TypeError):
            raise ScoutError('invalid_cursor', 'Курсор не соответствует перечню') from None
    more = offset + limit < len(items)
    return {'items': items[offset:offset + limit], 'next_cursor': signing.dumps(
        [*context, offset + limit], salt='scout.retention.items.v1',
    ) if more else None}
