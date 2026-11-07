"""Только обнаружение Sitemap в robots.txt; правила доступа не интерпретируются."""

from urllib.parse import urlsplit, urlunsplit

from .errors import ScoutError

MAX_ROBOTS_BYTES = 512 * 1024


def robots_url(seed_url):
    parts = urlsplit(seed_url)
    return urlunsplit((parts.scheme, parts.netloc, '/robots.txt', '', ''))


def robots_sitemaps(body):
    try:
        text = body.decode('utf-8-sig')
    except UnicodeError:
        raise ScoutError('robots_invalid', 'robots.txt должен содержать текст UTF-8') from None
    if text.lstrip().startswith('<') or any(ord(char) < 32 and char not in '\t\r\n' for char in text):
        raise ScoutError('robots_invalid', 'Вместо robots.txt получен некорректный текст')
    urls = []
    for line in text.splitlines():
        directive, separator, value = line.partition('#')[0].partition(':')
        if separator and directive.strip().lower() == 'sitemap':
            value = value.strip()
            if not value.lower().startswith(('https://', 'http://')) or len(value) > 2000:
                raise ScoutError('robots_invalid', 'Sitemap в robots.txt требует абсолютный HTTP(S)-адрес до 2000 символов')
            urls.append(value)
    if not urls:
        raise ScoutError('robots_no_sitemap', 'В robots.txt нет адресов Sitemap')
    return urls
