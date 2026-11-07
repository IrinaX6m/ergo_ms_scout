"""Несколько карт из robots.txt и управляемые ответы для отказов и восстановления."""

from urllib.parse import urlsplit

from .sitemap_index_catalog import SitemapIndexCatalog, index_plan


class RobotsCatalog(SitemapIndexCatalog):
    def __init__(self):
        super().__init__()
        self.robots_body = ('\ufeffUser-agent: *\r\nDisallow: /ignored-by-discovery/\r\n'
                            f'Sitemap: {self.origin}/one.xml.gz\r\n'
                            f'sItEmAp: {self.origin}/index.xml # index\r\n'
                            f'Sitemap: {self.origin}/one.xml.gz#duplicate\r\n').encode('utf-8')
        self.robots_status = 200
        self.robots_redirect = ''
        self.robots_content_type = 'text/plain; charset=utf-8'
        base = self.RequestHandlerClass

        class Handler(base):
            def do_GET(handler):
                if urlsplit(handler.path).path != '/robots.txt':
                    return super().do_GET()
                site = handler.server
                site.hits['/robots.txt'] += 1
                if site.block_path == '/robots.txt':
                    site.entered.set()
                    site.release.wait(15)
                code = site.robots_status
                if isinstance(code, list):
                    code = code.pop(0) if len(code) > 1 else code[0]
                handler.send_response(code)
                if site.robots_redirect:
                    handler.send_header('Location', site.robots_redirect)
                handler.send_header('Content-Type', site.robots_content_type)
                handler.send_header('Content-Length', str(len(site.robots_body)))
                handler.end_headers()
                try:
                    handler.wfile.write(site.robots_body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.RequestHandlerClass = Handler


def robots_plan(origin):
    plan = index_plan(origin)
    del plan['crawl']['sitemap_url']
    plan['crawl']['sitemap_from_robots'] = True
    return plan
