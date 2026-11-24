"""Загрузка файла только для явно выбранного изображения сохранённого снимка."""

from .errors import FetchError, ScoutError
from .image_sources import image_source
from .proxy_http import fetch_proxy_image
from .public_http import fetch_public_image

IMAGE_MAX_BYTES = 8 * 1024 * 1024
IMAGE_TIMEOUT_SECONDS = 10


def image_url(document, uid, base):
    node = document.nodes.get(uid)
    if node is None:
        raise ScoutError('node_not_found', 'Элемент отсутствует в снимке')
    if node.tag != 'img':
        raise ScoutError('image_source_unavailable', 'Выберите элемент img в снимке')
    url = image_source(node, base)
    if url:
        return url
    raise ScoutError('image_source_unavailable', 'У изображения нет адреса для скачивания')


def download_image(snapshot, url):
    options = {'timeout_seconds': IMAGE_TIMEOUT_SECONDS, 'max_bytes': IMAGE_MAX_BYTES}
    try:
        if snapshot.proxy_profile_revision_public_id:
            return fetch_proxy_image(
                url, revision_id=snapshot.proxy_profile_revision_public_id, owner=snapshot.user_public_id, **options,
            )
        return fetch_public_image(url, **options)
    except FetchError as exc:
        if exc.code in ('url_blocked', 'too_large', 'unsupported_image'):
            raise
        raise ScoutError('image_fetch_failed', 'Не удалось скачать изображение с сайта') from None
