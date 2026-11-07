"""Сравнение сохранённых результатов по ключам товара SPEC-001."""

import re
from decimal import Decimal
from heapq import merge
from itertools import groupby
from operator import itemgetter

from django.core import signing
from django.db.models import Count, Prefetch, Q
from django.db.models.fields.json import KeyTransform
from django.utils.translation import gettext as _

from ..models import Evidence, Record
from ..present import record_payload
from .constants import RUN_COMPLETED, RUN_COMPLETED_WITH_ERRORS, TASK_FAILED
from .errors import ScoutError
from .retention_locks import renew_read_leases

_COMPARE_STATUSES = (RUN_COMPLETED, RUN_COMPLETED_WITH_ERRORS)
_CHANGE_STATUSES = ('changed', 'unchanged', 'uncertain', 'added', 'not_seen_before', 'not_seen', 'not_checked')
_CURSOR_SALT = 'scout.run_comparison.v1'
_ENTITY_KEY = re.compile(r'[a-f0-9]{64}')


def compare_runs(base, target, *, field, limit, cursor) -> dict:
    from .retention_locks import read_results

    with read_results(base, target, comparison=True):
        return _compare_runs(base, target, field=field, limit=limit, cursor=cursor)


def _compare_runs(base, target, *, field, limit, cursor) -> dict:
    field_rule = _validate_pair(base, target, field)
    cursor_context = [str(base.public_id), str(target.public_id), field]
    after_key = _cursor_key(cursor, cursor_context)
    base_summary = _run_summary(base)
    target_summary = _run_summary(target)
    counts = dict.fromkeys(_CHANGE_STATUSES, 0)
    page = []
    for key, before, after in _keyed_pairs(base, target, field):
        renew_read_leases()
        status = _change_status(before, after, field, field_rule, base_summary, target_summary)
        counts[status] += 1
        if status != 'unchanged' and (after_key is None or key > after_key) and len(page) <= limit:
            page.append((key, status, before[0] if before else None, after[0] if after else None))
    has_more = len(page) > limit
    page = page[:limit]
    records = _page_records(page, field)
    profile = target.job_revision.identity
    return {
        'job_public_id': str(target.job_revision.job.public_id),
        'field': field,
        'base': base_summary,
        'target': target_summary,
        'counts': counts,
        'changes': [
            _change_payload(key, status, records.get(before_id), records.get(after_id), field, profile)
            for key, status, before_id, after_id in page
        ],
        'next_cursor': signing.dumps([*cursor_context, page[-1][0]], salt=_CURSOR_SALT) if has_more else None,
    }


def _validate_pair(base, target, field) -> dict:
    if base.pk == target.pk:
        raise ScoutError('invalid_comparison', _('Выберите два разных запуска'))
    if base.status not in _COMPARE_STATUSES or target.status not in _COMPARE_STATUSES:
        raise ScoutError('comparison_not_ready', _('Оба сбора должны завершиться'))
    base_revision, target_revision = base.job_revision, target.job_revision
    if (
        base_revision.job_id != target_revision.job_id
        or base_revision.plan_hash != target_revision.plan_hash
        or any((revision.identity or {}).get('kind') not in ('sku','field','url') for revision in (base_revision, target_revision))
    ):
        raise ScoutError('comparison_incompatible', _('Нужны запуски одного плана с профилем ключа'))
    if base.started_at >= target.started_at:
        raise ScoutError('invalid_comparison', _('Исходный сбор должен начаться раньше повторного'))
    rule = next((rule for rule in target_revision.fields if rule['name'] == field), None)
    if rule is None or rule.get('many'):
        raise ScoutError('invalid_comparison', _('Укажите одиночное поле из плана'))
    return rule


