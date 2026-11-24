"""Сохранённая картинка принадлежит результату того же подтверждённого сбора."""

import os
from base64 import b64decode
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from ..models import PageSnapshot, Run, RunImage, Task
from ..permissions import CanViewScout
from ..services import retention, run_images, snapshot_store, tasks_exec
from ..services.errors import FetchError, ScoutError
from ..services.preview import preview_rows
from ..services.runs import approve_run, create_job, explore_job, start_run
from ..services.url_norm import url_key

_BASE = 'https://catalog.example/start'
_FINAL = 'https://cdn.example/catalog/redirected.html'
_PHOTO = 'https://cdn.example/catalog/photo.png?size=500'
_HTML = b'''<main><article><b>Book</b><img src="photo.png?size=500"><img src="bad.svg"></article>
    <article><b>Pen</b><img data-src="photo.png?size=500"></article></main>'''
_PNG = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR42mNgAAAAAgAB5Sfe/AAAAABJRU5ErkJggg==')


def candidates(*urls):
    return [{'values': {'photo': {'images': [{'source_url': url, 'status': 'candidate'} for url in urls]}}}]


class RunImageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username='run-image-owner')
        self.job = create_job(
            user_public_id=self.user.public_id, title='Фото', seed_urls=[_BASE],
            record={'kind': 'css', 'selector': 'article'},
            fields=[{'name': 'title', 'kind': 'css', 'selector': 'b', 'scope': 'record', 'many': False},
                    {'name': 'photo', 'kind': 'css', 'selector': 'img', 'scope': 'record', 'many': True,
                     'value_source': 'image'}],
        )
        self.revision = self.job.revisions.get()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def approved_run(self):
        self.revision.approved_plan_hash = self.revision.plan_hash
        self.revision.save(update_fields=['approved_plan_hash'])
        return Run.objects.create(job_revision=self.revision, user_public_id=self.user.public_id,
                                  status='running', started_at=timezone.now())

    def test_approved_worker_fetches_once_then_serves_saved_bytes_without_source(self):
        def image(url, **_kwargs):
            if url == _PHOTO:
                return {'content_type': 'image/png', 'body': _PNG}
            raise FetchError('bad_encoding', 'Сжатый ответ не распаковывается', retryable=False)

        page = {'body': _HTML, 'status': 200, 'final_url': _FINAL, 'content_type': 'text/html', 'charset': 'utf-8'}
        files = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(snapshot_store, 'CACHE_DIR', Path(files)))
        self.enterContext(patch.dict(os.environ, {'SCOUT_TASK_RUNNER': 'inline'}))
        self.enterContext(patch.object(tasks_exec, 'fetch_public_html', return_value=page))
        fetch = self.enterContext(patch.object(run_images, 'fetch_public_image', side_effect=image))
        run = explore_job(job=self.job, user_public_id=self.user.public_id)
        tasks_exec.publish_ready(run.public_id)
        preview_rows(run)
        approve_run(run=run, user_public_id=self.user.public_id)
        fetch.assert_not_called()
        self.assertFalse(run.images.exists())
        start_run(run=run)
        tasks_exec.publish_ready(run.public_id)
        run.refresh_from_db()
        self.assertEqual(run.status, 'completed')
        self.assertEqual(fetch.call_count, 2)
        saved = run.images.get()
        self.assertEqual(saved.source_url, _PHOTO)
        book, pen = run.records.order_by('pk')
        book_photos = book.values['photo']['images']
        self.assertEqual([p['status'] for p in book_photos], ['saved', 'failed'])
        self.assertEqual(book_photos[0], {'source_url': _PHOTO, 'status': 'saved', 'public_id': str(saved.public_id),
                                         'content_type': 'image/png', 'byte_size': len(_PNG)})
        self.assertEqual(pen.values['photo']['images'], [book_photos[0]])
        self.assertEqual(pen.values['title']['normalized'], 'Pen')
        endpoint = f'/api/scout/runs/{run.public_id}/images/{saved.public_id}/'
        response = self.client.get(endpoint, HTTP_ACCEPT='image/*')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, _PNG)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['Content-Disposition'], f'attachment; filename="scout-{saved.public_id}.png"')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.client.head(endpoint).status_code, 405)
        self.assertEqual(fetch.call_count, 2)

    def test_prepared_pages_share_persisted_file_and_recheck_storage_caps_before_writing(self):
        run = self.approved_run()
        task = SimpleNamespace(run=run, lease_until=timezone.now() + timedelta(seconds=120))
        a, b, c = ('https://example.com/' + name for name in ('a', 'b', 'c'))
        first = candidates(a)
        second = candidates(a, b, c)
        with (patch.object(run_images, 'MAX_RUN_IMAGES', 2), patch.object(run_images, 'MAX_RUN_BYTES', 9),
              patch.object(run_images, 'fetch_public_image', return_value={'body': b'123', 'content_type': 'image/gif'}) as fetch):
            # Два исполнителя закончили сеть до того, как первый записал свой результат.
            one = run_images.prepare_run_images(task, first)
            two = run_images.prepare_run_images(task, second)
            self.assertFalse(run.images.exists())
            run_images.store_run_images(run.pk, one)
            run_images.store_run_images(run.pk, two)
            fetched = fetch.call_count
            replay = candidates(a)
            run_images.store_run_images(run.pk, run_images.prepare_run_images(task, replay))
            self.assertEqual(fetch.call_count, fetched)
        images = second[0]['values']['photo']['images']
        self.assertEqual([v['status'] for v in images], ['saved', 'saved', 'limit'])
        self.assertEqual(images[0], first[0]['values']['photo']['images'][0])
        self.assertEqual(images[0], replay[0]['values']['photo']['images'][0])
        self.assertEqual(run.images.count(), 2)

    def test_limits_and_proxy_failure_keep_other_results(self):
        run = self.approved_run()
        run.job_revision.proxy_profile_revision_public_id = uuid4()
        task = SimpleNamespace(run=run, lease_until=timezone.now() + timedelta(seconds=5))
        rows = candidates(_PHOTO, _BASE)
        with (patch.object(run_images, 'MAX_PAGE_REQUESTS', 1),
              patch.object(run_images, 'fetch_public_image') as direct,
              patch.object(run_images, 'fetch_proxy_image', side_effect=ScoutError('proxy_blocked', 'Отозван')) as proxy):
            run_images.store_run_images(run.pk, run_images.prepare_run_images(task, rows))
            direct.assert_not_called()
            args = proxy.call_args.kwargs
            self.assertEqual((args['revision_id'], args['owner']),
                             (run.job_revision.proxy_profile_revision_public_id, self.user.public_id))
            self.assertLessEqual(args['timeout_seconds'], 4)
            self.assertEqual([v['status'] for v in rows[0]['values']['photo']['images']], ['failed', 'limit'])
            task.lease_until = timezone.now()
            expired = candidates(_BASE)
            run_images.store_run_images(run.pk, run_images.prepare_run_images(task, expired))
            self.assertEqual(proxy.call_count, 1)
            self.assertEqual(expired[0]['values']['photo']['images'][0]['status'], 'limit')

    def test_concurrent_files_cannot_exceed_run_byte_limit(self):
        run = self.approved_run()
        task = SimpleNamespace(run=run, lease_until=timezone.now() + timedelta(seconds=120))
        first, second = candidates(_PHOTO), candidates(_BASE)
        with (patch.object(run_images, 'MAX_RUN_BYTES', 5),
              patch.object(run_images, 'fetch_public_image', return_value={'body': b'123', 'content_type': 'image/gif'})):
            one = run_images.prepare_run_images(task, first)
            two = run_images.prepare_run_images(task, second)
            run_images.store_run_images(run.pk, one)
            run_images.store_run_images(run.pk, two)
        self.assertEqual(run.images.count(), 1)
        self.assertEqual(run.images.get().byte_size, 3)
        self.assertEqual(second[0]['values']['photo']['images'][0], {'source_url': _BASE, 'status': 'limit'})

    def test_fenced_out_extraction_cannot_leave_saved_image(self):
        run = self.approved_run()
        snapshot = PageSnapshot.objects.create(run=run, source_url=_BASE, final_url=_FINAL)
        task = Task.objects.create(run=run, kind='extract', idempotency_key='stale', status='leased',
                                   payload={'snapshot_public_id': str(snapshot.public_id)}, fencing_token=2,
                                   lease_until=timezone.now() + timedelta(seconds=120))
        with (patch.object(tasks_exec, 'read_snapshot_bytes', return_value=_HTML),
              patch.object(run_images, 'fetch_public_image', return_value={'body': _PNG, 'content_type': 'image/png'})):
            tasks_exec._extract(task, 1)
        self.assertFalse(run.images.exists())
        self.assertFalse(run.records.exists())

    def test_files_follow_result_access_and_resumable_cleanup(self):
        run = self.approved_run()
        old = timezone.now() - timedelta(days=450)
        Run.objects.filter(pk=run.pk).update(status='completed', finished_at=old, started_at=old)
        for _ in range(2):
            Run.objects.create(job_revision=self.revision, user_public_id=self.user.public_id, status='completed',
                               finished_at=timezone.now(), started_at=timezone.now())
        saved = RunImage.objects.create(run=run, source_url=_PHOTO, url_hash=url_key(_PHOTO),
                                        body=_PNG, content_type='image/png', byte_size=len(_PNG))
        path = f'/api/scout/runs/{run.public_id}/images/{saved.public_id}/'
        other_run = Run.objects.exclude(pk=run.pk).first()
        self.assertEqual(self.client.get(path.replace(str(run.public_id), str(other_run.public_id))).status_code, 404)
        with patch.object(CanViewScout, 'has_permission', return_value=False):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_authenticate(get_user_model().objects.create_user(username='other-image-reader'))
        with patch.object(CanViewScout, 'has_permission', return_value=True):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.client.force_authenticate(self.user)
        preview = retention.create_preview(self.user.public_id, {'scopes': ['results'], 'policy_version': 1})
        self.assertEqual(preview.summary['totals']['image_bytes'], len(_PNG))
        self.assertEqual(preview.summary['totals']['images'], 1)
        with patch.object(retention, 'enqueue_cleanup'):
            cleanup = retention.accept_cleanup(self.user.public_id, {
                'preview_public_id': str(preview.public_id), 'manifest_hash': preview.manifest_hash,
                'idempotency_key': str(uuid4()),
            })
            retention.process_cleanup(cleanup.public_id)
            self.assertFalse(run.images.exists())
            self.assertEqual(self.client.get(path).status_code, 410)
            retention.process_cleanup(cleanup.public_id)
            retention.process_cleanup(cleanup.public_id)
        item = cleanup.items.get()
        self.assertEqual((item.deleted_bytes, item.deleted_rows), (len(_PNG), 1))
        run.refresh_from_db()
        self.assertEqual(run.results_availability, 'expired')
        self.assertEqual(run.retained_counts['image_count'], 1)
