"""Чтение списка адресов из XML-карты сайта."""

from lxml import etree

from .errors import ScoutError

_NS = '{http://www.sitemaps.org/schemas/sitemap/0.9}'


def sitemap_urls(body: bytes) -> list[str]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(body, parser)
    except (etree.XMLSyntaxError, LookupError) as exc:
        raise ScoutError('sitemap_invalid', 'Карта сайта содержит некорректный XML') from exc
    if root.getroottree().docinfo.doctype:
        raise ScoutError('sitemap_invalid', 'Карта сайта не должна содержать DTD')
    if root.tag in ('sitemapindex', f'{_NS}sitemapindex'):
        raise ScoutError('sitemap_index_unsupported', 'Укажите URL отдельной карты сайта в формате urlset')
    if root.tag not in ('urlset', f'{_NS}urlset'):
        raise ScoutError('sitemap_invalid', 'Ожидается XML-карта сайта с корневым элементом urlset')
    ns = _NS if root.tag.startswith(_NS) else ''
    urls = []
    for entry in root.iterfind(f'{ns}url/{ns}loc'):
        url = (entry.text or '').strip()
        if not len(entry) and len(url) <= 2000 and url.lower().startswith(('http://', 'https://')):
            urls.append(url)
    if not urls:
        raise ScoutError('sitemap_empty', 'В карте сайта нет абсолютных HTTP(S)-адресов страниц')
    return urls
