"""Тестовый каталог с разными правилами для списка и страницы товара."""

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def catalog_plan(origin):
    return {
        'title': 'Тестовый каталог',
        'seed_urls': [f'{origin}/catalog/'],
        'fields': [
            {'name': 'title', 'kind': 'css', 'selector': '.product-name', 'scope': 'page'},
            {'name': 'price', 'kind': 'css', 'selector': '.price', 'scope': 'page',
             'conversion': {'type': 'money', 'currency': 'RUB', 'decimal_separator': ','}},
            {'name': 'quantity', 'kind': 'css', 'selector': '.stock', 'scope': 'page',
             'conversion': {'type': 'integer'}},
        ],
        'crawl': {
            'mode': 'site', 'max_depth': 2, 'max_pages': 10,
            'visit': [prefix('/catalog/'), prefix('/products/')],
            'preview_urls': [f'{origin}/catalog/', f'{origin}/products/a'],
            'preview_pages': 3,
            'page_types': [
                {'id': 'catalog', 'action': 'discover', 'match': [prefix('/catalog/')]},
                {'id': 'product', 'action': 'extract', 'match': [prefix('/products/')],
                 'selectors': {'title': {'kind': 'css', 'selector': 'h1'}}},
            ],
        },
    }


def prefix(pattern):
    return {'kind': 'prefix', 'pattern': pattern}


def archive_type():
    return {
        'id': 'archive', 'action': 'extract', 'match': [prefix('/archive/')],
        'selectors': {'title': {'kind': 'css', 'selector': 'h2'}},
    }


_PAGES = {
    '/catalog/': '<h1>Каталог</h1><a href="/products/a">a</a><a href="/products/a#duplicate">a</a>'
                 '<a href="/products/b">b</a><a href="/bridge/">Архив</a>',
    '/products/a': '<h1>Чайник</h1><span class="price">1 250,00 ₽</span><span class="stock">3</span>',
    '/products/b': '<h1>Термос</h1><span class="price">790,00 ₽</span><span class="stock">0</span>',
    '/products/empty': '<p>Страница без полей</p>',
    '/products/missing': '<h1>Чашка</h1>',
    '/bridge/': '<h1>Архив</h1><a href="/archive/c">c</a>',
    '/archive/c': '<h2>Кружка</h2><span class="price">110,00 ₽</span><span class="stock">1</span>',
}


class CatalogHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        self.server.hits[path] += 1
        if path == '/catalog/go':
            self.send_response(302)
            self.send_header('Location', '/products/a?utm_source=fixture')
            self.end_headers()
            return
        if path == '/sitemap.xml':
            self._send(f'<urlset><url><loc>http://{self.headers["Host"]}/products/a</loc></url></urlset>',
                       'application/xml')
            return
        if path not in self.server.pages:
            self.send_error(404)
            return
        self._send(f'<!doctype html><html><body>{self.server.pages[path]}</body></html>', 'text/html; charset=utf-8')

    def _send(self, content, content_type):
        body = content.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class CatalogServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(('127.0.0.1', 0), CatalogHandler)
        self.hits = Counter()
        self.pages = _PAGES.copy()
        self.origin = f'http://127.0.0.1:{self.server_port}'
