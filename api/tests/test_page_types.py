"""SPEC-002 через API, очередь и тестовый HTTP-каталог."""

import csv
import io
import json
import os
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from ..models import Run
from ..services.tasks_exec import publish_ready
from ..tasks import execute_scout_task
from .fixtures.spec002_catalog import CatalogServer, archive_type, catalog_plan, prefix


class PageTypeTests(TestCase):
    def setUp(self):
        self.site = CatalogServer()
        thread = Thread(target=self.site.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.site.server_close)
        self.addCleanup(self.site.shutdown)
        self.enterContext(patch.dict(os.environ, {
            'SCOUT_TASK_RUNNER': 'inline',
            'SCOUT_TRUSTED_FETCH_ENDPOINTS': f'127.0.0.1:{self.site.server_port}',
        }))
        self.client = APIClient()
        self.client.force_authenticate(get_user_model().objects.create_superuser(username='scout-spec002'))
        self.plan = catalog_plan(self.site.origin)

    def _create(self):
        response = self.client.post('/api/scout/jobs/', self.plan, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def _explore(self, job):
        response = self.client.post(f"/api/scout/jobs/{job['public_id']}/explore/")
        self.assertEqual(response.status_code, 202, response.data)
        run_id = response.data['public_id']
        publish_ready(run_id)
        return f'/api/scout/runs/{run_id}/', run_id

    def _collect(self, path, run_id):
        self.assertEqual(self.client.post(path + 'approve/').status_code, 200)
        self.assertEqual(self.client.post(path + 'start/').status_code, 202)
        publish_ready(run_id)
        return self.client.get(path).data

    def test_catalog_preview_evidence_exports_and_delivery_retry(self):
        self.plan['crawl']['sitemap_url'] = self.site.origin + '/sitemap.xml'
        path, run_id = self._explore(self._create())
        preview = self.client.get(path + '?value_format=typed_v1').data
        self.assertTrue(preview['page_type_preview']['can_approve'])
        self.assertEqual([page['outcome'] for page in preview['page_type_preview']['pages']],
                         ['discovery_only', 'extracted'])
        self.assertNotIn('page_type_preview', self.client.get(path + '?summary=1').data)
        self.assertEqual(preview['record_count'], 0)
        self.assertEqual(preview['preview'][0]['values']['title']['normalized'], 'Чайник')
        self.assertEqual(self.client.post(path + 'start/').data['code'], 'approval_required')
        self.assertNotIn('/sitemap.xml', self.site.hits)

        result = self._collect(path, run_id)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.site.hits['/products/a'], 1)
        self.assertEqual(self.site.hits['/products/b'], 1)
        self.assertEqual(self.site.hits['/sitemap.xml'], 1)
        run = Run.objects.get(public_id=run_id)
        self.assertEqual(run.job_revision.rules_revision.rules['page_types'], self.plan['crawl']['page_types'])
        task = run.tasks.filter(kind='extract').first()
        execute_scout_task(str(task.public_id), task.fencing_token - 1)

        records = self.client.get(path + 'records/?value_format=typed_v1&limit=10').data['records']
        self.assertEqual(len(records), 2)
        by_title = {row['values']['title']['normalized']: row for row in records}
        self.assertEqual(set(by_title), {'Чайник', 'Термос'})
        self.assertEqual(by_title['Термос']['values']['quantity']['typed']['value'], 0)
        self.assertEqual(by_title['Чайник']['values'], preview['preview'][0]['values'])
        for row in records:
            self.assertEqual(len(row['evidence']), 3)
            self.assertEqual(row['evidence'][0]['locator'], 'css:h1#0.0')
            self.assertEqual(row['evidence'][0]['rules_revision_public_id'],
                             str(run.job_revision.rules_revision.public_id))
            self.assertIn('/products/', row['evidence'][0]['source_url'])

        files = {}

        def save(local, storage):
            files[Path(storage).suffix] = Path(local).read_text(encoding='utf-8-sig')
            return storage

        with (
            patch('modules.scout.api.services.exporting.get_media_client') as media,
            patch('modules.scout.api.services.exporting.get_signed_media_url', return_value='/signed'),
        ):
            media.return_value.commit_local.side_effect = save
            for kind in ('json', 'csv'):
                response = self.client.post(path + 'export/', {'kind': kind, 'value_format': 'typed_v1'}, format='json')
                self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(json.loads(files['.json']), records)
        exported = {row['title']: row for row in csv.DictReader(io.StringIO(files['.csv']))}
        self.assertEqual(set(exported), set(by_title))
        self.assertEqual(exported['Чайник']['price'], '1250.00')
        self.assertEqual(exported['Термос']['quantity'], '0')

    def test_final_url_conflict_blocks_approval(self):
        self.plan['crawl']['preview_urls'][1] = self.site.origin + '/catalog/go'
        self.plan['crawl']['page_types'].append({
            'id': 'also_product', 'action': 'discover', 'match': [prefix('/products/a')],
        })
        path, _run_id = self._explore(self._create())
        diagnostics = self.client.get(path).data['page_type_preview']
        page = diagnostics['pages'][1]
        self.assertEqual(page['source_url'], self.site.origin + '/catalog/go')
        self.assertEqual(page['final_url'], self.site.origin + '/products/a?utm_source=fixture')
        self.assertEqual(page['type_ids'], ['product', 'also_product'])
        self.assertEqual(page['outcome'], 'ambiguous')
        self.assertEqual(page['error']['code'], 'page_type_ambiguous')
        self.assertFalse(diagnostics['can_approve'])
        rejected = self.client.post(path + 'approve/')
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.data['code'], 'page_type_preview_blocked')

    def test_new_conflict_during_collection_keeps_other_records_and_links(self):
        crawl = self.plan['crawl']
        crawl['visit'] += [prefix('/bridge/'), prefix('/archive/')]
        crawl['preview_urls'].append(self.site.origin + '/archive/c')
        crawl['page_types'] += [archive_type(), {
            'id': 'also_product', 'action': 'discover', 'match': [prefix('/products/b')],
        }]
        path, run_id = self._explore(self._create())
        preview = self.client.get(path).data
        self.assertTrue(preview['page_type_preview']['can_approve'])
        self.assertEqual([row['values']['title']['normalized'] for row in preview['preview']], ['Чайник', 'Кружка'])
        result = self._collect(path, run_id)
        self.assertEqual(result['status'], 'completed_with_errors')
        self.assertEqual(result['record_count'], 2)
        self.assertEqual(self.site.hits['/bridge/'], 1)
        self.assertEqual(self.site.hits['/archive/c'], 1)
        failure, = [task for task in result['tasks'] if task['error_code']]
        self.assertEqual(failure['error_code'], 'page_type_ambiguous')
        self.assertIn('/products/b', failure['error_message'])

    def test_approval_requires_each_type_and_keeps_missing_values_distinct(self):
        crawl = self.plan['crawl']
        crawl['preview_urls'] = [self.site.origin + '/products/' + name for name in ('missing', 'empty', 'gone')]
        crawl['page_types'].append(archive_type())
        path, _run_id = self._explore(self._create())
        data = self.client.get(path + '?value_format=typed_v1').data
        diagnostics = data['page_type_preview']
        self.assertEqual([page['outcome'] for page in diagnostics['pages']], ['extracted', 'no_records', 'error'])
        self.assertEqual(diagnostics['pages'][2]['error']['code'], 'http_404')
        self.assertEqual(diagnostics['unverified_extract_type_ids'], ['archive'])
        self.assertFalse(diagnostics['can_approve'])
        row, = data['preview']
        self.assertEqual(row['values']['price']['typed']['status'], 'missing')
        self.assertEqual([item['field_path'] for item in row['evidence']], ['title'])
        self.assertEqual(self.client.post(path + 'approve/').data['code'], 'page_type_preview_blocked')

    def test_unknown_selector_field_and_plan_hash(self):
        job = self._create()
        url = f"/api/scout/jobs/{job['public_id']}/"
        selectors = self.plan['crawl']['page_types'][1]['selectors']
        selectors['cost'] = {'kind': 'css', 'selector': '.price'}
        rejected = self.client.patch(url, self.plan, format='json')
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.data['code'], 'invalid_page_types')
        self.assertEqual(rejected.data['path'], '/crawl/page_types/1/selectors/cost')
        del selectors['cost']
        selectors['title']['selector'] = 'h2'
        changed = self.client.patch(url, self.plan, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertNotEqual(changed.data['revision']['plan_hash'], job['revision']['plan_hash'])

    def test_bad_selector_is_reported_per_control_page(self):
        self.plan['crawl']['page_types'][1]['selectors']['title']['selector'] = 'h1['
        path, _run_id = self._explore(self._create())
        data = self.client.get(path).data
        self.assertEqual(data['preview'], [])
        page = data['page_type_preview']['pages'][1]
        self.assertEqual(page['outcome'], 'error')
        self.assertEqual(page['error']['code'], 'selector')
        self.assertEqual(self.client.post(path + 'approve/').data['code'], 'page_type_preview_blocked')

    def test_previously_approved_revision_cannot_bypass_new_preview(self):
        job = self._create()
        path, _run_id = self._explore(job)
        self.assertEqual(self.client.post(path + 'approve/').status_code, 200)
        self.assertEqual(self.client.post(path + 'cancel/').status_code, 200)
        self.site.pages['/products/a'] = self.site.pages['/products/empty']
        new_path, _run_id = self._explore(job)
        preview = self.client.get(new_path).data
        self.assertTrue(preview['approved'])
        self.assertFalse(preview['page_type_preview']['can_approve'])
        rejected = self.client.post(new_path + 'start/')
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.data['code'], 'page_type_preview_blocked')
