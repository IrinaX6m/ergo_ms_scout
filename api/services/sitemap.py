"""Чтение списка адресов из XML-карты сайта."""

from lxml import etree

from .errors import ScoutError

_NS = '{http://www.sitemaps.org/schemas/sitemap/0.9}'


MAX_ENTRIES = 50_000


def sitemap_document(body: bytes) -> tuple[str, list[str]]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(body, parser)
    except (etree.XMLSyntaxError, LookupError) as exc:
        raise ScoutError('sitemap_invalid', 'Карта сайта содержит некорректный XML') from exc
    if root.getroottree().docinfo.doctype:
        raise ScoutError('sitemap_invalid', 'Карта сайта не должна содержать DTD')
    index = root.tag in ('sitemapindex', f'{_NS}sitemapindex')
    if not index and root.tag not in ('urlset', f'{_NS}urlset'):
        raise ScoutError('sitemap_invalid', 'Ожидается XML-карта urlset или индекс sitemapindex')
    ns = _NS if root.tag.startswith(_NS) else ''
    urls = []
    entries = list(root.iterfind(f'{ns}{"sitemap" if index else "url"}'))
    if len(entries) > MAX_ENTRIES:
        raise ScoutError('sitemap_limit', 'Превышен предел записей XML-карты')
    for parent in entries:
        locations = parent.findall(f'{ns}loc')
        if index and len(locations) != 1:
            raise ScoutError('sitemap_invalid', 'Каждая карта индекса должна иметь один абсолютный loc')
        if not locations:
            continue
        entry = locations[0]
        url = (entry.text or '').strip()
        if not len(entry) and len(url) <= 2000 and url.lower().startswith(('http://', 'https://')):
            urls.append(url)
        elif index:
            raise ScoutError('sitemap_invalid', 'Индекс содержит недопустимый адрес карты')
    if not urls:
        raise ScoutError('sitemap_empty', 'В карте сайта нет абсолютных HTTP(S)-адресов страниц')
    return ('index' if index else 'urls'), urls


def sitemap_urls(body: bytes) -> list[str]:
    kind, urls = sitemap_document(body)
    if kind == 'index':
        raise ScoutError('sitemap_index_unsupported', 'Для индекса требуется диспетчер карт')
    return urls
