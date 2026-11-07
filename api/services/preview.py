"""Предпросмотр читает сохранённый снимок и не пишет записи результата."""

from .constants import TASK_FETCH
from .errors import ScoutError
from .html_extract import extract_html
from .page_types import ambiguous_type_error, effective_fields, matching_page_types
from .product_identity import merge_identity_state, observation_rank, product_key, public_identity
from .snapshot_store import read_snapshot_bytes
from .value_types import legacy_values, missing_typed_fields


def preview_urls(revision) -> list[str]:
    crawl = revision.crawl or {}
    if crawl.get('mode') == 'site':
        return (crawl.get('preview_urls') or revision.seed_urls)[:int(crawl.get('preview_pages') or 3)]
    return revision.seed_urls


def preview_rows(run, *, typed: bool = False) -> list[dict]:
    revision = run.job_revision
    observations = [
        (snapshot, row)
        for snapshot in run.snapshots.all()
        for row in _snapshot_rows(snapshot, revision, revision.fields)
    ]
    return _render_preview(observations, revision, typed=typed)


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
            _preview_matched_page(page, rows, verified, snapshot, revision, matches[0])
    unverified = [
        kind['id'] for kind in crawl['page_types'] if kind['action'] == 'extract' and kind['id'] not in verified
    ]
    return _render_preview(rows, revision, typed=typed), {
        'pages': pages,
        'unverified_extract_type_ids': unverified,
        'can_approve': not unverified and not any(page['error'] for page in pages),
    }


def _preview_matched_page(page, rows, verified, snapshot, revision, page_type):
    if page_type['action'] == 'discover':
        page['outcome'] = 'discovery_only'
        return
    fields = effective_fields(revision.fields, page_type)
    try:
        found = _snapshot_rows(snapshot, revision, fields, require_match=True)
    except ScoutError as exc:
        page.update(outcome='error', error={'code': exc.code, 'detail': str(exc)})
        return
    page.update(outcome='extracted' if found else 'no_records', row_count=len(found))
    if found:
        verified.add(page_type['id'])
        rows.extend((snapshot, row) for row in found)


def _snapshot_rows(snapshot, revision, fields, *, require_match=False):
    try:
        body = read_snapshot_bytes(snapshot.content_path, snapshot=snapshot)
    except (OSError, ValueError) as exc:
        raise ScoutError('snapshot', 'Снимок не прочитан') from exc
    return extract_html(
        body,
        fields,
        record=revision.record or None,
        content_type=snapshot.content_type,
        charset=snapshot.charset,
        require_match=require_match,
        sku_field=revision.identity['field'] if revision.identity else None,
    )


def _render_preview(observations, revision, *, typed):
    rules_public_id = str(revision.rules_revision.public_id) if typed else None
    if revision.identity:
        return _identity_preview(observations, revision, typed=typed, rules_public_id=rules_public_id)
    results = []
    for snapshot, row in observations:
        missing = missing_typed_fields(row['values']) if typed else set()
        results.append({
            'source_url': snapshot.source_url,
            'values': row['values'] if typed else legacy_values(row['values']),
            'evidence': [
                _typed_evidence(item, snapshot, rules_public_id) for item in row['evidence']
                if item['field_path'] not in missing
            ] if typed else [{**item, 'html_availability': snapshot.html_availability} for item in row['evidence']],
        })
    return results


def _identity_preview(observations, revision, *, typed, rules_public_id):
    drop_query = (revision.crawl or {}).get('drop_query')
    field_names = [field['name'] for field in revision.fields]
    groups = {}
    for snapshot, row in observations:
        key = product_key(revision, row)
        local_key = key or (snapshot.public_id, row['observation_index'])
        groups.setdefault(local_key, []).append((snapshot, row))

    results = []
    for local_key, group in groups.items():
        key = local_key if isinstance(local_key, str) else None
        group.sort(key=lambda pair: observation_rank(pair[0], pair[1]['observation_index'], drop_query))
        chosen_snapshot, chosen_row = group[0]
        state = {}
        evidence = []
        for position, (snapshot, row) in enumerate(group):
            state = merge_identity_state(state, row, grouped=key is not None, field_names=field_names)
            for item in row['evidence']:
                source = {**item, 'source_url': snapshot.source_url, 'selected': position == 0,
                          'html_availability': snapshot.html_availability}
                if typed:
                    source = _typed_evidence(source, snapshot, rules_public_id)
                else:
                    source.pop('typed', None)
                evidence.append(source)
        results.append({
            'source_url': chosen_snapshot.source_url,
            'identity': public_identity(key, state),
            'values': chosen_row['values'] if typed else legacy_values(chosen_row['values']),
            'evidence': evidence,
        })
    return results


def _typed_evidence(item, snapshot, rules_public_id):
    return {
        **item, 'source_url': snapshot.source_url, 'snapshot_public_id': str(snapshot.public_id),
        'rules_revision_public_id': rules_public_id,
        'html_availability': snapshot.html_availability,
    }
