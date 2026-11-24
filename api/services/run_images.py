"""Получение изображений до транзакции записи и привязка файлов под блокировкой запуска."""

from collections import defaultdict
from dataclasses import dataclass, field
from time import monotonic

from django.utils import timezone

from ..models import RunImage
from .constants import RUN_PAUSING, RUN_RUNNING
from .errors import ScoutError
from .proxy_http import fetch_proxy_image
from .public_http import fetch_public_image
from .url_norm import url_key
from .visual_images import IMAGE_MAX_BYTES, IMAGE_TIMEOUT_SECONDS

MAX_RUN_IMAGES = 100
MAX_RUN_BYTES = 64 * 1024 * 1024
MAX_PAGE_REQUESTS = 32
PAGE_TIMEOUT_SECONDS = 30


@dataclass
class _Selection:
    references: list = field(default_factory=list)
    downloaded: RunImage | None = None
    status: str = 'limit'


def _stored_images(run_id):
    return {image.url_hash: image for image in RunImage.objects.filter(run_id=run_id).only(
        'url_hash', 'public_id', 'content_type', 'byte_size',
    )}


def prepare_run_images(task, rows):
    selected = defaultdict(_Selection)
    for row in rows:
        for cell in row['values'].values():
            for image in cell.get('images', ()):
                if image['status'] == 'candidate':
                    selected[image['source_url']].references.append(image)
    if not selected:
        return selected

    run = task.run
    revision = run.job_revision
    if (run.status not in (RUN_RUNNING, RUN_PAUSING) or not revision.approved_plan_hash
            or revision.approved_plan_hash != revision.plan_hash):
        return selected
    saved = _stored_images(run.pk)
    slots = MAX_RUN_IMAGES - len(saved)
    byte_budget = MAX_RUN_BYTES - sum(image.byte_size for image in saved.values())
    # Оставляем секунду для атомарной записи результата перед истечением аренды.
    now = timezone.now()
    remaining = (task.lease_until - now).total_seconds() - 1
    crawl = revision.crawl or {}
    if crawl.get('mode') == 'site' and run.started_at:
        remaining = min(remaining, crawl['max_seconds'] - (now - run.started_at).total_seconds())
    deadline = monotonic() + min(PAGE_TIMEOUT_SECONDS, remaining)
    requests = 0
    for url, selection in selected.items():
        key = url_key(url)
        if key in saved:
            continue
        timeout = min(IMAGE_TIMEOUT_SECONDS, deadline - monotonic())
        if slots <= 0 or byte_budget <= 0 or requests >= MAX_PAGE_REQUESTS or timeout <= 0:
            break
        requests += 1
        options = {'timeout_seconds': timeout, 'max_bytes': min(IMAGE_MAX_BYTES, byte_budget)}
        try:
            if revision.proxy_profile_revision_public_id:
                result = fetch_proxy_image(url, owner=run.user_public_id,
                                           revision_id=revision.proxy_profile_revision_public_id, **options)
            else:
                result = fetch_public_image(url, **options)
        except ScoutError as exc:
            if exc.code != 'too_large' and monotonic() < deadline:
                selection.status = 'failed'
            continue
        body = result['body']
        selection.downloaded = RunImage(run_id=run.pk, source_url=url, url_hash=key,
                                        body=body, byte_size=len(body), content_type=result['content_type'])
        byte_budget -= len(body)
        slots -= 1
    return selected


def store_run_images(run_id, selected):
    """Записывается в той же транзакции и с тем же fencing, что и ячейки записей."""
    if not selected:
        return
    saved = _stored_images(run_id)
    total_bytes = sum(image.byte_size for image in saved.values())
    for url, selection in selected.items():
        key = url_key(url)
        image = saved.get(key)
        if image is None and selection.downloaded is not None:
            downloaded = selection.downloaded
            if len(saved) < MAX_RUN_IMAGES and total_bytes + downloaded.byte_size <= MAX_RUN_BYTES:
                downloaded.save(force_insert=True)
                image = saved[key] = downloaded
                total_bytes += image.byte_size
        result = {'status': selection.status} if image is None else {
            'status': 'saved', 'public_id': str(image.public_id),
            'content_type': image.content_type, 'byte_size': image.byte_size,
        }
        for reference in selection.references:
            reference.update(result)
