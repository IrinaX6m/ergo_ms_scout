"""Типизированные значения полей Scout и формат их выдачи."""

import re
from datetime import date
from unicodedata import category

from django.utils.translation import gettext as _

from .constants import FIELD_TEXT_LIMIT
from .errors import ScoutError

TYPED_VALUE_FORMAT = 'typed_v1'

_GROUP_SPACE = ' \u00a0\u202f'
_MONEY = re.compile(
    rf'(?P<whole>[0-9]+|[0-9]{{1,3}}(?:[{_GROUP_SPACE}][0-9]{{3}})+)'
    rf'(?:(?P<separator>[,.])(?P<fraction>[0-9]{{1,2}}))?'
    rf'(?:[{_GROUP_SPACE}]*(?P<currency>[A-Z]{{3}}|[^\w\s]))?'
)
_INTEGER = re.compile(r'[+-]?[0-9]+')
_DATE = re.compile(r'([0-9]{2})\.([0-9]{2})\.([0-9]{4})')
_MAX_INTEGER = '2147483647'


def use_typed_values(value_format) -> bool:
    if value_format is None:
        return False
    if value_format == TYPED_VALUE_FORMAT:
        return True
    raise ScoutError('invalid_value_format', _('Допустимый формат значений: typed_v1'))


def clean_conversion(conversion, *, many: bool) -> dict:
    if many or not isinstance(conversion, dict):
        raise ScoutError('invalid', _('Преобразование доступно только для одного значения поля'))
    kind = conversion.get('type')
    if kind == 'money' and conversion.get('currency') == 'RUB' and conversion.get('decimal_separator') in (',', '.'):
        if conversion.keys() == {'type', 'currency', 'decimal_separator'}:
            return dict(conversion)
    elif kind == 'integer' and conversion.keys() == {'type'}:
        return dict(conversion)
    elif kind == 'date' and conversion == {'type': 'date', 'format': 'DD.MM.YYYY'}:
        return dict(conversion)
    raise ScoutError('invalid', _('Неподдерживаемый тип или параметры преобразования поля'))


def typed_cell(raw: str | None, conversion: dict) -> dict:
    kind = conversion['type']
    value, code = None, None
    if raw is None:
        status = 'missing'
    elif len(raw) > FIELD_TEXT_LIMIT:
        status, code = 'invalid', 'value_truncated'
    elif not (text := raw.strip()):
        status = 'empty'
    else:
        if kind == 'money':
            value, code = _money(text, conversion)
        elif kind == 'integer':
            value, code = _integer(text)
        else:
            value, code = _date(text)
        status = 'invalid' if code else 'ok'
    return {'type': kind, 'status': status, 'value': value, 'error': {'code': code} if code else None}


def _money(text: str, conversion: dict) -> tuple[dict | None, str | None]:
    match = _MONEY.fullmatch(text)
    if match is None:
        return None, 'invalid_decimal'
    whole, separator, fraction, currency = match.groups()
    if separator and separator != conversion['decimal_separator']:
        return None, 'invalid_decimal'
    if currency and currency not in ('₽', conversion['currency']):
        if len(currency) == 3 or category(currency) == 'Sc':
            return None, 'currency_mismatch'
        return None, 'invalid_decimal'
    digits = ''.join(char for char in whole if char not in _GROUP_SPACE).lstrip('0') or '0'
    return {'amount': f"{digits}.{(fraction or '').ljust(2, '0')}", 'currency': conversion['currency']}, None


def _integer(text: str) -> tuple[int | None, str | None]:
    if _INTEGER.fullmatch(text) is None:
        return None, 'invalid_integer'
    digits = text.lstrip('+-').lstrip('0') or '0'
    if (text.startswith('-') and digits != '0') or (len(digits), digits) > (len(_MAX_INTEGER), _MAX_INTEGER):
        return None, 'value_out_of_range'
    return int(digits), None


def _date(text: str) -> tuple[str | None, str | None]:
    match = _DATE.fullmatch(text)
    if match is not None:
        day, month, year = map(int, match.groups())
        try:
            return date(year, month, day).isoformat(), None
        except ValueError:
            pass
    return None, 'invalid_date'


def legacy_values(values: dict) -> dict:
    return {
        name: {key: value for key, value in cell.items() if key != 'typed'}
        if isinstance(cell, dict) and 'typed' in cell else cell
        for name, cell in values.items()
    }


def missing_typed_fields(values: dict) -> set[str]:
    return {
        name for name, cell in values.items()
        if isinstance(cell, dict) and (cell.get('typed') or {}).get('status') == 'missing'
    }


def typed_csv_columns(fields: list[dict]) -> list[str]:
    columns = ['public_id']
    for field in fields:
        name = field['name']
        columns.append(name)
        if conversion := field.get('conversion'):
            if conversion['type'] == 'money':
                columns.append(f'{name}__currency')
            columns.extend((f'{name}__status', f'{name}__error'))
    return columns
