"""Каталог SPEC-001 с изменяемыми ссылками для последовательных сборов."""

from .spec001_catalog import PRODUCTS, IdentityCatalog, identity_plan, set_product


class ComparisonCatalog(IdentityCatalog):
    def __init__(self):
        super().__init__()
        self.links = list(PRODUCTS)
        self.update_links()

    def update_links(self):
        self.pages['/catalog/'] = '<h1>Каталог</h1>' + ''.join(f'<a href="{path}">{path}</a>' for path in self.links)

    def add_product_and_change_price(self):
        for path in ('/products/k-01', '/sale/k-01'):
            set_product(self, path, 'K-01', '1 350,00')
        set_product(self, '/products/k-03', 'K-03', '1 490,00')
        self.links.append('/products/k-03')
        self.update_links()


def comparison_plan(origin):
    plan = identity_plan(origin)
    plan['seed_urls'] = [origin + '/catalog/']
    plan['crawl'] = {
        'mode': 'site',
        'preview_urls': [origin + '/products/k-01'],
        'max_depth': 1,
        'max_pages': 10,
        'extract_on': [{'kind': 'prefix', 'pattern': path} for path in ('/products/', '/sale/')],
    }
    return plan
