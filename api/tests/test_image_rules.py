"""Выбор элемента изображения и значения правил в предпросмотре."""

from django.test import SimpleTestCase
from lxml import html

from modules.scout.api.services.errors import ScoutError
from modules.scout.api.services.html_extract import extract_html
from modules.scout.api.services.plan import normalize_plan, plan_hash
from modules.scout.api.services.visual_rules import VisualDocument

BASE = 'https://catalog.example/items/42'
CARD = {'kind': 'css', 'selector': 'article'}
PAGE = (
    b'<main><article><h2>Chair</h2><img class="photo" src="../chair.jpg?v=1&amp;h=500">'
    b'<img class="photo" src="../chair.jpg?v=1&amp;h=500#copy"></article>'
    b'<article><div class="photo">text</div><img class="photo" src="data:image/png,a"'
    b' data-src="//cdn.example/table.webp"></article></main>'
)
PHOTO = {'name': 'photo', 'scope': 'record', 'many': True, 'kind': 'css', 'selector': 'img.photo',
         'value_source': 'image'}


class ImageRuleTests(SimpleTestCase):
    def test_page_photo_uses_its_id_before_generic_classes(self):
        document = VisualDocument(b'<img class="preload" id="main_photo" src="/cover.jpg">', 'utf-8')
        selected = next(iter(document.nodes))
        checked = document.check(source_url=BASE, record=None, field={
            'name': 'photo', 'scope': 'page', 'many': False, 'node_id': selected,
        })
        self.assertEqual(checked['field']['selector'], 'img#main_photo')
        self.assertEqual(checked['field']['value_source'], 'image')

    def test_click_matches_images_in_each_card_without_exposing_resources_in_snapshot(self):
        document = VisualDocument(PAGE, 'utf-8')
        snapshot = html.fromstring(document.editor_html())
        placeholders = snapshot.xpath('//*[@data-scout-image]')
        self.assertEqual(len(placeholders), 3)
        self.assertFalse(snapshot.xpath('//img|//*[@src]'))
        self.assertTrue(placeholders[0].text_content().strip())
        checked = document.check(
            source_url=BASE, record=CARD,
            field={'name': 'photo', 'scope': 'record', 'many': True, 'node_id': placeholders[0].get('data-scout-node')},
        )
        self.assertEqual(checked['field'], PHOTO)
        self.assertEqual([item['match_count'] for item in checked['rows']], [2, 1])
        rows = extract_html(PAGE, [PHOTO], record=CARD, source_url=BASE)
        for example, row, expected in zip(checked['rows'], rows, (
            'https://catalog.example/chair.jpg?v=1&h=500', 'https://cdn.example/table.webp',
        )):
            self.assertEqual(example['value'], row['values']['photo'])
            self.assertEqual(example['value']['images'], [{'source_url': expected, 'status': 'candidate'}])

    def test_text_selection_replaces_image_kind_and_old_text_rule_keeps_its_value(self):
        document = VisualDocument(PAGE, 'utf-8')
        title = next(uid for uid, node in document.nodes.items() if node.tag == 'h2')
        check = document.check(source_url=BASE, record=CARD, field={
            'name': 'photo', 'scope': 'record', 'many': False, 'node_id': title, 'value_source': 'image',
        })
        self.assertNotIn('value_source', check['field'])
        self.assertEqual(check['rows'][0]['value']['normalized'], 'Chair')
        text_rule = {key: value for key, value in PHOTO.items() if key != 'value_source'}
        self.assertEqual(extract_html(PAGE, [text_rule], record=CARD)[0]['values']['photo'],
                         {'raw': '\n', 'normalized': ''})

    def test_image_kind_changes_the_plan_hash_and_excludes_text_only_options(self):
        baseline = {key: value for key, value in PHOTO.items() if key != 'value_source'}
        image_plan = normalize_plan([BASE], [PHOTO], record=CARD)
        self.assertEqual(image_plan['fields'][0]['value_source'], 'image')
        self.assertNotEqual(plan_hash(image_plan), plan_hash(normalize_plan([BASE], [baseline], record=CARD)))
        self.assertEqual(image_plan, normalize_plan([BASE], image_plan['fields'], record=CARD))
        with self.assertRaises(ScoutError):
            normalize_plan([BASE], [{**PHOTO, 'conversion': {'type': 'integer'}}], record=CARD)
        with self.assertRaises(ScoutError):
            normalize_plan([BASE], [{**PHOTO, 'many': False}], record=CARD,
                           identity={'kind': 'field', 'namespace': 'catalog', 'field': 'photo'})
