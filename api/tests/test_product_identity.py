"""План, предпросмотр, задачи и Evidence нескольких наблюдений."""

import os
from threading import Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient

from ..models import Run
from ..services.html_extract import extract_html
from ..services.identity_records import store_identity_rows
from ..services.snapshot_store import read_snapshot_bytes
from ..services.tasks_exec import publish_ready
from .fixtures.spec001_catalog import IdentityCatalog, identity_plan, set_product


class ProductIdentityTests(TestCase):
    def setUp(self):
        self.site = IdentityCatalog()
        Thread(target=self.site.serve_forever, daemon=True).start()
        self.addCleanup(self.site.server_close)
        self.addCleanup(self.site.shutdown)
        self.enterContext(patch.dict(os.environ, {
            'SCOUT_TASK_RUNNER': 'inline',
            'SCOUT_TRUSTED_FETCH_ENDPOINTS': f'127.0.0.1:{self.site.server_port}',
        }))
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser(username='scout-spec001')
        self.client.force_authenticate(self.user)
        self.plan = identity_plan(self.site.origin)

    def _create(self, plan):
        response = self.client.post('/api/scout/jobs/', plan, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def _collect(self, job, *, page_counts=None):
        pending = self.client.post(f"/api/scout/jobs/{job['public_id']}/explore/")
        self.assertEqual(pending.status_code, 202, pending.data)
        run_id = pending.data['public_id']
        path = f'/api/scout/runs/{run_id}/'
        publish_ready(run_id)
        preview = self.client.get(path + '?value_format=typed_v1').data
        self.assertEqual(preview['record_count'], 0)
        if page_counts is not None:
            self.assertEqual([page['row_count'] for page in preview['page_type_preview']['pages']], page_counts)
        self.assertEqual(self.client.post(path + 'approve/').status_code, 200)
        self.assertEqual(self.client.post(path + 'start/').status_code, 202)
        publish_ready(run_id)
        self.assertEqual(self.client.get(path).data['status'], 'completed')
        rows = self.client.get(path + 'records/?value_format=typed_v1').data['records']
        return preview['preview'], rows, Run.objects.get(public_id=run_id), path

    def test_sku_evidence_and_prices_stay_with_their_runs(self):
        job = self._create(self.plan)
        self.assertEqual(job['revision']['identity'], self.plan['identity'])
        preview, first, _run, first_path = self._collect(job)
        for path in ('/products/k-01', '/sale/k-01'):
            set_product(self.site, path, 'K-01', '1 350,00')
        _preview, second, _run, _path = self._collect(job)
        by_sku = lambda rows: {row['values']['sku']['normalized']: row for row in rows}
        self.assertEqual(len(first), 3)
        self.assertEqual(len(second), 3)
        old, new = by_sku(first), by_sku(second)
        self.assertEqual(set(old), {'K-01', 'K-02', ''})
        self.assertNotEqual(old['K-01']['identity']['entity_key'], old['K-02']['identity']['entity_key'])
        self.assertEqual(old['K-01']['identity'], new['K-01']['identity'])
        self.assertNotEqual(old['K-01']['public_id'], new['K-01']['public_id'])
        self.assertEqual(old['K-01']['values']['price']['typed']['value']['amount'], '1250.00')
        self.assertEqual(new['K-01']['values']['price']['typed']['value']['amount'], '1350.00')
        self.assertEqual(old['']['identity'], {'entity_key': None, 'status': 'missing', 'conflicting_fields': []})
        self.assertEqual(len(old['']['evidence']), 2)
        self.assertEqual(len(old['K-01']['evidence']), 6)
        self.assertEqual(len(new['K-01']['evidence']), 6)
        self.assertEqual({item['source_url'] for item in old['K-01']['evidence']},
                         {self.site.origin + '/products/k-01', self.site.origin + '/sale/k-01'})
        self.assertEqual({item['source_url'] for item in old['K-01']['evidence'] if item['selected']},
                         {self.site.origin + '/products/k-01'})
        self.assertEqual(by_sku(preview)['K-01']['evidence'], old['K-01']['evidence'])
        self.assertEqual(self.client.get(first_path + 'records/?value_format=typed_v1').data['records'], first)
        legacy_view = self.client.get(first_path + 'records/').data['records']
        self.assertEqual(by_sku(legacy_view)['K-01']['identity'], old['K-01']['identity'])
        self.assertNotIn('typed', by_sku(legacy_view)['K-01']['evidence'][2])

    def test_conflict_and_reprocessed_snapshot_keep_one_record(self):
        set_product(self.site, '/sale/k-01', 'K-01', '1 300,00')
        self.plan['seed_urls'].reverse()
        job = self._create(self.plan)
        preview, result, run, path = self._collect(job)
        find_k01 = lambda rows: next(row for row in rows if row['values']['sku']['normalized'] == 'K-01')
        row = find_k01(result)
        self.assertEqual(row['identity']['conflicting_fields'], ['price'])
        self.assertEqual(find_k01(preview)['identity'], row['identity'])
        prices = {item['typed']['value']['amount']: item['selected'] for item in row['evidence']
                  if item['field_path'] == 'price'}
        self.assertEqual(prices, {'1250.00': True, '1300.00': False})
        snapshot = run.snapshots.get(source_url=self.site.origin + '/sale/k-01')
        revision = run.job_revision
        raw = extract_html(read_snapshot_bytes(snapshot.content_path), revision.fields,
                           charset=snapshot.charset, sku_field='sku')
        with transaction.atomic():
            Run.objects.select_for_update().get(pk=run.pk)
            store_identity_rows(snapshot, revision, revision.schema_revision, revision.rules_revision, raw)
        self.assertEqual(self.client.get(path + 'records/?value_format=typed_v1').data['records'], result)

    def test_legacy_format_and_validation(self):
        original = self._create({key: value for key, value in self.plan.items() if key != 'identity'})
        self.assertNotIn('identity', original['revision'])
        _preview, rows, _run, path = self._collect(original)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all('identity' not in row for row in rows))
        self.assertTrue(all('selected' not in item for row in rows for item in row['evidence']))
        url = f"/api/scout/jobs/{original['public_id']}/"
        changed = self.client.patch(url, self.plan, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertNotEqual(changed.data['revision']['plan_hash'], original['revision']['plan_hash'])
        self.plan['identity']['field'] = 'price'
        rejected = self.client.patch(url, self.plan, format='json')
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual((rejected.data['code'], rejected.data['path']), ('invalid_identity', '/identity/field'))
        other = get_user_model().objects.create_user(username='scout-other-catalog')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(path + 'records/?value_format=typed_v1').status_code, 404)

    def test_page_types_keep_observation_counts_and_use_their_sku_selectors(self):
        self.plan['crawl'] = {
            'mode': 'site', 'max_depth': 0, 'preview_pages': 4,
            'page_types': [
                {'id': 'product', 'match': [{'kind': 'prefix', 'pattern': '/products/'}], 'action': 'extract'},
                {'id': 'sale', 'match': [{'kind': 'prefix', 'pattern': '/sale/'}], 'action': 'extract',
                 'selectors': {'sku': {'kind': 'xpath', 'selector': '//span[@class="offer-code"]/text()'}}},
            ],
        }
        self.site.pages['/sale/k-01'] = self.site.pages['/sale/k-01'].replace('class="sku"', 'class="offer-code"')
        preview, rows, run, _path = self._collect(self._create(self.plan), page_counts=[1, 1, 1, 1])
        self.assertEqual(len(preview), 3)
        self.assertEqual(len(rows), 3)
        product = next(row for row in rows if row['values']['sku']['normalized'] == 'K-01')
        sku_sources = [item for item in product['evidence'] if item['field_path'] == 'sku']
        self.assertEqual(len(sku_sources), 2)
        self.assertTrue(sku_sources[1]['locator'].startswith('xpath:'))
        self.assertEqual(run.records.count(), 3)

    def test_sku_status_uses_all_matches_before_truncation(self):
        field = self.plan['fields'][0]
        cases = [
            ('<b class="sku"> </b>', 'missing', None, 1),
            ('<b class="sku">A</b><b class="sku">A</b>', 'ambiguous', None, 2),
            (f'<b class="sku">{"A" * 201}</b>', 'invalid', None, 1),
            ('<b class="sku">  000a  B </b>', 'resolved', '000a  B', 1),
        ]
        for html, status, sku, matches in cases:
            with self.subTest(status=status):
                row, = extract_html(html.encode(), [field], sku_field='sku')
                self.assertEqual(row['sku_match'], (status, sku))
                self.assertEqual(len(row['evidence']), matches)
