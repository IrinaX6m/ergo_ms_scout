"""Подтверждённый текстовый тип Advanced SmartCaptcha: картинка → локальная модель → поле rep."""

import asyncio
import hashlib
import re
from contextvars import copy_context
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from urllib.parse import urlsplit

from django.views.decorators.debug import sensitive_variables

from .captcha_ml import recognize_phrase
from .errors import FetchError, ScoutError

_PROVIDER_HOSTS = frozenset({'smartcaptcha.yandexcloud.net', 'smartcaptcha.cloud.yandex.ru'})


@dataclass
class ImageTaskState:
    inferences: int = 0
    submissions: int = 0
    model_seconds: float = 0
    seen: set = field(default_factory=set, repr=False)
    frame_seen_at: float | None = None


def is_provider_frame(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.hostname in _PROVIDER_HOSTS
                and parts.port in (None, 443) and parts.username is None and parts.password is None)
    except ValueError:
        return False


@sensitive_variables()
async def solve_text_task(page, *, state, deadline, cancelled):
    container = page.locator('iframe[data-testid="advanced-iframe"]')
    if await container.count() != 1 or not await container.is_visible():
        return False
    element = await container.element_handle()
    frame = await element.content_frame() if element else None
    if frame is None:
        return False
    if frame.url in ('', 'about:blank'):
        return False
    if not is_provider_frame(frame.url):
        raise FetchError('captcha_task_unsupported', 'Источник дополнительного задания не поддержан', retryable=False)
    text = frame.locator('input[name="rep"]')
    image = frame.locator('img[alt="Задание с картинкой"]')
    submit = frame.locator('button').filter(has_text=re.compile(r'^Отправить$'))
    if state.frame_seen_at is None:
        state.frame_seen_at = monotonic()
    if await text.count() != 1 or await image.count() != 1 or await submit.count() != 1:
        if monotonic() - state.frame_seen_at < 5:
            return False
        raise FetchError('captcha_task_unsupported', 'Поддержан только текстовый тип дополнительного задания', retryable=False)
    if await text.evaluate('n => n.type') != 'text':
        raise FetchError('captcha_task_unsupported', 'Поддержан только текстовый тип дополнительного задания', retryable=False)
    if not await text.is_visible() or not await image.is_visible() or not await submit.is_visible():
        return False
    dimensions = await image.evaluate('n => ({loaded:n.complete&&n.naturalWidth>0,w:n.clientWidth,h:n.clientHeight})')
    if not dimensions['loaded']:
        return False
    if not (0 < dimensions['w'] <= 2048 and 0 < dimensions['h'] <= 2048
            and dimensions['w'] * dimensions['h'] <= 524288):
        raise FetchError('captcha_image_invalid', 'Изображение задания больше допустимого размера', retryable=False)
    picture = await image.screenshot(type='png', timeout=_milliseconds(deadline))
    identity = await _identity(image, picture)
    if identity in state.seen:
        return False
    if state.inferences >= 2:
        raise FetchError('captcha_attempts_exhausted', 'Лимит решений дополнительного задания исчерпан', retryable=False)
    state.seen.add(identity)
    state.inferences += 1
    timeout = min(25, int(deadline - monotonic() - 3))
    if timeout < 1:
        raise FetchError('captcha_model_timeout', 'Не осталось времени для локального распознавания', retryable=False)
    started = monotonic()
    answer = await _local_answer(picture, timeout, cancelled)
    state.model_seconds += monotonic() - started
    if cancelled.is_set():
        raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
    if await page.evaluate('Boolean(document.querySelector(\'input[name="smart-token"]\')?.value)'):
        return False
    if not await container.is_visible():
        return False
    current = await image.screenshot(type='png', timeout=_milliseconds(deadline))
    if await _identity(image, current) != identity:
        # Обновлённой картинке нельзя отправлять ответ предыдущего задания.
        return False
    maximum = await text.evaluate('n => n.maxLength')
    if maximum > 0 and len(answer) > maximum:
        raise FetchError('captcha_model_invalid', 'Ответ не помещается в поле задания', retryable=False)
    await text.fill(answer, timeout=_milliseconds(deadline))
    if cancelled.is_set():
        raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
    await submit.click(timeout=_milliseconds(deadline))
    state.submissions += 1
    return True


@sensitive_variables()
async def _identity(image, picture):
    source = await image.get_attribute('src') or ''
    return hashlib.sha256(source.encode() + b'\0' + picture).digest()


@sensitive_variables()
async def _local_answer(picture, timeout, cancelled):
    output = Queue(maxsize=1)
    deadline = monotonic() + timeout

    def invoke():
        try:
            while True:
                if cancelled.is_set():
                    raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
                remaining = int(deadline - monotonic())
                if remaining < 1:
                    raise FetchError('captcha_model_timeout', 'Истекло время локального распознавания', retryable=False)
                try:
                    result = recognize_phrase(picture, timeout_seconds=remaining)
                    break
                except ScoutError as exc:
                    if exc.code != 'captcha_model_busy':
                        raise
                    cancelled.wait(.2)
        except ScoutError as exc:
            result = FetchError(exc.code, str(exc), retryable=False)
        except Exception:
            result = FetchError('captcha_model_unavailable', 'Локальная модель CAPTCHA недоступна', retryable=False)
        output.put(result)

    context = copy_context()
    Thread(target=context.run, args=(invoke,), name='scout-captcha-phrase', daemon=True).start()
    while True:
        if cancelled.is_set():
            raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
        try:
            answer = output.get_nowait()
        except Empty:
            if monotonic() >= deadline:
                raise FetchError('captcha_model_timeout', 'Истекло время локального распознавания', retryable=False)
            await asyncio.sleep(.1)
            continue
        if isinstance(answer, FetchError):
            raise answer from None
        return answer


def _milliseconds(deadline):
    remaining = int((deadline - monotonic()) * 1000)
    if remaining <= 0:
        raise FetchError('captcha_browser_timeout', 'Истекло время браузерной проверки', retryable=False)
    return remaining
