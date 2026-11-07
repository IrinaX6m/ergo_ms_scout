"""Явный ключ объекта и выбор строки, общие для предпросмотра и сбора."""

import hashlib
import json
from urllib.parse import urlsplit, urlunsplit, unquote_plus

from .url_norm import resolve_url, canonical_host


def product_key(revision, row) -> str | None:
    status, sku = row['sku_match']
    if status != 'resolved':
        return None
    profile = revision.identity
    parts = [profile['kind']+'-v1', str(revision.job.public_id), profile['namespace'], profile.get('field','final_url'), sku]
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


def merge_identity_state(state, row, *, grouped: bool, field_names, profile=None) -> dict:
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
        **({'kind':profile['kind'],'key_value':row['sku_match'][1]}
           if profile and profile['kind']!='sku' else {}),
    }


def public_identity(key, state) -> dict:
    return {'entity_key': key, 'status': state['status'], 'conflicting_fields': state['conflicting_fields'],
            **({'kind':state['kind'],'key_value':state['key_value']} if 'kind' in state else {})}


def identity_extract_options(snapshot, revision):
    profile = revision.identity
    if not profile:
        return {}
    if profile['kind'] != 'url':
        return {'sku_field':profile['field']}
    raw = snapshot.final_url or snapshot.source_url
    try:
        parts = urlsplit(raw)
        host = canonical_host(parts.hostname or '')
        if parts.scheme not in ('http','https') or not host or parts.username or parts.password:
            raise ValueError
        netloc = f'[{host}]' if ':' in host else host
        if parts.port and parts.port != (443 if parts.scheme=='https' else 80):
            netloc += f':{parts.port}'
        drop = set((revision.crawl or {}).get('drop_query') or [])
        query = '&'.join(piece for piece in parts.query.split('&')
                         if unquote_plus(piece.split('=',1)[0]) not in drop)
        normalized = urlunsplit((parts.scheme,netloc,parts.path or '/',query,''))
        if len(normalized)>2000:
            raise ValueError
    except (ValueError,TypeError):
        normalized = ''
    return {'identity_url':normalized}
