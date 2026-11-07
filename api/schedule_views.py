"""API ежедневного расписания и назначенных календарных дней."""

from datetime import date
from uuid import UUID

from django.core import signing
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from src.core.utils.base.base_views import BaseAPIView

from .integrations import error_payload, error_status
from .models import DailySchedule
from .permissions import CanConfigureScout, CanRunScout, CanViewScout
from .services.access import jobs_for
from .services.daily_schedules import create_schedule, occurrence_payload, schedule_payload, update_schedule
from .services.errors import ScoutError

_CURSOR_SALT = 'scout.schedule_occurrences.v1'


class DailyScheduleView(BaseAPIView):
    def get_permissions(self):
        classes = (IsAuthenticated, CanViewScout) if self.request.method == 'GET' else (
            IsAuthenticated, CanConfigureScout, CanRunScout,
        )
        return [permission() for permission in classes]

    def get(self, request, public_id):
        job = get_object_or_404(jobs_for(request.user), public_id=public_id)
        schedule = get_object_or_404(DailySchedule, job=job)
        return Response(schedule_payload(schedule))

    def post(self, request, public_id):
        job = get_object_or_404(jobs_for(request.user), public_id=public_id)
        try:
            schedule = create_schedule(job, request.data)
        except ScoutError as exc:
            return Response(error_payload(exc), status=error_status(exc))
        return Response(schedule_payload(schedule), status=201)

    def patch(self, request, public_id):
        job = get_object_or_404(jobs_for(request.user), public_id=public_id)
        schedule = get_object_or_404(DailySchedule, job=job)
        try:
            schedule = update_schedule(schedule, request.data)
        except ScoutError as exc:
            return Response(error_payload(exc), status=error_status(exc))
        return Response(schedule_payload(schedule))


class ScheduleOccurrencesView(BaseAPIView):
    permission_classes = [IsAuthenticated, CanViewScout]

    def get(self, request, public_id):
        job = get_object_or_404(jobs_for(request.user), public_id=public_id)
        schedule = get_object_or_404(DailySchedule, job=job)
        rows = schedule.occurrences.select_related('revision', 'run').order_by('-local_date', '-public_id')
        try:
            try:
                limit = int(request.query_params.get('limit', '50'))
            except ValueError:
                limit = 0
            if not 1 <= limit <= 200:
                raise ScoutError('invalid_limit', 'Размер порции должен быть от 1 до 200')
            if 'cursor' in request.query_params:
                day, uid = _read_cursor(request.query_params['cursor'], schedule)
                rows = rows.filter(Q(local_date__lt=day) | Q(local_date=day, public_id__lt=uid))
        except ScoutError as exc:
            return Response(error_payload(exc), status=error_status(exc))
        page = list(rows[:limit + 1])
        cursor = None
        if len(page) > limit:
            last = page[limit - 1]
            cursor = signing.dumps(
                [str(schedule.public_id), last.local_date.isoformat(), str(last.public_id)], salt=_CURSOR_SALT,
            )
        return Response({'occurrences': [occurrence_payload(row) for row in page[:limit]], 'next_cursor': cursor})


def _read_cursor(raw, schedule):
    try:
        if len(raw) > 512:
            raise ValueError
        values = signing.loads(raw, salt=_CURSOR_SALT)
        if not isinstance(values, list) or len(values) != 3 or values[0] != str(schedule.public_id):
            raise ValueError
        return date.fromisoformat(values[1]), UUID(values[2])
    except (signing.BadSignature, TypeError, ValueError):
        raise ScoutError('invalid_cursor', 'Курсор не соответствует этому расписанию') from None
