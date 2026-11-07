"""Ключ товара и правила выбора строки, общие для предпросмотра и сбора."""

import hashlib
import json

from .url_norm import resolve_url


def product_key(revision, row) -> str | None:
    status, sku = row['sku_match']
    if status != 'resolved':
        return None
    profile = revision.identity
    parts = ['sku-v1', str(revision.job.public_id), profile['namespace'], profile['field'], sku]
    payload = json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def observation_rank(snapshot, index, drop_query) -> tuple:
    source = snapshot.source_url
    final = snapshot.final_url or source
    return (
        resolve_url(final, final, drop_query)[0] or final,
        resolve_url(source, source, drop_query)[0] or source,
        index,
        snapshot.content_hash,
        source,
    )


def merge_identity_state(state, row, *, grouped: bool, field_names) -> dict:
    status, _sku = row['sku_match']
    reference = dict(state.get('reference', {}))
    conflicts = set(state.get('conflicting_fields', []))
    if grouped:
        for name, cell in row['values'].items():
            if name in conflicts:
                continue
            if typed := cell.get('typed'):
                value = typed['value'] if typed['status'] == 'ok' else None
            else:
                value = cell['normalized'] or None
            if value is None:
                continue
            if reference.setdefault(name, value) != value:
                conflicts.add(name)
                reference.pop(name)
    return {
        'status': status,
        'reference': reference,
        'conflicting_fields': [name for name in field_names if name in conflicts],
    }


def public_identity(key, state) -> dict:
    return {'entity_key': key, 'status': state['status'], 'conflicting_fields': state['conflicting_fields']}
