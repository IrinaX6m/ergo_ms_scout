"""Контрольные страницы для проверки идентичности товаров SPEC-001."""

from .spec002_catalog import CatalogServer


PRODUCTS = {
    '/products/k-01': ('K-01', '1 250,00'),
    '/sale/k-01': ('K-01', '1 250,00'),
    '/products/k-02': ('K-02', '990,00'),
    '/products/no-sku': (None, '800,00'),
}


def set_product(site, path, sku, price):
    code = f'<span class="sku">{sku}</span>' if sku is not None else ''
    site.pages[path] = f'<h1>Чайник</h1>{code}<span class="price">{price} ₽</span>'


class IdentityCatalog(CatalogServer):
    def __init__(self):
        super().__init__()
        self.pages.clear()
        for path, (sku, price) in PRODUCTS.items():
            set_product(self, path, sku, price)


def identity_plan(origin):
    return {
        'title': 'Контрольный каталог',
        'seed_urls': [origin + path for path in PRODUCTS],
        'record': None,
        'fields': [
            {'name': 'sku', 'kind': 'css', 'selector': '.sku', 'scope': 'page', 'many': False},
            {'name': 'title', 'kind': 'css', 'selector': 'h1', 'scope': 'page', 'many': False},
            {'name': 'price', 'kind': 'css', 'selector': '.price', 'scope': 'page', 'many': False,
             'conversion': {'type': 'money', 'currency': 'RUB', 'decimal_separator': ','}},
        ],
        'identity': {'kind': 'sku', 'namespace': 'demo_catalog', 'field': 'sku'},
    }
