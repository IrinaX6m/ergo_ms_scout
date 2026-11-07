"""Контракт дерева: идентичность API-002, границы, курсоры и безопасное чтение."""

import json
from datetime import timedelta
from pathlib import Path
from time import time
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from lxml import html
from rest_framework.test import APIClient

from modules.scout.api.models import VisualSnapshot, Job, Run, Task, RetentionLease
from modules.scout.api.permissions import CanConfigureScout
from modules.scout.api.services.errors import ScoutError
from modules.scout.api.services.visual_rules import VisualDocument
from modules.scout.api.services.visual_tree import CURSOR_SALT, VisualTree, tree_version
from modules.scout.api.tree_views import _DOMReadThrottle, _DOMSearchThrottle

_CATALOG = Path(__file__).with_name('fixtures').joinpath('dom_catalog.html').read_bytes()
_BASE = '/api/scout/visual-snapshots/'


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'scout-dom-tests'}})
class VisualTreeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser(username='dom-owner')
        self.other = get_user_model().objects.create_superuser(username='dom-other')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.snapshot = self.make_snapshot()
        self.path = f'{_BASE}{self.snapshot.public_id}/'
        self.tree = self.path + 'tree/'
        self.version = tree_version(self.snapshot)

    def make_snapshot(self, body=_CATALOG, **kwargs):
        return VisualSnapshot.objects.create(
            user_public_id=self.user.public_id, source_url='https://catalog.example/',
            final_url='https://catalog.example/', body=body, charset='utf-8', status='ready', **kwargs,
        )

    def branch(self, **kwargs):
        return self.client.get(self.tree, {'tree_version': self.version, **kwargs})

    def search(self, **kwargs):
        return self.client.post(self.tree + 'search/', {'tree_version': self.version, 'q': 'price', **kwargs}, format='json')

    def assert_error(self, result, status, code):
        self.assertEqual(result.status_code, status, getattr(result, 'data', result.content))
        self.assertEqual(result.data['code'], code, result.data)
        self.assertEqual(result['Cache-Control'], 'no-store')

    def test_nodes_branches_path_around_and_api002_share_ids(self):
        legacy = self.client.get(self.path)
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.data['tree_version'], self.version)
        document = html.fromstring(legacy.data['html'])
        visible = {el.get('data-scout-node'): el for el in document.xpath('//*[@data-scout-node]')}
        root = self.client.get(self.tree)
        self.assertEqual((root.status_code, root.data['node_count'], root.data['max_depth']), (200, 10, 3))
        self.assertEqual(root.data['items'][0]['node_id'], 'n1')
        children = self.branch(parent_id='n1', limit=1)
        self.assertEqual(children.data['total_count'], 2)
        self.assertEqual(children.data['items'][0]['node_id'], 'n2')
        next_page = self.branch(parent_id='n1', limit=1, cursor=children.data['next_cursor'])
        self.assertEqual(next_page.data['items'][0]['node_id'], 'n7')
        previous = self.branch(parent_id='n1', limit=1, cursor=next_page.data['previous_cursor'])
        self.assertEqual(previous.data['items'], children.data['items'])
        around = self.branch(parent_id='n2', around_node_id='n6', limit=2)
        self.assertEqual([n['node_id'] for n in around.data['items']], ['n6'])
        image = around.data['items'][0]
        self.assertEqual((image['tag'], image['rendered_tag']), ('img', 'span'))
        self.assertEqual(image['text_preview'], 'Обложка блокнота')
        detail = self.client.get(self.tree + 'nodes/n5/', {'tree_version': self.version})
        self.assertEqual([n['node_id'] for n in detail.data['ancestors']], ['n1', 'n2'])
        self.assertEqual(detail.data['node']['child_index'], 1)
        self.assertEqual(detail.data['node']['text_preview'], '1250,00 ₽')
        for item in [*root.data['items'], *children.data['items'], image, detail.data['node']]:
            self.assertEqual(visible[item['node_id']].tag, item['rendered_tag'])
        checked = self.client.post(self.path + 'check/', {
            'record': {'node_id': 'n2'},
            'field': {'name': 'price', 'scope': 'record', 'many': False, 'node_id': 'n5'},
        }, format='json')
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.data['row_count'], 2)
        self.assertEqual(checked.data['rows'][1]['value'], {'raw': '', 'normalized': ''})
        self.assertEqual([row['match_count'] for row in checked.data['rows']], [1, 1])
        self.assert_error(self.client.post(self.path + 'check/', {'tree_version': 'dom-v1:' + '0' * 64}, format='json'),
                          409, 'tree_version_changed')

    def test_search_covers_unloaded_branches_normalizes_and_paginates(self):
        first = self.search(q='  PRICE  ', tag='SPAN', limit=1)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data['total_count'], 2)
        self.assertEqual(first.data['items'][0]['node_id'], 'n5')
        cursor = first.data['next_cursor']
        second = self.search(limit=1, tag='span', cursor=cursor)
        self.assertEqual(second.data['items'][0]['node_id'], 'n10')
        self.assertEqual(second.data['items'][0]['text_preview'], '')
        payload = signing.loads(cursor, salt=CURSOR_SALT)
        self.assertNotIn('price', json.dumps(payload))
        empty = self.search(q='несуществующее')
        self.assertEqual((empty.data['total_count'], empty.data['items']), (0, []))
        self.assertEqual(self.search(q='карандаш', tag='a').data['total_count'], 1)
        self.assertEqual(self.search(q='.*').data['total_count'], 0)
        self.assertEqual(self.search(q='product', tag='article').data['total_count'], 2)

    def test_cursor_binding_signature_expiry_and_version(self):
        cursor = self.branch(parent_id='n1', limit=1).data['next_cursor']
        for parameters in ({'parent_id': 'n1', 'limit': 2}, {'parent_id': 'n2', 'limit': 1}):
            self.assert_error(self.branch(cursor=cursor, **parameters), 400, 'invalid_cursor')
        self.assert_error(self.branch(parent_id='n1', limit=1, cursor=cursor[:-1] + '!'), 400, 'invalid_cursor')
        with patch('django.core.signing.time.time', return_value=time() + 901):
            self.assert_error(self.branch(parent_id='n1', limit=1, cursor=cursor), 400, 'cursor_expired')
        search_cursor = self.search(limit=1).data['next_cursor']
        self.assert_error(self.search(limit=1, q='product', cursor=search_cursor), 400, 'invalid_cursor')
        other_snapshot = self.make_snapshot()
        foreign = self.client.get(f'{_BASE}{other_snapshot.public_id}/tree/', {
            'tree_version': tree_version(other_snapshot), 'parent_id': 'n1', 'limit': 1, 'cursor': cursor,
        })
        self.assert_error(foreign, 400, 'invalid_cursor')
        with patch('modules.scout.api.services.visual_tree.TREE_SCHEMA_VERSION', b'new-schema'):
            self.assert_error(self.branch(parent_id='n1', limit=1, cursor=cursor), 409, 'tree_version_changed')
        self.assertEqual(tree_version(self.snapshot), self.version)

    def test_owner_expiry_and_loading_checked_before_search_body(self):
        missing = self.client.get(f'{_BASE}{uuid4()}/tree/')
        self.assert_error(missing, 404, 'snapshot_not_found')
        self.client.force_authenticate(self.other)
        foreign = self.client.post(self.tree + 'search/', b'invalid JSON', content_type='application/json')
        self.assertEqual(foreign.data, missing.data)
        self.assert_error(foreign, 404, 'snapshot_not_found')
        self.client.force_authenticate(self.user)
        VisualSnapshot.objects.filter(pk=self.snapshot.pk).update(created_at=timezone.now() - timedelta(hours=2))
        expired = self.client.get(self.tree)
        self.assertEqual(expired.data, missing.data)
        VisualSnapshot.objects.filter(pk=self.snapshot.pk).update(created_at=timezone.now(), status='queued')
        self.assert_error(self.client.get(self.tree), 409, 'snapshot_not_ready')
        VisualSnapshot.objects.filter(pk=self.snapshot.pk).update(status='failed', error_code='too_large')
        self.assert_error(self.client.get(self.tree), 409, 'snapshot_not_ready')

    def test_queries_and_node_relations_are_strict(self):
        for parameters in ({'limit': 101}, {'limit': 0}, {'limit': '1.5'}, {'limit': 'true'},
                           {'parent_id': ''}, {'extra': 1}, {'tree_version': 'wrong'}):
            self.assert_error(self.branch(**parameters), 400, 'invalid_query')
        self.assert_error(self.client.get(self.tree + '?limit=1&limit=2'), 400, 'invalid_query')
        self.assert_error(self.client.get(self.tree, {'parent_id': 'n1'}), 400, 'invalid_query')
        self.assert_error(self.branch(parent_id='n1', around_node_id='n5'), 400, 'node_not_child')
        self.assert_error(self.branch(parent_id='n999'), 404, 'node_not_found')
        self.assert_error(self.branch(parent_id='n1', around_node_id='n7', cursor='x'), 400, 'invalid_query')
        self.assert_error(self.client.get(self.tree + 'nodes/n0/', {'tree_version': self.version}), 400, 'invalid_query')
        leaf = self.branch(parent_id='n5')
        self.assertEqual((leaf.data['total_count'], leaf.data['items'], leaf.data['next_cursor']), (0, [], None))

    def test_search_body_limits_types_and_safe_errors(self):
        for parameters in ({'q': ''}, {'q': 'a'}, {'q': None}, {'q': ['price']},
                           {'q': 'x' * 101}, {'limit': True}, {'limit': '2'}, {'cursor': None},
                           {'tag': ''}, {'tag': None}, {'tag': []}, {'extra': 1}):
            self.assert_error(self.search(**parameters), 400, 'invalid_query')
        self.assert_error(self.client.post(self.tree + 'search/', b'{}', content_type='text/plain'), 415, 'unsupported_media_type')
        self.assert_error(self.client.post(self.tree + 'search/', b'{', content_type='application/json'), 400, 'invalid_query')
        invalid_unicode = json.dumps({'tree_version': self.version, 'q': '\ud800x'}).encode('ascii')
        self.assert_error(self.client.post(self.tree + 'search/', invalid_unicode, content_type='application/json'), 400, 'invalid_query')
        self.assert_error(self.client.post(self.tree + 'search/', b'{"q":"aa","q":"bb"}', content_type='application/json'), 400, 'invalid_query')
        self.assert_error(self.client.post(self.tree + 'search/', b'x' * 4097, content_type='application/json'), 413, 'request_too_large')
        sentinel = 'private-query-marker'
        with patch('modules.scout.api.tree_views.VisualTree', side_effect=RuntimeError(sentinel)), self.assertLogs('modules.scout', level='ERROR') as log:
            response = self.branch()
        self.assert_error(response, 500, 'internal_error')
        self.assertNotIn(sentinel, response.content.decode() + str(log.output))

    def test_metadata_is_limited_and_no_attributes_or_resources_escape(self):
        body = ('<main id="bad:id" class="valid invalid:class ' + ' '.join('class' + str(i) for i in range(10)) + '">' +
                '<script>secret-script-value</script><input type="password" value="secret-form-value">'
                '<img src="https://secret.test/" alt="&lt;b&gt;literal&lt;/b&gt;">' + '😀' * 121 + '</main>').encode()
        snapshot = self.make_snapshot(body)
        result = self.client.get(f'{_BASE}{snapshot.public_id}/tree/')
        self.assertEqual(result.status_code, 200, result.data)
        item = result.data['items'][0]
        self.assertIsNone(item['element_id'])
        self.assertEqual(len(item['classes']), 8)
        self.assertTrue(item['metadata_limited'])
        self.assertLessEqual(len(item['text_preview']), 120)
        serialized = json.dumps(result.data, ensure_ascii=False)
        for forbidden in ('secret-script-value', 'secret-form-value', 'secret.test', 'invalid:class'):
            self.assertNotIn(forbidden, serialized)
        allowed = {'node_id','parent_id','child_index','depth','tag','rendered_tag','element_id','classes','text_preview','children_count','metadata_limited'}
        self.assertEqual(set(item), allowed)
        self.assertLess(len(result.content), 256 * 1024)

    def test_depth_limit_does_not_break_old_snapshot_or_check(self):
        snapshot = self.make_snapshot(('<main>' + '<div>' * 65 + 'deep' + '</div>' * 65 + '</main>').encode())
        path = f'{_BASE}{snapshot.public_id}/'
        legacy = self.client.get(path)
        self.assertEqual(legacy.status_code, 200)
        self.assertIn('deep', legacy.data['html'])
        self.assert_error(self.client.get(path + 'tree/'), 422, 'tree_depth_exceeded')
        for extra in ({}, {'tree_version': legacy.data['tree_version']}):
            checked = self.client.post(path + 'check/', {'record': {'kind': 'css', 'selector': 'main'}, **extra}, format='json')
            self.assertEqual(checked.status_code, 200, checked.data)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, 'ready')

    def test_ten_thousand_nodes_are_complete_and_larger_tree_is_refused(self):
        body = ('<main>' + '<span>x</span>' * 9999 + '</main>').encode()
        snapshot = self.make_snapshot(body)
        tree = VisualTree(VisualDocument(body, 'utf-8'), snapshot)
        first = tree.branch({'parent_id': 'n1', 'limit': '100'})
        ids = []
        page = first
        while True:
            ids.extend(item['node_id'] for item in page['items'])
            if page['next_cursor'] is None:
                break
            page = tree.branch({'parent_id': 'n1', 'limit': '100', 'cursor': page['next_cursor']})
        self.assertEqual(ids, ['n' + str(i) for i in range(2, 10001)])
        detail = tree.detail('n10000')
        self.assertEqual(detail['node']['child_index'], 9998)
        self.assertEqual(len(tree.search({'limit': 100}, 'span', None)['items']), 100)
        too_many = self.make_snapshot(('<main>' + '<span>x</span>' * 10000 + '</main>').encode())
        self.assert_error(self.client.get(f'{_BASE}{too_many.public_id}/tree/'), 422, 'tree_too_large')

    def test_empty_tree_prefix_whitespace_and_no_side_effects(self):
        body = b'<main>x<b> A </b> y<i>B</i>C</main>'
        snapshot = self.make_snapshot(body)
        result = self.client.get(f'{_BASE}{snapshot.public_id}/tree/')
        self.assertEqual(result.data['items'][0]['text_preview'], 'x A yBC')
        empty = self.make_snapshot(b'<html><body>Only text</body></html>')
        result = self.client.get(f'{_BASE}{empty.public_id}/tree/')
        self.assertEqual((result.data['node_count'], result.data['max_depth'], result.data['items']), (0, None, []))
        created_at = self.snapshot.created_at
        with patch('modules.scout.api.services.visual_snapshots.fetch_public_html') as fetch, patch('modules.scout.api.tasks.load_visual_snapshot.apply_async') as publish:
            self.branch()
            self.search()
        fetch.assert_not_called()
        publish.assert_not_called()
        self.assertEqual((Job.objects.count(), Run.objects.count(), Task.objects.count(), RetentionLease.objects.count()), (0, 0, 0, 0))
        self.snapshot.refresh_from_db()
        self.assertEqual(self.snapshot.created_at, created_at)

    def test_permissions_no_store_and_throttles(self):
        anonymous = APIClient()
        self.assert_error(anonymous.get(self.tree), 401, 'authentication_failed')
        with patch.object(CanConfigureScout, 'has_permission', return_value=False):
            self.assert_error(self.client.get(self.tree), 403, 'permission_denied')
        cache.clear()
        with patch.object(_DOMReadThrottle, 'rate', '2/minute'):
            self.assertEqual(self.branch().status_code, 200)
            self.assertEqual(self.branch().status_code, 200)
            limited = self.branch()
            self.assert_error(limited, 429, 'throttled')
            self.assertIn('Retry-After', limited)
        cache.clear()
        with patch.object(_DOMSearchThrottle, 'rate', '2/minute'):
            self.assertEqual(self.search().status_code, 200)
            self.assertEqual(self.search().status_code, 200)
            self.assert_error(self.search(), 429, 'throttled')

    def test_storage_and_response_limits_are_fail_closed(self):
        with patch('modules.scout.api.tree_views.read_resource', side_effect=ScoutError('storage_unavailable', 'Хранилище недоступно')):
            self.assert_error(self.branch(), 503, 'storage_unavailable')
        with patch('modules.scout.api.tree_views.MAX_RESPONSE_BYTES', 10):
            self.assert_error(self.branch(), 422, 'tree_too_large')
