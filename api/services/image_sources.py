"""Адрес исходного изображения в сохранённом HTML."""

from urllib.parse import urldefrag, urljoin, urlsplit


def image_source(node, base):
    if getattr(node, 'tag', None) != 'img':
        return None
    for attr in ('data-src', 'data-lazy-src', 'data-original', 'src'):
        value = (node.get(attr) or '').strip()
        if not value or value.startswith('#') or any(ord(char) < 32 or char == '\\' for char in value):
            continue
        try:
            url = urldefrag(urljoin(base, value)).url
            parts = urlsplit(url)
            if (parts.scheme in ('http', 'https') and parts.hostname and parts.username is None
                    and len(url) <= 4000 and not any(char.isspace() for char in url)):
                return url
        except ValueError:
            continue
    return None
