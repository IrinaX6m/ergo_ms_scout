"""Контрольный индекс с gzip-картой, вложением, общими URL и управляемой задержкой XML."""

import gzip
from threading import Event
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from .ext002_catalog import ComparisonCatalog, comparison_plan


def xml_index(urls):
    return '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
        f'<sitemap><loc>{escape(url)}</loc></sitemap>' for url in urls
    ) + '</sitemapindex>'


def xml_urls(urls):
    return '<urlset>' + ''.join(f'<url><loc>{escape(url)}</loc></url>' for url in urls) + '</urlset>'


class SitemapIndexCatalog(ComparisonCatalog):
    def __init__(self):
        super().__init__()
        self.xml = {
            '/index.xml': xml_index([self.origin+'/one.xml.gz', self.origin+'/one.xml.gz#duplicate',
                                     self.origin+'/nested.xml']),
            '/one.xml.gz': xml_urls([self.origin+'/products/k-01', self.origin+'/sale/k-01']),
            '/nested.xml': xml_index([self.origin+'/two.xml']),
            '/two.xml': xml_urls([self.origin+'/products/k-02', self.origin+'/products/no-sku']),
            '/cycle.xml': xml_index([self.origin+'/nested-cycle.xml']),
            '/nested-cycle.xml': xml_index([self.origin+'/cycle.xml']),
            '/broken-index.xml': xml_index([self.origin+'/one.xml.gz', self.origin+'/broken.xml']),
            '/broken.xml': '<urlset>',
        }
        self.block_path = None
        self.entered, self.release = Event(), Event()
        base = self.RequestHandlerClass

        class Handler(base):
            def do_GET(handler):
                path = urlsplit(handler.path).path
                if path not in handler.server.xml:
                    return super().do_GET()
                handler.server.hits[path] += 1
                if path == handler.server.block_path:
                    handler.server.entered.set()
                    handler.server.release.wait(15)
                value = handler.server.xml[path]
                if value is None:
                    handler.send_error(404)
                    return
                if isinstance(value, tuple):
                    handler.send_response(302)
                    handler.send_header('Location', value[0])
                    handler.end_headers()
                    return
                body = value.encode('utf-8')
                body = gzip.compress(body) if path.endswith('.gz') else body
                handler.send_response(200)
                handler.send_header('Content-Type', 'application/gzip' if path.endswith('.gz') else 'application/xml')
                handler.send_header('Content-Length',str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

        self.RequestHandlerClass = Handler


def index_plan(origin, path='/index.xml'):
    plan = comparison_plan(origin)
    plan['crawl']['sitemap_url'] = origin+path
    return plan
