"""Один ограниченный браузерный проход известной формы Checko, без личного профиля."""

import asyncio
import os
from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Thread
from time import monotonic
from urllib.parse import urlsplit

from .browser_egress import BrowserEgress
from .challenges import raise_for_challenge
from .errors import FetchError
from .html_extract import detected_charset
from .smartcaptcha_tasks import ImageTaskState, solve_text_task

_SLOTS = BoundedSemaphore(1)


def origin_of(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username is not None or parts.password is not None:
        raise FetchError('captcha_browser_scope', 'Браузерная проверка требует HTTPS без реквизитов в адресе', retryable=False)
    host = '[' + parts.hostname + ']' if ':' in parts.hostname else parts.hostname
    return 'https://' + host + (':' + str(parts.port) if parts.port not in (None, 443) else '')


def fetch_browser_html(url, *, cookies=(), proxy=None, max_bytes=1000000, seconds=45,
                       channel='chrome', url_allowed=None, should_continue=lambda: True):
    if 'pw:' in os.environ.get('DEBUG', '') or os.environ.get('DEBUG') == '*':
        raise FetchError('captcha_browser_unavailable', 'Протокольный журнал браузера должен быть выключен', retryable=False)
    origin = origin_of(url)
    if url_allowed is not None and not url_allowed(url):
        raise FetchError('url_scope', 'Адрес выходит за пределы плана', retryable=False)
    slot_deadline = monotonic() + 5
    while not _SLOTS.acquire(timeout=.1):
        if not should_continue():
            raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
        if monotonic() >= slot_deadline:
            raise FetchError('captcha_browser_busy', 'Браузер проверки уже занят', retryable=False)
    cancelled = Event()
    finished = Event()
    output = Queue(maxsize=1)
    try:
        gateway = BrowserEgress(origin, proxy=proxy, seconds=seconds)
    except Exception:
        _SLOTS.release()
        raise FetchError('captcha_browser_unavailable', 'Сетевой шлюз браузера недоступен', retryable=False) from None

    def invoke():
        try:
            # Django на Windows использует Selector; дочерний драйвер требует Proactor.
            factory = asyncio.ProactorEventLoop if os.name == 'nt' else asyncio.new_event_loop
            with asyncio.Runner(loop_factory=factory) as runner:
                result = runner.run(_browse(url, origin, cookies, gateway, cancelled, max_bytes, channel, url_allowed))
        except FetchError as exc:
            result = exc
        except Exception:
            result = FetchError('captcha_browser_unavailable', 'Браузерная проверка недоступна', retryable=False)
        finally:
            gateway.server.server_close()
            _SLOTS.release()
            finished.set()
        output.put(result)

    try:
        Thread(target=invoke, name='scout-smartcaptcha-browser', daemon=True).start()
    except RuntimeError:
        _SLOTS.release()
        gateway.server.server_close()
        raise FetchError('captcha_browser_unavailable', 'Браузерная проверка недоступна', retryable=False) from None
    deadline = monotonic() + seconds + 5
    while True:
        try:
            continuing = should_continue()
        except BaseException:
            cancelled.set()
            gateway.cancel()
            finished.wait(timeout=5)
            raise
        if not continuing:
            cancelled.set()
            gateway.cancel()
            finished.wait(timeout=5)
            raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
        try:
            result = output.get(timeout=0.3)
        except Empty:
            if monotonic() >= deadline:
                cancelled.set()
                gateway.cancel()
                finished.wait(timeout=5)
                raise FetchError('captcha_browser_timeout', 'Истекло время браузерной проверки', retryable=False) from None
            continue
        if isinstance(result, FetchError):
            raise result from None
        return result


async def _launch(playwright, gateway, channel):
    return await playwright.chromium.launch(**_launch_arguments(gateway, channel))


def _launch_arguments(gateway, channel):
    return dict(channel=channel, headless=True, timeout=10000, chromium_sandbox=True,
        proxy={'server': gateway.address, 'bypass': '<-loopback>'},
        args=['--disable-quic', '--disable-background-networking', '--dns-prefetch-disable',
              '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
              '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])


async def _browse(url, origin, cookies, gateway, cancelled, max_bytes, channel, url_allowed):
    from playwright.async_api import async_playwright, Error as BrowserError, TimeoutError as BrowserTimeout

    fatal = []
    submitting = False
    image_tasks = ImageTaskState()
    with gateway:
        async with async_playwright() as playwright:
            browser = await _launch(playwright, gateway, channel)
            try:
                context = await browser.new_context(ignore_https_errors=False, accept_downloads=False,
                                                    service_workers='block', locale='ru-RU')
                if cookies:
                    await context.add_cookies(list(cookies))
                page = await context.new_page()
                page.on('dialog', lambda dialog: dialog.dismiss())
                context.on('page', lambda other: other.close() if other != page else None)
                await context.route_web_socket('**', lambda route: route.close())

                async def route_request(route):
                    request = route.request
                    try:
                        parts = urlsplit(request.url)
                        allowed = (parts.scheme == 'https' and (parts.hostname, parts.port or 443) in gateway.authorities
                                   and parts.username is None and parts.password is None)
                        if request.is_navigation_request() and request.frame == page.main_frame:
                            control_post = submitting and request.method == 'POST' and parts.path == '/check/humaneness'
                            allowed = allowed and origin_of(request.url) == origin and (
                                control_post or url_allowed is None or url_allowed(request.url))
                            if not allowed:
                                fatal.append(FetchError('url_scope', 'Переадресация выходит за пределы плана', retryable=False))
                        if not allowed or cancelled.is_set():
                            await route.abort()
                        else:
                            await route.continue_()
                    except Exception:
                        await route.abort()

                await context.route('**/*', route_request)
                try:
                    response = await page.goto(url, wait_until='domcontentloaded', timeout=_remaining(gateway))
                    if response is None:
                        raise FetchError('captcha_browser_response', 'Браузер не получил страницу', retryable=False)
                    challenge_present = bool(response.status == 429 or await page.locator('form[action="/check/humaneness"]').count())
                    if challenge_present:
                        form = page.locator('form[action="/check/humaneness"][method="post"]')
                        if await form.count() != 1:
                            raise FetchError('captcha_task_unsupported', 'Форма проверки пока не поддержана', retryable=False)
                        if not await _has_token(page):
                            await page.frame_locator('[data-testid="checkbox-iframe"]').get_by_role('checkbox', name='Я не робот').click(timeout=min(10000, _remaining(gateway)))
                        while not await _has_token(page):
                            if cancelled.is_set():
                                raise FetchError('captcha_browser_cancelled', 'Браузерная проверка прервана', retryable=False)
                            _remaining(gateway)
                            await solve_text_task(page, state=image_tasks, deadline=gateway.deadline, cancelled=cancelled)
                            await page.wait_for_timeout(200)
                        submitting = True
                        async with page.expect_navigation(wait_until='domcontentloaded', timeout=_remaining(gateway)) as navigation:
                            await form.get_by_role('button', name='Подтвердить', exact=True).click(timeout=_remaining(gateway))
                        response = await navigation.value
                    if response is None or not 200 <= response.status < 300:
                        raise FetchError('captcha_not_cleared', 'Источник не принял браузерную проверку', retryable=False)
                    if origin_of(page.url) != origin or (url_allowed and not url_allowed(page.url)):
                        raise FetchError('url_scope', 'Переадресация выходит за пределы плана', retryable=False)
                    response_headers = await response.all_headers()
                    content_type = response_headers.get('content-type', '')
                    if content_type.split(';', 1)[0].strip().lower() not in ('text/html', 'application/xhtml+xml'):
                        raise FetchError('not_html', 'Ответ не является HTML', retryable=False)
                    body = await response.body()
                    if len(body) > max_bytes:
                        raise FetchError('too_large', 'Страница больше допустимого размера', retryable=False)
                    raise_for_challenge(headers=response_headers, url=page.url, body=body, content_type=content_type)
                    if fatal:
                        raise fatal[0]
                    source_host = urlsplit(origin).hostname
                    selected = [c for c in await context.cookies([origin]) if c['domain'].lstrip('.') == source_host]
                    return {'page': {'status': response.status, 'body': body, 'content_type': content_type[:120],
                                     'charset': detected_charset(body, content_type)[:40], 'final_url': page.url},
                            'cookies': selected, 'user_agent': await page.evaluate('navigator.userAgent'),
                            'egress_bytes': gateway.transferred, 'challenge_present': challenge_present,
                            'image_tasks': image_tasks.submissions, 'ml_calls': image_tasks.inferences,
                            'ml_seconds': round(image_tasks.model_seconds, 3)}
                except BrowserError as exc:
                    if fatal:
                        raise fatal[0] from None
                    if gateway.failure:
                        code, detail, retryable = gateway.failure
                        raise FetchError(code, detail, retryable=retryable) from None
                    code = 'captcha_browser_timeout' if isinstance(exc, BrowserTimeout) else 'captcha_browser_network'
                    raise FetchError(code, 'Браузерная проверка не завершилась', retryable=False) from None
            finally:
                await asyncio.wait_for(browser.close(), timeout=5)


def _remaining(gateway):
    remaining = int((gateway.deadline - monotonic()) * 1000)
    if remaining <= 0:
        raise FetchError('captcha_browser_timeout', 'Истекло время браузерной проверки', retryable=False)
    return remaining


async def _has_token(page):
    return await page.evaluate('Boolean(document.querySelector(\'input[name="smart-token"]\')?.value)')
