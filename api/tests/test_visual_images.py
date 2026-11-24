"""Скачивание по узлу, выбранному из визуального снимка владельца."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from modules.scout.api.models import VisualSnapshot
from modules.scout.api.permissions import CanConfigureScout
from modules.scout.api.services import visual_images
from modules.scout.api.services.errors import FetchError
from modules.scout.api.services.visual_tree import tree_version


class VisualImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_superuser(username='image-owner')
        cls.other = get_user_model().objects.create_superuser(username='image-other')
        cls.snapshot = VisualSnapshot.objects.create(
            user_public_id=cls.owner.public_id, source_url='https://catalog.example/start',
            final_url='https://catalog.example/books/book.html', status='ready', charset='utf-8',
            body=(
                b'<main><img alt="Cover" src="../covers/cover.png?size=500&amp;v=1">'
                b'<img src="data:image/gif;base64,AAAA" data-lazy-src="//cdn.example/real.png">'
                b'<img src="data:image/png;base64,AAAA"></main>'
            ),
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.path = f'/api/scout/visual-snapshots/{self.snapshot.public_id}/'
        self.query = {'tree_version': tree_version(self.snapshot), 'node_id': 'n2'}

    def image(self, **overrides):
        return self.client.get(self.path + 'image/', {**self.query, **overrides}, HTTP_ACCEPT='image/*')

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()['code'], code)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_only_explicit_download_reads_image_and_resolves_relative_to_final_page(self):
        file = {'body': b'png-bytes', 'content_type': 'image/png'}
        with patch.object(visual_images, 'fetch_public_image', return_value=file) as fetch:
            detail = self.client.get(self.path)
            self.assertNotIn('../covers/', detail.json()['html'])
            self.assertEqual(self.client.get(self.path + 'tree/').status_code, 200)
            self.assertEqual(self.client.head(self.path + 'image/', self.query).status_code, 405)
            fetch.assert_not_called()
            response = self.image()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.content, file['body'])
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="scout-n2.png"')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Cache-Control'], 'no-store')
        fetch.assert_called_once_with('https://catalog.example/covers/cover.png?size=500&v=1',
                                      timeout_seconds=10, max_bytes=8 * 1024 * 1024)

    def test_lazy_cdn_source_uses_the_saved_proxy_profile(self):
        revision = uuid4()
        VisualSnapshot.objects.filter(pk=self.snapshot.pk).update(proxy_profile_revision_public_id=revision)
        with (
            patch.object(visual_images, 'fetch_public_image') as direct,
            patch.object(visual_images, 'fetch_proxy_image', return_value={'body': b'jpg', 'content_type': 'image/jpeg'}) as proxy,
        ):
            response = self.image(node_id='n3')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="scout-n3.jpg"')
        proxy.assert_called_once_with('https://cdn.example/real.png', owner=self.owner.public_id, revision_id=revision,
                                      timeout_seconds=10, max_bytes=8 * 1024 * 1024)
        direct.assert_not_called()

    def test_invalid_and_stale_selections_are_rejected_before_fetching(self):
        with patch.object(visual_images, 'fetch_public_image') as fetch:
            for query, status, code in (
                ({'tree_version': 'dom-v1:' + '0' * 64}, 409, 'tree_version_changed'),
                ({'tree_version': ''}, 400, 'invalid_query'), ({'node_id': ''}, 400, 'invalid_query'),
                ({'url': 'https://other.example'}, 400, 'invalid_query'), ({'node_id': 'n99'}, 404, 'node_not_found'),
                ({'node_id': 'n1'}, 422, 'image_source_unavailable'), ({'node_id': 'n4'}, 422, 'image_source_unavailable'),
            ):
                with self.subTest(query=query):
                    self.assert_error(self.image(**query), status, code)
            self.assert_error(self.client.get(self.path + 'image/', {'node_id': 'n2'}), 400, 'invalid_query')
            fetch.assert_not_called()

    def test_ownership_permissions_readiness_and_ttl_precede_fetch(self):
        with patch.object(visual_images, 'fetch_public_image') as fetch:
            self.client.force_authenticate(None)
            self.assert_error(self.image(), 401, 'authentication_failed')
            self.client.force_authenticate(self.other)
            self.assert_error(self.image(), 404, 'snapshot_not_found')
            self.client.force_authenticate(self.owner)
            with patch.object(CanConfigureScout, 'has_permission', return_value=False):
                self.assert_error(self.image(), 403, 'permission_denied')
            VisualSnapshot.objects.filter(pk=self.snapshot.pk).update(status='queued')
            self.assert_error(self.image(), 409, 'snapshot_not_ready')
            VisualSnapshot.objects.filter(pk=self.snapshot.pk).update(created_at=timezone.now() - timedelta(hours=2))
            self.assert_error(self.image(), 404, 'snapshot_not_found')
            fetch.assert_not_called()

    def test_remote_failures_are_structured_and_never_return_an_upstream_body(self):
        for source_error, code, status in (
            ('network', 'image_fetch_failed', 502), ('http_404', 'image_fetch_failed', 502),
            ('unsupported_image', 'unsupported_image', 415), ('url_blocked', 'url_blocked', 422),
            ('too_large', 'too_large', 413),
        ):
            with self.subTest(code=source_error), patch.object(
                visual_images, 'fetch_public_image', side_effect=FetchError(source_error, 'Ошибка', retryable=False),
            ):
                self.assert_error(self.image(), status, code)
