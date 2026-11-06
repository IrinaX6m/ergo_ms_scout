from django.core.management.base import BaseCommand, CommandError

from ...services.errors import ScoutError
from ...services.proxy_profiles import rotate_proxy_keys


class Command(BaseCommand):
    help = 'Перешифровать реквизиты прокси Scout активным ключом.'

    def handle(self, *args, **options):
        try:
            count = rotate_proxy_keys()
        except ScoutError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f'Перешифровано версий прокси: {count}')
