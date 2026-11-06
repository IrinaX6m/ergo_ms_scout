"""Локальный каталог с известным результатом для измерений SPEC-003."""

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit

PAGE_LIMIT = 200
ROWS_PER_ITEM = 20
NOT_FOUND = 7
RETRY_ONCE = 19
CASES = {'full': PAGE_LIMIT - 1, 'partial': PAGE_LIMIT}


class CatalogHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = urlsplit(self.path).path.strip('/').split('/')
        if len(parts) < 2 or parts[0] not in CASES:
            self.send_error(404)
            return
        case = parts[0]
        if parts[1:] == ['catalog']:
            self.server.register_hit(case, 'catalog')
            links = [f'<a href="items/{item}">{item}</a>' for item in range(1, CASES[case] + 1)]
            links.extend(f'<a href="items/{item}#duplicate">{item}</a>' for item in range(1, 6))
            links.append('<a href="outside-plan">Excluded</a>')
            self._html(''.join(links))
            return
        if len(parts) != 3 or parts[1] != 'items' or not parts[2].isdigit():
            self.send_error(404)
            return
        item = int(parts[2])
        if not 1 <= item <= CASES[case]:
            self.send_error(404)
            return
        hits = self.server.register_hit(case, item)
        if case == 'partial' and item == NOT_FOUND:
            self.send_error(404)
        elif case == 'partial' and item == RETRY_ONCE and hits == 1:
            self.send_error(503)
        else:
            self._html(''.join(
                f'<article><h2>{item}-{row}</h2><span class="price">{item + row}</span></article>'
                for row in range(1, ROWS_PER_ITEM + 1)
            ))

    def _html(self, contents):
        body = f'<!doctype html><meta charset="utf-8">{contents}'.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class CatalogServer(ThreadingHTTPServer):
    def __init__(self, port=0):
        super().__init__(('127.0.0.1', port), CatalogHandler)
        self.hits = Counter()
        self.hit_lock = Lock()

    def register_hit(self, case, item):
        with self.hit_lock:
            self.hits[case, item] += 1
            return self.hits[case, item]


if __name__ == '__main__':
    with CatalogServer(port=8765) as server:
        print('http://127.0.0.1:8765/full/catalog', flush=True)
        print('http://127.0.0.1:8765/partial/catalog', flush=True)
        server.serve_forever()
