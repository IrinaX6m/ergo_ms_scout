"""Неизменяемые снимки HTML в кэше проекта, не в каталоге исходников."""

import hashlib
import os
import threading
import time
from pathlib import Path

from src.config.paths import CACHE_DIR

_ROOT = CACHE_DIR / 'scout' / 'snapshots'
_READ_LIMIT = 2_000_000


def snapshot_root() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


def safe_snapshot_path(relative_path):
    root = (CACHE_DIR / 'scout' / 'snapshots').absolute()
    candidate = CACHE_DIR / relative_path
    if Path(relative_path).is_absolute() or '..' in Path(relative_path).parts:
        raise ValueError('invalid snapshot path')
    resolved = candidate.resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError('snapshot path escaped cache')
    for path in (candidate, *candidate.parents):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('snapshot path traverses a link')
        if path == CACHE_DIR:
            break
    return resolved


def store_snapshot_bytes(body: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(body).hexdigest()
    relative = f'scout/snapshots/{digest}.html'
    target = CACHE_DIR / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        return digest, relative
    temporary = target.with_name(
        f'{digest}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.partial'
    )
    try:
        temporary.write_bytes(body)
        for _ in range(5):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if target.is_file():
                    break
                time.sleep(0.02)
        else:
            if not target.is_file():
                os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return digest, relative


def read_snapshot_bytes(relative_path: str, max_bytes: int = _READ_LIMIT, *, snapshot=None) -> bytes:
    from .retention_locks import resource_lock

    path = safe_snapshot_path(relative_path)
    with resource_lock('blob:' + path.stem, shared=True):
        if snapshot is not None:
            from ..models import PageSnapshot
            from .errors import ScoutError
            state = PageSnapshot.objects.get(pk=snapshot.pk).html_availability
            if state in ('expired', 'purging'):
                raise ScoutError('snapshot_content_expired', 'HTML снимка удалён по сроку хранения')
        if not path.exists() and snapshot is not None:
            from ..models import PageSnapshot
            PageSnapshot.objects.filter(pk=snapshot.pk).update(html_availability='missing')
        body = path.read_bytes()
    if body.startswith(b'\x1f\x8b'):
        return _gzip_limited(body, max_bytes)
    return body


def _gzip_limited(body: bytes, max_bytes: int) -> bytes:
    import gzip
    import io

    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
        unpacked = stream.read(max_bytes + 1)
    if len(unpacked) > max_bytes:
        raise ValueError('snapshot exceeds read limit')
    return unpacked
