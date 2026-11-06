"""Тонкие задачи Celery. Состояние сбора живёт в базе, не в сообщении."""

import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from .models import Run, Task
from .services.constants import CLAIMABLE_RUN_STATUSES
from .services.tasks_exec import inline_runner, publish_ready, run_one
from .services.visual_snapshots import delete_expired_snapshots, load_snapshot

logger = logging.getLogger('celery.module.scout.tasks')
DISPATCH_REQUEST_TTL = timedelta(seconds=30)
DISPATCH_REQUEST_HEADER = 'scout_dispatch_requested_until'


def _clear_dispatch_request(run_id: str, requested_until) -> bool:
    return bool(Run.objects.filter(
        public_id=run_id, dispatch_requested_until=requested_until,
    ).update(dispatch_requested_until=None))


def _request_dispatch(run_id: str) -> None:
    now = timezone.now()
    requested_until = now + DISPATCH_REQUEST_TTL
    reserved = Run.objects.filter(public_id=run_id, status__in=CLAIMABLE_RUN_STATUSES).filter(
        Q(dispatch_requested_until__isnull=True) | Q(dispatch_requested_until__lte=now),
    ).update(dispatch_requested_until=requested_until)
    if not reserved:
        return
    try:
        dispatch_scout_pending.apply_async(
            args=[run_id], headers={DISPATCH_REQUEST_HEADER: requested_until.isoformat()},
        )
    except Exception:
        _clear_dispatch_request(run_id, requested_until)
        logger.exception('SCOUT не поставил сверку запуска %s в очередь', run_id)


@shared_task(name='modules.scout.api.tasks.execute_scout_task')
def execute_scout_task(task_public_id: str, fencing_token: int) -> dict:
    changed = run_one(str(task_public_id), int(fencing_token))
    if changed and not inline_runner():
        run_id = (
            Task.objects.filter(public_id=task_public_id)
            .values_list('run__public_id', flat=True)
            .first()
        )
        if run_id:
            _request_dispatch(str(run_id))
    return {'changed': bool(changed)}


@shared_task(bind=True, name='modules.scout.api.tasks.dispatch_scout_pending')
def dispatch_scout_pending(self, run_public_id: str = '') -> dict:
    requested_until = (self.request.headers or {}).get(DISPATCH_REQUEST_HEADER)
    # Снимаем отметку до сверки, чтобы завершившиеся во время неё задачи могли запросить следующую.
    if requested_until and not _clear_dispatch_request(run_public_id, requested_until):
        return {'ok': True}
    publish_ready(run_public_id or None)
    logger.info('SCOUT сверил очередь запуска %s', run_public_id or '*')
    return {'ok': True}


@shared_task(name='modules.scout.api.tasks.load_visual_snapshot', soft_time_limit=45, time_limit=55, ignore_result=True)
def load_visual_snapshot(public_id: str):
    load_snapshot(public_id)


@shared_task(name='modules.scout.api.tasks.clean_visual_snapshots', ignore_result=True)
def clean_visual_snapshots():
    delete_expired_snapshots()
    from .services.proxy_profiles import prune_proxy_credentials

    prune_proxy_credentials()
