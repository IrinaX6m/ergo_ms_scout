"""Предпросмотр читает сохранённый снимок и не пишет записи результата."""

from .errors import ScoutError
from .html_extract import extract_html
from .snapshot_store import read_snapshot_bytes
from .value_types import legacy_values, missing_typed_fields


def preview_rows(run, *, typed: bool = False) -> list[dict]:
    revision = run.job_revision
    rules = revision.fields
    record = revision.record or None
    rules_public_id = str(revision.rules_revision.public_id) if typed else None
    rows = []
    for snapshot in run.snapshots.all():
        try:
            body = read_snapshot_bytes(snapshot.content_path)
        except (OSError, ValueError) as exc:
            raise ScoutError('snapshot', 'Снимок не прочитан') from exc
        for row in extract_html(
            body,
            rules,
            record=record,
            content_type=snapshot.content_type,
            charset=snapshot.charset,
        ):
            values = row['values']
            evidence = row['evidence']
            if typed:
                missing = missing_typed_fields(values)
                evidence = [
                    {
                        **item,
                        'source_url': snapshot.source_url,
                        'snapshot_public_id': str(snapshot.public_id),
                        'rules_revision_public_id': rules_public_id,
                    }
                    for item in evidence if item['field_path'] not in missing
                ]
            rows.append({
                'source_url': snapshot.source_url,
                'values': values if typed else legacy_values(values),
                'evidence': evidence,
            })
    return rows
