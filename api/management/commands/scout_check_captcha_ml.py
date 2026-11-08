"""Воспроизводимая проба локальной модели; синтетические картинки, не проверка обхода сайта."""

import io
import json
from time import monotonic

from django.core.management.base import BaseCommand, CommandError

from ...services.captcha_ml import recognize_text
from ...services.errors import ScoutError


class Command(BaseCommand):
    help = 'Проверить локальную модель на трёх синтетических текстовых картинках без сетевых запросов к сайтам'

    def handle(self, *args, **options):
        from PIL import Image, ImageDraw, ImageFont

        rows = []
        for index, expected in enumerate(('48271', 'K7M2P', ''), 1):
            image = Image.new('RGB', (240, 80), 'white')
            if expected:
                ImageDraw.Draw(image).text((16, 12), expected, font=ImageFont.load_default(size=44), fill='black')
            data = io.BytesIO()
            image.save(data, format='PNG')
            started = monotonic()
            try:
                answer = recognize_text(data.getvalue(), min_length=5, max_length=5)
                correct, code = answer == expected, None
            except ScoutError as exc:
                correct, code = not expected and exc.code == 'captcha_unrecognized', exc.code
            rows.append({'case': index, 'correct': correct, 'seconds': round(monotonic() - started, 3), 'code': code})
        # Не печатаем картинки, ответы модели или реквизиты браузерной сессии.
        self.stdout.write(json.dumps({'synthetic_only': True, 'cases': rows,
                                      'passed': sum(row['correct'] for row in rows)}, ensure_ascii=False))
        if not all(row['correct'] for row in rows):
            raise CommandError('Локальная проба CAPTCHA не прошла все контрольные случаи')