def _cursor_key(cursor, context) -> str | None:
    if cursor is None:
        return None
    if len(cursor) <= 512:
        try:
            value = signing.loads(cursor, salt=_CURSOR_SALT)
        except (signing.BadSignature, ValueError):
            value = None
        if isinstance(value, list) and len(value) == 4 and value[:3] == context:
            if isinstance(value[3], str) and _ENTITY_KEY.fullmatch(value[3]):
                return value[3]
    raise ScoutError('invalid_cursor', _('Курсор не соответствует этому сравнению'))


def _run_summary(run) -> dict:
    complete = run.status == RUN_COMPLETED and not run.stop_reason
    return {
        'run_public_id': str(run.public_id),
        'status': run.status,
        'completeness': 'complete' if complete else 'partial',
        'stop_reason': run.stop_reason,
        'failed_tasks': run.tasks.filter(status=TASK_FAILED).count(),
        **run.records.aggregate(
            record_count=Count('pk'), unkeyed_records=Count('pk', filter=Q(entity_key__isnull=True)),
        ),
    }


def _keyed_pairs(base, target, field):
    def keyed_rows(run, side):
        rows = run.records.filter(entity_key__isnull=False).order_by('entity_key').values_list(
            'entity_key', 'pk', KeyTransform(field, 'values'), KeyTransform('conflicting_fields', 'identity_state'),
        )
        return ((key, side, (pk, value, conflicts)) for key, pk, value, conflicts in rows.iterator(chunk_size=500))

    key_of = itemgetter(0)
    ordered = merge(keyed_rows(base, 'base'), keyed_rows(target, 'target'), key=key_of)
    for key, group in groupby(ordered, key=key_of):
        sides = {side: row for _, side, row in group}
        yield key, sides.get('base'), sides.get('target')


def _change_status(before, after, field, field_rule, base_summary, target_summary) -> str:
    if before is None:
        return 'added' if base_summary['completeness'] == 'complete' else 'not_seen_before'
    if after is None:
        return 'not_seen' if target_summary['completeness'] == 'complete' else 'not_checked'
    old = _comparable_value(before, field, field_rule)
    new = _comparable_value(after, field, field_rule)
    if old is None or new is None:
        return 'uncertain'
    return 'unchanged' if old == new else 'changed'


def _comparable_value(row, field, field_rule):
    _, value, conflicts = row
    if value is None or field in (conflicts or []):
        return None
    conversion = field_rule.get('conversion')
    if not conversion:
        return value['normalized'] or None
    cell = value.get('typed') or {}
    if cell.get('status') != 'ok':
        return None
    typed = cell['value']
    if conversion['type'] == 'money':
        return Decimal(typed['amount']), typed['currency']
    return typed


def _page_records(page, field):
    ids = {pk for _, _, before, after in page for pk in (before, after) if pk is not None}
    if not ids:
        return {}
    evidence = Evidence.objects.filter(field_path=field).select_related('snapshot')
    return Record.objects.select_related('rules_revision').prefetch_related(
        Prefetch('evidence', queryset=evidence),
    ).in_bulk(ids)


def _change_payload(key, status, before, after, field, profile) -> dict:
    return {
        'entity_key': key,
        **({'sku': (after or before).values[profile['field']]['raw'].strip()} if profile['kind']=='sku'
           else {'key':{'kind':profile['kind'],'value':(after or before).identity_state.get('key_value')}}),
        'status': status,
        'before': _side_payload(before, field),
        'after': _side_payload(after, field),
    }


def _side_payload(record, field) -> dict | None:
    if record is None:
        return None
    payload = record_payload(record, typed=True)
    value = payload['values'].get(field)
    evidence = payload['evidence']
    if field in payload['identity']['conflicting_fields']:
        state = 'conflict'
    elif value is None:
        state = 'missing'
    elif 'typed' in value:
        state = value['typed']['status']
    elif value['normalized']:
        state = 'ok'
    else:
        state = 'empty' if any(item['selected'] for item in evidence) else 'missing'
    return {'record_public_id': payload['public_id'], 'value': value, 'state': state, 'evidence': evidence}
