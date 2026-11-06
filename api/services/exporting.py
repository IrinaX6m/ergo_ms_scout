"""Выгрузка завершённого сбора в media_api."""

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import indent

from django.utils.translation import gettext as _

from src.core.utils.media_client import get_media_client
from src.core.utils.media_signing import get_signed_media_url

from ..models import ExportArtifact
from ..present import record_payload
from .constants import RUN_COMPLETED, RUN_COMPLETED_WITH_ERRORS
from .errors import ScoutError

EXPORT_BATCH_SIZE = 200


def export_run(*, run, kind: str):
    if run.status not in (RUN_COMPLETED, RUN_COMPLETED_WITH_ERRORS):
        raise ScoutError('invalid_state', _('Выгрузка доступна после завершения сбора'))
    if kind not in ('json', 'csv'):
        raise ScoutError('invalid', _('Формат выгрузки: json или csv'))
    records = run.records.order_by('created_at', 'pk')
    filename = f'records.{kind}'
    storage_path = f'scout/exports/{run.public_id}/{filename}'
    try:
        with TemporaryDirectory(prefix='scout-export-') as temporary:
            local_path = Path(temporary) / filename
            if kind == 'json':
                with local_path.open('w', encoding='utf-8', newline='') as output:
                    _write_json(records, output)
            else:
                with local_path.open('w', encoding='utf-8-sig', newline='') as output:
                    _write_csv(records, output)
            stored = get_media_client().commit_local(str(local_path), storage_path)
    except Exception as exc:
        raise ScoutError('media', _('Не удалось записать файл выгрузки')) from exc
    artifact = ExportArtifact.objects.create(run=run, kind=kind, storage_path=stored)
    url = get_signed_media_url(stored, as_attachment=True)
    return artifact, url, filename


def _write_json(records, output) -> None:
    output.write('[')
    separator = '\n'
    for record in records.prefetch_related('evidence').iterator(chunk_size=EXPORT_BATCH_SIZE):
        output.write(separator)
        output.write(indent(json.dumps(record_payload(record), ensure_ascii=False, indent=2), '  '))
        separator = ',\n'
    output.write('\n]' if separator == ',\n' else ']')


def _write_csv(records, output) -> None:
    names = {}
    for values in records.values_list('values', flat=True).iterator(chunk_size=EXPORT_BATCH_SIZE):
        names.update(dict.fromkeys(values or {}))
    writer = csv.DictWriter(output, fieldnames=['public_id', *names])
    writer.writeheader()
    for record in records.iterator(chunk_size=EXPORT_BATCH_SIZE):
        row = {'public_id': str(record.public_id)}
        for name in names:
            cell = (record.values or {}).get(name) or {}
            row[name] = cell.get('normalized', '')
        writer.writerow(row)
