"""Настройки ежедневного расписания и неизменяемая история его версий."""

import re
from datetime import time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from src.core.integrations import bridge
from src.core.integrations.module_contracts import ADP_CHECK_MODULE_PERMISSION

from ..models import DailySchedule, Job, ScheduleRevision
from .errors import ScoutError
from .proxy_profiles import validate_revision
from .schedule_calendar import START_WINDOW_SECONDS, first_future_date, next_scheduled_at

_FIELDS = {'plan_revision_public_id', 'plan_hash', 'local_time', 'timezone', 'enabled'}
_TIME = re.compile(r'([01][0-9]|2[0-3]):[0-5][0-9]')
_HASH = re.compile(r'[a-f0-9]{64}')


def owner_can_schedule(owner) -> bool:
    return all(bridge.call(
        ADP_CHECK_MODULE_PERMISSION, user_public_id=str(owner), module_name='scout', permission_key=permission,
        default=False,
    ) is True for permission in ('scout_configure', 'scout_run'))


def current_revision(schedule):
    return schedule.revisions.select_related('plan_revision', 'schedule').get(number=schedule.version)


def create_schedule(job, body):
    with transaction.atomic():
        Job.objects.select_for_update().get(pk=job.pk)
        if DailySchedule.objects.filter(job=job).exists():
            raise ScoutError('schedule_exists', 'У задания уже есть расписание')
        values = _validate_body(job, body)
        schedule = DailySchedule.objects.create(job=job)
        append_revision(schedule, values, timezone.now())
    return schedule


def update_schedule(schedule, body):
    with transaction.atomic():
        locked = DailySchedule.objects.select_for_update().select_related('job').get(pk=schedule.pk)
        if not isinstance(body, dict) or type(body.get('expected_version')) is not int:
            raise ScoutError('invalid_schedule', 'Укажите версию настроек', path='/expected_version')
        if body['expected_version'] != locked.version:
            raise ScoutError('schedule_changed', 'Настройки расписания уже изменились')
        old = current_revision(locked)
        values = _validate_body(locked.job, body, old=old)
        append_revision(locked, values, timezone.now())
    return locked


def _validate_body(job, body, *, old=None):
    allowed = _FIELDS | ({'expected_version'} if old else set())
    if not isinstance(body, dict) or set(body) - allowed:
        raise ScoutError('invalid_schedule', 'Передайте настройки ежедневного расписания', path='/')
    if old is None and _FIELDS - body.keys():
        raise ScoutError('invalid_schedule', 'Заполните все поля расписания', path='/')
    if old and (('plan_revision_public_id' in body) != ('plan_hash' in body)):
        raise ScoutError('invalid_schedule', 'UUID версии и хеш меняются вместе', path='/plan_revision_public_id')
    try:
        plan_id = UUID(str(body.get('plan_revision_public_id', old.plan_revision.public_id if old else '')))
    except ValueError:
        raise ScoutError('invalid_schedule', 'Укажите UUID версии плана', path='/plan_revision_public_id') from None
    plan = get_object_or_404(job.revisions, public_id=plan_id)
    digest = body.get('plan_hash', old.plan_hash if old else None)
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ScoutError('invalid_schedule', 'Укажите хеш плана', path='/plan_hash')
    text = body.get('local_time', old.local_time.strftime('%H:%M') if old else None)
    if not isinstance(text, str) or not _TIME.fullmatch(text):
        raise ScoutError('invalid_schedule', 'Время задаётся как HH:MM', path='/local_time')
    zone = body.get('timezone', old.timezone if old else None)
    try:
        if not isinstance(zone, str) or len(zone) > 80:
            raise ValueError
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ScoutError('invalid_schedule', 'Укажите доступный часовой пояс IANA', path='/timezone') from None
    enabled = body.get('enabled', old.enabled if old else None)
    if type(enabled) is not bool:
        raise ScoutError('invalid_schedule', 'enabled принимает true или false', path='/enabled')
    if old is None or enabled or 'plan_revision_public_id' in body:
        if digest != plan.plan_hash or digest != plan.approved_plan_hash:
            raise ScoutError('approval_required', 'Выбранную версию плана нужно подтвердить')
    if enabled:
        if not owner_can_schedule(job.user_public_id):
            raise PermissionDenied('Владелец задания не может выполнять сборы по расписанию')
        validate_revision(plan.proxy_profile_revision_public_id, job.user_public_id)
    return {'plan_revision': plan, 'plan_hash': digest, 'local_time': time.fromisoformat(text),
            'timezone': zone, 'enabled': enabled}


def append_revision(schedule, values, now):
    previous = schedule.revisions.filter(number=schedule.version).first()
    if previous:
        previous.effective_until = now
        previous.save(update_fields=['effective_until'])
        schedule.version += 1
        schedule.save(update_fields=['version'])
    first = first_future_date(now, values['local_time'], values['timezone']) if values['enabled'] else None
    return ScheduleRevision.objects.create(
        schedule=schedule, number=schedule.version, effective_from=now,
        first_local_date=first, next_local_date=first, **values,
    )


def disable_schedule(revision, now):
    schedule = revision.schedule
    if schedule.version == revision.number:
        append_revision(schedule, {
            'plan_revision': revision.plan_revision, 'plan_hash': revision.plan_hash,
            'local_time': revision.local_time, 'timezone': revision.timezone, 'enabled': False,
        }, now)


def schedule_payload(schedule):
    revision = current_revision(schedule)
    due = next_scheduled_at(revision, timezone.now())
    return {
        'public_id': str(schedule.public_id), 'job_public_id': str(schedule.job.public_id),
        'version': schedule.version, 'plan_revision_public_id': str(revision.plan_revision.public_id),
        'plan_hash': revision.plan_hash, 'local_time': revision.local_time.strftime('%H:%M'),
        'timezone': revision.timezone, 'enabled': revision.enabled,
        'start_window_seconds': START_WINDOW_SECONDS, 'next_scheduled_at': due,
    }


def occurrence_payload(occurrence):
    return {
        'public_id': str(occurrence.public_id), 'schedule_version': occurrence.revision.number,
        'local_date': occurrence.local_date, 'scheduled_at': occurrence.scheduled_at,
        'processed_at': occurrence.processed_at, 'status': occurrence.status, 'reason': occurrence.reason,
        'run_public_id': str(occurrence.run.public_id) if occurrence.run_id else None,
    }
