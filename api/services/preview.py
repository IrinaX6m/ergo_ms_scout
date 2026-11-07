"""Предпросмотр читает сохранённый снимок и не пишет записи результата."""

from .constants import TASK_FETCH
from .errors import ScoutError
from .html_extract import extract_html
from .page_types import ambiguous_type_error, effective_fields, matching_page_types
from .snapshot_store import read_snapshot_bytes
from .value_types import legacy_values, missing_typed_fields


def preview_urls(revision) -> list[str]:
    crawl = revision.crawl or {}
    if crawl.get('mode') == 'site':
        return (crawl.get('preview_urls') or revision.seed_urls)[:int(crawl.get('preview_pages') or 3)]
    return revision.seed_urls


def preview_rows(run, *, typed: bool = False) -> list[dict]:
    revision = run.job_revision
    return [
        row
        for snapshot in run.snapshots.all()
        for row in _snapshot_rows(snapshot, revision, revision.fields, typed=typed)
    ]


def page_type_preview(run, *, typed: bool = False) -> tuple[list[dict], dict]:
    revision = run.job_revision
    crawl = revision.crawl
    snapshots = {snapshot.source_url: snapshot for snapshot in run.snapshots.all()}
    fetches = {task.payload['url']: task for task in run.tasks.all() if task.kind == TASK_FETCH}
    rows, pages = [], []
    verified = set()
    for url in preview_urls(revision):
        snapshot = snapshots.get(url)
        matches = matching_page_types(snapshot, crawl) if snapshot else []
        page = {
            'source_url': url,
            'final_url': (snapshot.final_url or snapshot.source_url) if snapshot else None,
            'type_ids': [page_type['id'] for page_type in matches],
            'outcome': 'unmatched',
            'row_count': 0,
            'error': None,
        }
        pages.append(page)
        if snapshot is None:
            task = fetches.get(url)
            page.update(outcome='error', error={
                'code': (task.error_code if task else '') or 'snapshot',
                'detail': (task.error_message if task else '') or 'Контрольный снимок не загружен',
            })
        elif len(matches) > 1:
            error = ambiguous_type_error(snapshot, matches)
            page.update(outcome='ambiguous', error={'code': error.code, 'detail': str(error)})
        elif matches:
            _preview_matched_page(page, rows, verified, snapshot, revision, matches[0], typed=typed)
    unverified = [
        kind['id'] for kind in crawl['page_types'] if kind['action'] == 'extract' and kind['id'] not in verified
    ]
    return rows, {
        'pages': pages,
        'unverified_extract_type_ids': unverified,
        'can_approve': not unverified and not any(page['error'] for page in pages),
    }


def _preview_matched_page(page, rows, verified, snapshot, revision, page_type, *, typed):
    if page_type['action'] == 'discover':
        page['outcome'] = 'discovery_only'
        return
    fields = effective_fields(revision.fields, page_type)
    try:
        found = _snapshot_rows(snapshot, revision, fields, typed=typed, require_match=True)
    except ScoutError as exc:
        page.update(outcome='error', error={'code': exc.code, 'detail': str(exc)})
        return
    page.update(outcome='extracted' if found else 'no_records', row_count=len(found))
    if found:
        verified.add(page_type['id'])
        rows.extend(found)


def _snapshot_rows(snapshot, revision, fields, *, typed, require_match=False):
    try:
        body = read_snapshot_bytes(snapshot.content_path)
    except (OSError, ValueError) as exc:
        raise ScoutError('snapshot', 'Снимок не прочитан') from exc
    rules_public_id = str(revision.rules_revision.public_id) if typed else None
    rows = []
    for row in extract_html(
        body,
        fields,
        record=revision.record or None,
        content_type=snapshot.content_type,
        charset=snapshot.charset,
        require_match=require_match,
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
