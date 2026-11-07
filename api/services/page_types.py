"""Общий выбор правил страницы для предпросмотра и основного сбора."""

from urllib.parse import urlsplit

from .errors import ScoutError
from .url_norm import resolve_url, rules_match


def matching_page_types(snapshot, crawl: dict) -> list[dict]:
    target = snapshot.final_url or snapshot.source_url
    normalized, _reason = resolve_url(target, target, crawl.get('drop_query'))
    if normalized is None:
        return []
    return [page_type for page_type in crawl['page_types'] if rules_match(normalized, page_type['match'])]


def effective_fields(fields: list[dict], page_type: dict) -> list[dict]:
    selectors = page_type.get('selectors', {})
    return [{**field, **selectors.get(field['name'], {})} for field in fields]


def ambiguous_type_error(snapshot, matches: list[dict]) -> ScoutError:
    path = urlsplit(snapshot.final_url or snapshot.source_url).path or '/'
    names = ', '.join(page_type['id'] for page_type in matches)
    return ScoutError('page_type_ambiguous', f'Для страницы подходят несколько типов: {names}. Путь: {path[:120]}')
