"""Обнаружение карт сохраняет подтверждение плана, границы и общий барьер перед HTML."""

import copy
import os
from datetime import timedelta
from threading import Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from ..models import Run, Task
from ..services.plan import normalize_plan, plan_hash
from ..services.robots import robots_url, MAX_ROBOTS_BYTES
from ..services.tasks_exec import publish_ready, recover_expired_leases, run_one, _claim
from .fixtures.robots_catalog import RobotsCatalog, robots_plan


class RobotsSitemapTests(TestCase):
    def setUp(self):
        self.site = RobotsCatalog()
        Thread(target=self.site.serve_forever, daemon=True).start()
        self.addCleanup(self.site.server_close)
        self.addCleanup(self.site.shutdown)
        self.enterContext(patch.dict(os.environ, {'SCOUT_TASK_RUNNER': 'inline',
            'SCOUT_TRUSTED_FETCH_ENDPOINTS': f'127.0.0.1:{self.site.server_port}'}))
        self.user = get_user_model().objects.create_superuser(username='scout-robots')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def prepare(self, **crawl):
        plan = robots_plan(self.site.origin)
        plan['crawl'].update(crawl)
        response = self.client.post('/api/scout/jobs/', plan, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        uid = self.client.post(f"/api/scout/jobs/{response.data['public_id']}/explore/").data['public_id']
        publish_ready(uid)
        return Run.objects.get(public_id=uid), f'/api/scout/runs/{uid}/'

    def collect(self, **crawl):
        run, endpoint = self.prepare(**crawl)
        self.client.post(endpoint+'approve/')
        self.assertEqual(self.client.post(endpoint+'start/').status_code, 202)
        publish_ready(run.public_id)
        run.refresh_from_db()
        return run, endpoint

    def failed(self, code):
        run, _endpoint = self.collect()
        self.assertEqual(run.status, 'failed')
        self.assertEqual(run.tasks.get(status='failed').error_code, code)
        self.assertFalse(run.crawl_urls.exists())
        self.assertFalse(run.records.exists())
        return run

    def test_multiple_maps_index_gzip_and_duplicates_wait_for_confirmation(self):
        run, endpoint = self.prepare()
        self.assertEqual(self.site.hits['/robots.txt'], 0)
        self.assertEqual(self.client.post(endpoint+'start/').status_code, 409)
        self.client.post(endpoint+'approve/')
        self.client.post(endpoint+'start/')
        publish_ready(run.public_id)
        result = self.client.get(endpoint, {'summary': 1}).data
        self.assertEqual(result['status'], 'completed', result)
        scan = result['sitemap']
        self.assertEqual(scan['discovery'], 'robots')
        self.assertTrue(scan['robots_processed'] and scan['ready'])
        self.assertEqual(scan['maps_discovered'], 4)
        self.assertEqual(scan['maps_processed'], 4)
        self.assertEqual(run.tasks.filter(kind='sitemap').count(), 5)
        self.assertEqual(run.records.count(), 3)
        self.assertEqual(sum(row.evidence.count() for row in run.records.all()), 11)
        for path in ('/robots.txt', '/index.xml', '/one.xml.gz', '/nested.xml', '/two.xml'):
            self.assertEqual(self.site.hits[path], 1, path)
        self.assertFalse(run.snapshots.filter(source_url__contains='robots.txt').exists())
        before = (run.records.count(), run.tasks.count())
        for task in run.tasks.filter(kind='sitemap'):
            self.assertFalse(run_one(str(task.public_id), task.fencing_token))
        self.assertEqual(before, (run.records.count(), run.tasks.count()))

    def test_missing_empty_relative_html_and_invalid_utf8_fail_closed(self):
        self.site.robots_status = 404
        self.failed('http_404')
        self.site.robots_status = 200
        for body, code in ((b'User-agent: *\nDisallow: /', 'robots_no_sitemap'),
                           (b'Sitemap: /relative.xml', 'robots_invalid'),
                           (b'<html>Login</html>', 'robots_invalid'),
                           (b'Sitemap: https://example.org/\xff', 'robots_invalid'),
                           (b'Sitemap: ', 'robots_invalid')):
            self.site.robots_body = body
            self.failed(code)

    def test_transient_http_failure_retries_and_unavailable_exhausts(self):
        self.site.robots_status = [503, 200]
        run, _endpoint = self.collect()
        self.assertEqual(run.status, 'completed')
        self.assertEqual(self.site.hits['/robots.txt'], 2)
        self.site.robots_status = 503
        run = self.failed('http_503')
        self.assertEqual(run.tasks.get(idempotency_key='sitemap').attempt_count, 3)

    def test_map_error_and_scope_failure_leave_frontier_closed(self):
        for body, code in ((f'Sitemap: {self.site.origin}/broken.xml', 'sitemap_invalid'),
                           ('Sitemap: https://example.org/map.xml', 'sitemap_scope'),
                           ('Sitemap: http://127.0.0.1:1/map.xml', 'url_blocked'),
                           (f'Sitemap: {self.site.origin}/robots.txt', 'sitemap_cycle')):
            self.site.robots_body = body.encode()
            self.failed(code)

    def test_redirects_apply_network_and_host_scope_before_request(self):
        self.site.xml['/robots-alias.txt'] = ('https://example.org/robots.txt',)
        self.site.robots_status = 302
        self.site.robots_redirect = self.site.origin+'/robots-alias.txt'
        self.failed('redirect_scope')
        self.site.robots_redirect = 'http://127.0.0.1:1/robots.txt'
        self.failed('url_blocked')
        self.site.robots_redirect = self.site.origin+'/robots-ready.txt'
        self.site.xml['/robots-ready.txt'] = f'Sitemap: {self.site.origin}/one.xml.gz'
        run, _endpoint = self.collect()
        self.assertEqual(run.status, 'completed')
        self.assertEqual(run.tasks.filter(kind='sitemap').count(), 2)

    def test_robots_and_xml_share_budgets_page_limit_and_filters(self):
        run, _endpoint = self.collect(max_pages=2, visit=[{'kind': 'prefix', 'pattern': '/products/'}])
        self.assertEqual(run.status, 'completed')
        self.assertEqual(run.stop_reason, 'max_pages')
        self.assertEqual(run.crawl_urls.filter(state='done').count(), 2)
        self.assertFalse(run.snapshots.filter(source_url__contains='/sale/').exists())
        self.site.robots_body = b'#'+b'x'*MAX_ROBOTS_BYTES
        self.failed('too_large')
        self.site.robots_body = f'Sitemap: {self.site.origin}/one.xml.gz'.encode()
        with patch('modules.scout.api.services.sitemap_scan.MAX_XML_BYTES', 10):
            self.failed('too_large')
        self.site.robots_body = '\n'.join(f'Sitemap: {self.site.origin}/map{i}.xml' for i in range(21)).encode()
        self.failed('sitemap_limit')

    def test_lost_lease_pause_and_cancel_do_not_open_or_duplicate_frontier(self):
        run, endpoint = self.prepare()
        self.client.post(endpoint+'approve/')
        with patch('modules.scout.api.views.schedule_publish'):
            self.client.post(endpoint+'start/')
        root = run.tasks.get(idempotency_key='sitemap')
        claimed, token = _claim(str(root.public_id), root.fencing_token)
        Task.objects.filter(pk=root.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        recover_expired_leases()
        self.assertFalse(run_one(str(root.public_id), token))
        root.refresh_from_db()
        self.assertTrue(run_one(str(root.public_id), root.fencing_token))
        self.assertFalse(run.crawl_urls.exists())
        self.assertEqual(self.client.post(endpoint+'pause/').data['status'], 'paused')
        self.client.post(endpoint+'resume/')
        publish_ready(run.public_id)
        run.refresh_from_db()
        self.assertEqual(run.status, 'completed')
        self.assertEqual(self.site.hits['/robots.txt'], 1)
        run, endpoint = self.prepare()
        self.client.post(endpoint+'approve/')
        with patch('modules.scout.api.views.schedule_publish'):
            self.client.post(endpoint+'start/')
        root = run.tasks.get(idempotency_key='sitemap')
        self.assertTrue(run_one(str(root.public_id), root.fencing_token))
        self.client.post(endpoint+'cancel/')
        publish_ready(run.public_id)
        run.refresh_from_db()
        self.assertEqual(run.status, 'cancelled')
        self.assertFalse(run.crawl_urls.exists())

    def test_plan_validation_preserves_old_hash_and_builds_origin_robots_url(self):
        plan = robots_plan(self.site.origin)
        disabled = copy.deepcopy(plan)
        del disabled['title']
        disabled['crawl']['sitemap_from_robots'] = False
        absent = copy.deepcopy(disabled)
        del absent['crawl']['sitemap_from_robots']
        self.assertEqual(plan_hash(normalize_plan(**disabled)), plan_hash(normalize_plan(**absent)))
        self.assertEqual(robots_url('https://example.org/catalog/?a=1#x'), 'https://example.org/robots.txt')
        for crawl in ({'sitemap_from_robots': 'true'}, {'mode': 'pages'},
                      {'sitemap_url': self.site.origin+'/index.xml'}):
            invalid = copy.deepcopy(plan)
            invalid['crawl'].update(crawl)
            self.assertEqual(self.client.post('/api/scout/jobs/', invalid, format='json').status_code, 400)
        response = self.client.post('/api/scout/jobs/', {**plan, 'crawl': {**plan['crawl'], 'max_pages': 1000}}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['revision']['crawl']['max_pages'], 200)
