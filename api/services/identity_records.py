"""Атомарная запись наблюдений SKU под блокировкой запуска."""

import hashlib

from ..models import Evidence, Record
from .product_identity import merge_identity_state, observation_rank, product_key


def store_identity_rows(snapshot, revision, schema, rules, rows) -> None:
    drop_query = (revision.crawl or {}).get('drop_query')
    field_names = [field['name'] for field in revision.fields]
    evidence = []
    for row in rows:
        key = product_key(revision, row)
        index = row['observation_index']
        if key is not None:
            existing = Record.objects.select_related('snapshot').filter(run_id=snapshot.run_id, entity_key=key).first()
            storage_key = key
        else:
            storage_key = hashlib.sha256(f'{snapshot.public_id}:{index}'.encode('ascii')).hexdigest()
            existing = Record.objects.filter(
                snapshot=snapshot, schema_revision=schema, rules_revision=rules, identity_key=storage_key,
            ).first()
        state = merge_identity_state(
            existing.identity_state if existing else {}, row, grouped=key is not None, field_names=field_names,
        )
        if existing is None:
            existing = Record.objects.create(
                run_id=snapshot.run_id, snapshot=snapshot, schema_revision=schema, rules_revision=rules,
                identity_key=storage_key, entity_key=key, observation_index=index,
                identity_state=state, values=row['values'],
            )
        else:
            _update_record(existing, snapshot, row, state, drop_query)
        evidence.extend(
            Evidence(
                record=existing, snapshot=snapshot, observation_index=index, source_url=snapshot.source_url,
                field_path=item['field_path'], locator=item['locator'], raw_value=item['raw_value'],
                normalized_value=item['normalized_value'], extractor_id=item['extractor_id'],
                extractor_version=item['extractor_version'], typed_value=item.get('typed'),
            )
            for item in row['evidence']
        )
    Evidence.objects.bulk_create(evidence, batch_size=500, ignore_conflicts=True)


def _update_record(record, snapshot, row, state, drop_query) -> None:
    index = row['observation_index']
    changed = []
    if state != record.identity_state:
        record.identity_state = state
        changed.append('identity_state')
    if record.entity_key and observation_rank(snapshot, index, drop_query) < observation_rank(
        record.snapshot, record.observation_index, drop_query,
    ):
        record.snapshot = snapshot
        record.observation_index = index
        record.values = row['values']
        changed.extend(('snapshot', 'observation_index', 'values'))
    if changed:
        record.save(update_fields=changed)
