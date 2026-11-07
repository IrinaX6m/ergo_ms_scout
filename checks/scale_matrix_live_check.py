"""Изолированный прогон SCALE-001: python modules/scout/checks/scale_matrix_live_check.py 200.

200..10000 страниц, по 20 карточек. Пределы меняются только в своей временной БД
до подтверждения; рабочая нормализация и службы не меняются. Требуется локальная PostgreSQL.
"""

import json
import os
import secrets
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from threading import Event, Thread

import psycopg2
from psycopg2 import sql
import requests
import yaml

root = Path(__file__).resolve().parents[3]
assert len(sys.argv)==2 and sys.argv[1].isdigit() and 200<=int(sys.argv[1])<=10000, 'Specify 200..10000 pages'

reuse_max = int(os.environ.get('SCOUT_SCALE_DB_REUSE_MAX', '50'))
suffix = secrets.token_hex(4)
work = root / 'virtual_env/cache/tmp' / f'scout-scale-current-{sys.argv[1]}-{suffix}'
work.mkdir()
database_name = f'scout_scale001_{suffix}'
settings_name = 'scout_scale_settings'
(work / f'{settings_name}.py').write_text(
    'import os\nfrom src.config.patterns.development import *\nfrom scout_scale_probe import install_publish\ninstall_publish()\n'
    'from celery.signals import worker_init\n'
    'def install_timing(sender, **kwargs):\n'
    '    from scout_scale_probe import install_worker\n'
    '    install_worker()\n'
    '    print("scout-db-reuse-effective:", sender.app.conf.get("CELERY_DB_REUSE_MAX"), flush=True)\n'
    'worker_init.connect(install_timing, weak=False)\n'
    "DATABASES = {'default': {**DATABASES['default'], 'NAME': os.environ['SCOUT_SCALE_DATABASE']}}\n"
    'from pathlib import Path\n'
    'from modules.scout.api.services import snapshot_store\n'
    'snapshot_store.CACHE_DIR = Path(os.environ["SCOUT_SCALE_DIR"]) / "cache"\n'
    'snapshot_store._ROOT = snapshot_store.CACHE_DIR / "scout" / "snapshots"\n'
    'if CACHES["default"]["BACKEND"].endswith("FileBasedCache"):\n'
    '    CACHES["default"]["LOCATION"] = str(snapshot_store.CACHE_DIR / "django")\n',
    encoding='utf-8',
)
config = yaml.safe_load((root / 'databases.yaml').read_text(encoding='utf-8-sig'))['databases']['default']
assert config['engine'] == 'postgresql' and config['host'] in ('127.0.0.1', 'localhost', '::1')
sys.path.insert(0, str(root))
import csv
import io
from urllib.parse import urljoin, urlsplit

import psutil
from modules.scout.api.tests.fixtures.spec003_catalog import CatalogServer, ROWS_PER_ITEM, CASES

CASES[f'p{sys.argv[1]}']=int(sys.argv[1])-1
fixture = CatalogServer()
Thread(target=fixture.serve_forever, daemon=True).start()
origin = f'http://127.0.0.1:{fixture.server_port}'
import socket
with socket.socket() as api_socket, socket.socket() as media_socket:
    api_socket.bind(('127.0.0.1',0)); media_socket.bind(('127.0.0.1',0))
    api_port,media_port=api_socket.getsockname()[1],media_socket.getsockname()[1]
api = f'http://127.0.0.1:{api_port}/api/'
media = f'http://127.0.0.1:{media_port}'
env = dict(os.environ,
    PYTHONPATH=os.pathsep.join((str(work), str(root), str(root / 'core/api'), str(root / 'core/media_api/src'))),
    DJANGO_SETTINGS_MODULE=settings_name,
    SCOUT_SCALE_DATABASE=database_name,
    PROCESS_MODULES='scout', SCOUT_TASK_RUNNER='celery',
    SCOUT_WORKER_DB_REUSE_MAX=str(reuse_max), SCOUT_SCALE_DIR=str(work),
    SCOUT_TRUSTED_FETCH_ENDPOINTS=f'127.0.0.1:{fixture.server_port}',
    ERGO_SEARCH_ENABLED='false', ERGO_REALTIME='http_polling',
    ERGO_MEDIA='remote', MEDIA_ACCESS_MODE='remote',
    MEDIA_API_HOST='127.0.0.1', MEDIA_API_PORT=str(media_port), MEDIA_API_BIND_HOST='127.0.0.1',
    MEDIA_API_HEALTH_PUBLIC='true', MEDIA_API_URL=media, MEDIA_API_INTERNAL_URL=media,
    MEDIA_API_INTERNAL_KEY=secrets.token_urlsafe(32),
    MEDIA_STORAGE_TYPE='local', MEDIA_STORAGE_PATH=str(work / 'media'),
    ERGO_LOGS_DIR=str(work / 'logs'),
    CELERY_BROKER_URL='sqla+sqlite:///' + (work / 'broker.sqlite3').as_posix(),
    CELERY_RESULT_BACKEND='db+sqlite:///' + (work / 'results.sqlite3').as_posix(),
    PYTHONUTF8='1', PYTHONUNBUFFERED='1',
)
session = requests.Session()
session.trust_env = False
children = {}
summary = {'cases': {}}
created_database = False
django_ready = False
def log(message):
    print(message, flush=True)

def manage_database(create):
    with closing(psycopg2.connect(dbname=config['name'], host=config['host'], port=config['port'],
                                  user=config['user'], password=config['password'])) as conn:
        conn.autocommit = True
        command = sql.SQL('CREATE DATABASE {}' if create else 'DROP DATABASE {}')
        with conn.cursor() as cursor:
            cursor.execute(command.format(sql.Identifier(database_name)))

def start(name, *args, settings=None):
    with (work / f'{name}.log').open('wb') as output:
        child = subprocess.Popen([sys.executable, *args], cwd=root, env=dict(env, DJANGO_SETTINGS_MODULE=settings or settings_name), stdout=output,
                                 stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    children[name] = child
    return child

def stop(name):
    child = children.pop(name)
    if child.poll() is None:
        descendants = psutil.Process(child.pid).children(recursive=True)
        for process in reversed(descendants):
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(descendants, timeout=5)
        if child.poll() is None:
            child.kill()
    return child.wait(timeout=10)

def assert_processes():
    import shutil
    if psutil.virtual_memory().available < 2*1024**3 or shutil.disk_usage(work).free < 5*1024**3:
        raise RuntimeError('Test stopped: less than 2 GiB free RAM or 5 GiB free disk')
    for name, child in children.items():
        assert child.poll() is None, f'{name} exited with {child.returncode}'

def wait_for(label, predicate, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert_processes()
        value = predicate()
        if value:
            return value
        time.sleep(.3)
    raise RuntimeError(f'Timed out waiting for {label}')

def start_worker(name, queue):
    # The launcher selects the normal Scout queue itself.
    args = [] if queue == 'scout' else [f'--queues={queue}']
    start(name, str(root / 'core/api/scripts/start_celery_worker.py'), '--module=scout',
          '--concurrency=1', '--pool=solo', f'--hostname={name}@local', *args)
    log_path = work / f'{name}.log'
    wait_for(f'{name} ready', lambda: 'Connected to sqla+sqlite:' in log_path.read_text(errors='replace'), 65)
    worker_log = log_path.read_text(errors='replace')
    assert f'scout-db-reuse-effective: {reuse_max or None}' in worker_log, worker_log[-1600:]


def request(method, path, code=200, **kwargs):
    response = session.request(method, api + path, timeout=120 if path.endswith('export/') else 30, **kwargs)
    assert response.status_code == code, f'{method} {path}: {response.status_code} {response.text[:380]}'
    payload = response.json()
    return payload.get('data', payload)

def status(path, expected, seconds=40):
    def check():
        result = request('GET', path)
        if result['status'] == expected:
            return result
        if result['status'] in ('completed', 'completed_with_errors', 'failed', 'cancelled'):
            raise AssertionError(f"Expected {expected}, got {result['status']}: {result.get('error_summary')}")
    return wait_for(expected, check, seconds)

from shutil import copyfile
from statistics import median

copyfile(Path(__file__).with_name('scale_probe.py'), work / 'scout_scale_probe.py')

def stats_ms(times):
    times = sorted(times)
    if not times:
        return {'count': 0}
    p95 = times[(len(times) * 95 + 99) // 100 - 1]
    return {'count': len(times), 'median_ms': round(median(times) / 1e6, 3),
            'p95_ms': round(p95 / 1e6, 3), 'max_ms': round(times[-1] / 1e6, 3)}

def seconds(value):
    return round(value / 1e9, 3)

def events():
    result = []
    for path in work.glob('probe-*.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return result

def profile(run, start, end):
    task_data = {str(public_id): (kind, int(created.timestamp() * 1e9))
                 for public_id, kind, created in run.tasks.values_list('public_id', 'kind', 'created_at')}
    relevant = {key for key, (_, created) in task_data.items() if created >= start}
    expected = len(relevant)
    def captured():
        data = events()
        done = {row['args'][0] for row in data if row['event'] == 'worker'
                and row['name'] == 'execute_scout_task' and row['changed'] and row['args'][0] in relevant}
        return data if len(done) == expected else None
    data = wait_for('profiling events', captured, 15)
    producers = {row['id']: row for row in data if row['event'] == 'published'}
    workers = [row for row in data if row['event'] == 'worker' and start <= row['start'] <= end and (
        (row['name'] == 'execute_scout_task' and row['args'][0] in relevant)
        or (row['name'] == 'dispatch_scout_pending' and (not row['args'] or row['args'][0] == str(run.public_id)))
    )]
    first_publish = {}
    for row in producers.values():
        if row['name'] == 'execute_scout_task' and row['args'][0] in relevant:
            task_id = row['args'][0]
            first_publish[task_id] = min(first_publish.get(task_id, row['start']), row['start'])
    assert len(first_publish) == expected
    grouped = {}
    for row in workers:
        kind = 'dispatch' if row['name'] == 'dispatch_scout_pending' else task_data[row['args'][0]][0]
        grouped.setdefault(kind, []).append(row)
    report = {}
    for kind, rows in grouped.items():
        paired = [(row, producers[row['id']]) for row in rows if row['id'] in producers]
        assert len(paired) == len(rows), (kind, len(paired), len(rows))
        useful = [(worker, publication) for worker, publication in paired if worker['changed'] is not False]
        assert all(row['state'] == 'SUCCESS' for row in rows)
        assert all(worker['received'] is not None for worker, _ in paired)
        stages = {}
        for name in sorted({stage for row in rows for stage in row['stages']}):
            stages[name] = {
                'wall_s': seconds(sum(row['stages'].get(name, [0, 0])[0] for row in rows)),
                'calls': sum(row['stages'].get(name, [0, 0])[1] for row in rows),
                'postgres_s': seconds(sum(row['db_stages'].get(name, [0, 0])[0] for row in rows)),
                'postgres_calls': sum(row['db_stages'].get(name, [0, 0])[1] for row in rows),
            }
        report[kind] = {
            'deliveries': len(rows), 'duplicates_ignored': sum(row['changed'] is False for row in rows),
            'worker_s': seconds(sum(row['total'] for row in rows)),
            'postgres_s': seconds(sum(row['db'][0] for row in rows)),
            'postgres_calls': sum(row['db'][1] for row in rows),
            'broker_wait_all': stats_ms(max(0, worker['received'] - publication['end']) for worker, publication in paired),
            'broker_wait_used': stats_ms(max(0, worker['received'] - publication['end']) for worker, publication in useful),
            'received_to_prerun': stats_ms(max(0, worker['start'] - worker['received']) for worker, _ in paired),
            'publish_broker': stats_ms(publication['end'] - publication['start'] for _, publication in paired),
            'consumer_beat_before_publish_signal': sum(worker['received'] < publication['end'] for worker, publication in paired),
            'stages': stages,
        }
        if kind != 'dispatch':
            report[kind]['postgres_to_publish'] = stats_ms(
                max(0, published - task_data[key][1])
                for key, published in first_publish.items() if task_data[key][0] == kind
            )
    assert sum(row['changed'] is True for row in workers) == expected, (len(workers), expected)
    return report

def measure(operation):
    names = ('django', 'media', f'scale_matrix_{sys.argv[1]}_1', f'scale_matrix_{sys.argv[1]}_2')
    trees = {}
    for name in names:
        process = psutil.Process(children[name].pid)
        trees[name] = (process, *process.children(recursive=True))

    def rss(tree):
        total = 0
        for process in tree:
            try:
                total += process.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        return total

    before = {name: rss(tree) for name, tree in trees.items()}
    assert all(value > 30 * 1048576 for value in before.values()), before
    peaks = before.copy()
    finished = Event()

    def sample():
        while not finished.is_set():
            for name, tree in trees.items():
                peaks[name] = max(peaks[name], rss(tree))
            finished.wait(.1)

    monitor = Thread(target=sample, daemon=True)
    monitor.start()
    started = time.perf_counter()
    try:
        value = operation()
    finally:
        elapsed = time.perf_counter() - started
        finished.set()
        monitor.join()
    return value, {
        'seconds': round(elapsed, 3),
        'peak_rss_mib': {name: round(peak / 1048576, 2) for name, peak in peaks.items()},
        'delta_rss_mib': {name: round((peak - before[name]) / 1048576, 2) for name, peak in peaks.items()},
    }


def check_result_api(path, size):
    expected = (size - 1) * ROWS_PER_ITEM
    status = request('GET', path, params={'summary': 1})
    assert status['status'] == 'completed' and status['record_count'] == expected and status['snapshot_count'] == size
    paged = []
    params = {'limit': 200}
    pages = 0
    seen_cursors = set()
    while True:
        page = request('GET', path + 'records/', params=params)
        assert len(page['records']) <= params['limit']
        paged.extend(page['records'])
        pages += 1
        cursor = page['next_cursor']
        if cursor is None:
            break
        assert cursor == page['records'][-1]['public_id'] and cursor not in seen_cursors
        seen_cursors.add(cursor)
        params['cursor'] = cursor

    assert len(paged) == expected and len({row['public_id'] for row in paged}) == expected
    assert pages == (expected + 199) // 200
    expected_titles = {f'{item}-{row}' for item in range(1, size) for row in range(1, ROWS_PER_ITEM + 1)}
    assert {record['values']['title']['normalized'] for record in paged} == expected_titles
    for record in paged:
        title = record['values']['title']['normalized']
        item, row = map(int, title.split('-'))
        values = {'title': title, 'price': str(item + row)}
        assert {key: cell['normalized'] for key, cell in record['values'].items()} == values
        assert len(record['evidence']) == len(values)
        assert {e['field_path']: e['normalized_value'] for e in record['evidence']} == values
        for evidence in record['evidence']:
            assert evidence['source_url'] == f'{origin}/p{size}/items/{item}'
            assert evidence['raw_value'] == record['values'][evidence['field_path']]['raw']
            assert evidence['locator'] and evidence['extractor_id'] and evidence['extractor_version']
    log(f'p{size}: all {expected} records and {2 * expected} Evidence entries verified in {pages} pages.')

    exports = {}
    for kind in ('json', 'csv'):
        metadata, upload = measure(lambda: request('POST', path + 'export/', json={'kind': kind}))
        signed = urljoin(media + '/', metadata['download_url'])
        assert urlsplit(signed).netloc == urlsplit(media).netloc and urlsplit(signed).query

        def download():
            with requests.Session() as downloader:
                downloader.trust_env = False
                response = downloader.get(signed, timeout=60)
                response.raise_for_status()
                return response.content

        content, transfer = measure(download)
        if kind == 'json':
            assert json.loads(content) == paged
        else:
            assert content.startswith(b'\xef\xbb\xbf')
            rows = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
            assert len(rows) == expected
            for actual, record in zip(rows, paged):
                assert actual == {'public_id': record['public_id'], **{
                    name: cell['normalized'] for name, cell in record['values'].items()
                }}
        exports[kind] = {'bytes': len(content), 'generate_upload': upload, 'download': transfer}
        log(f'p{size}: {kind} verified, {len(content)} bytes, generated/uploaded in {upload["seconds"]}s.')
    return {'pages': pages, 'records': expected, 'evidence': 2 * expected, 'exports': exports}


def check_case(size):
    case = f'p{size}'
    base = f'/{case}/'
    job = request('POST', 'scout/jobs/', 201, json={
        'title': f'SCALE-001 {size}', 'seed_urls': [origin + base + 'catalog'],
        'record': {'kind': 'css', 'selector': 'article'},
        'fields': [{'name': 'title', 'kind': 'css', 'selector': 'h2', 'scope': 'record'},
                   {'name': 'price', 'kind': 'css', 'selector': '.price', 'scope': 'record'}],
        'crawl': {'mode': 'site', 'max_depth': 1, 'max_pages': size, 'max_seconds': 3600,
                  'frontier_cap': size + 10, 'parallel_fetch': 2,
                  'visit': [{'kind': 'prefix', 'pattern': base + 'catalog'},
                            {'kind': 'prefix', 'pattern': base + 'items/'}],
                  'extract_on': [{'kind': 'prefix', 'pattern': base + 'items/'}]},
    })
    # Raise only this temporary database's plan ceilings before the normal approval flow.
    from modules.scout.api.services.plan import plan_hash

    revision = JobRevision.objects.get(job__public_id=job['public_id'])
    assert revision.crawl['max_pages'] == min(size, 200)
    assert revision.crawl['frontier_cap'] == min(size + 10, 500)
    revision.crawl = {**revision.crawl, 'max_pages': size, 'frontier_cap': size + 10}
    plan = {field: getattr(revision, field) for field in ('seed_urls', 'record', 'fields', 'limits', 'crawl')}
    revision.plan_hash = plan_hash(plan)
    revision.save(update_fields=['crawl', 'plan_hash'])
    run = request('POST', f"scout/jobs/{job['public_id']}/explore/", 202, json={})
    path = f"scout/runs/{run['public_id']}/"
    status(path, 'awaiting_confirmation')
    request('POST', path + 'approve/', json={})
    log(f'{case}: {run["public_id"]}; start.')
    started = time.time_ns()
    terminal = ('completed', 'completed_with_errors', 'failed', 'cancelled')
    last_message = time.monotonic()

    def check_state():
        nonlocal last_message
        current = Run.objects.get(public_id=run['public_id'])
        if current.status in terminal:
            return current.status
        if time.monotonic() - last_message >= 25:
            log(f'p{size}: {current.snapshots.count()} snapshots, {current.records.count()} records.')
            last_message = time.monotonic()
        return None

    def collect():
        request('POST', path + 'start/', 202, json={})
        return wait_for('crawl terminal state', check_state, 3630)

    state, crawl_metrics = measure(collect)
    ended = time.time_ns()
    job_run = Run.objects.get(public_id=run['public_id'])
    if (state != 'completed' or job_run.stop_reason or job_run.snapshots.count() != size
            or job_run.records.count() != (size-1)*ROWS_PER_ITEM):
        summary['cases'][case] = {
            'status':state,'wall_seconds':seconds(ended-started),'crawl_metrics':crawl_metrics,
            'snapshots':job_run.snapshots.count(),'records':job_run.records.count(),
            'expected_snapshots':size,'expected_records':(size-1)*ROWS_PER_ITEM,
            'stop_reason':job_run.stop_reason,'error_summary':job_run.error_summary,
            'result_verified':False,
        }
        (work/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        raise AssertionError(f'{case} stopped with {state}; see result.json')
    assert job_run.snapshots.count() == size and job_run.records.count() == (size - 1) * ROWS_PER_ITEM
    assert job_run.stop_reason == '' and job_run.tasks.exclude(status='succeeded').count() == 0
    assert job_run.crawl_urls.filter(state='done').count() == size
    assert Attempt.objects.filter(task__run=job_run, task__kind='fetch').count() == size
    with fixture.hit_lock:
        actual_hits = {item: hits for (name, item), hits in fixture.hits.items() if name == case}
    assert actual_hits == {'catalog': 1, **{item: 1 for item in range(1, size)}}
    titles = list(job_run.records.values_list('values__title__normalized', flat=True))
    assert len(set(titles)) == len(titles)
    assert set(titles) == {f'{item}-{row}' for item in range(1, size) for row in range(1, ROWS_PER_ITEM + 1)}
    stage_profile = profile(job_run, started, ended)
    deliveries = sum(group['deliveries'] for group in stage_profile.values())
    connects = sum(group['stages'].get('postgres_connect', {}).get('calls', 0) for group in stage_profile.values())
    if reuse_max:
        assert 0 < connects < deliveries // 3, (connects, deliveries)
    else:
        assert connects >= deliveries * .95, (connects, deliveries)
    log(f'p{size}: {connects} PostgreSQL connections for {deliveries} messages, reuse={reuse_max}.')
    summary['cases'][case] = {'wall_seconds': seconds(ended - started), 'status': state,
                              'snapshots': size, 'records': job_run.records.count(), 'profile': stage_profile,
                              'dispatch_requested': sum(
                                  event['event'] == 'published'
                                  and event['name'] == 'dispatch_scout_pending'
                                  and started <= event['start'] <= ended
                                  and event['args'] == [str(job_run.public_id)]
                                  for event in events()
                              )}
    snapshot_root = (work / 'cache').resolve()
    snapshot_bytes = 0
    for relative, byte_size in job_run.snapshots.values_list('content_path', 'byte_size'):
        local_path = (snapshot_root / relative).resolve()
        assert local_path.is_relative_to(snapshot_root) and local_path.stat().st_size == byte_size
        snapshot_bytes += byte_size
    summary['cases'][case].update(snapshot_bytes=snapshot_bytes, crawl_metrics=crawl_metrics)
    summary['cases'][case].update(collection_verified=True, result_api_verified=False)
    (work / 'result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    log(f'p{size}: collection finished in {crawl_metrics["seconds"]}s with {snapshot_bytes} snapshot bytes.')
    try:
        summary['cases'][case]['result_api'] = check_result_api(path, size)
    except Exception as error:
        summary['cases'][case]['result_api_error'] = type(error).__name__
        (work / 'result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        raise
    summary['cases'][case]['result_api_verified'] = True
    (work / 'result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    log(f'{case}: {size} snapshots, {job_run.records.count()} records, {seconds(ended - started)}s.')

def main():
    global created_database, django_ready, Run, Attempt, JobRevision
    manage_database(create=True)
    created_database = True
    with (work / 'migrate.log').open('wb') as output:
        subprocess.run([sys.executable, '-m', 'src.manage', 'migrate', '--noinput'], cwd=root, env=env,
                       stdout=output, stderr=subprocess.STDOUT, check=True, timeout=150,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    os.environ.update(env)
    sys.path[:0] = [str(work), str(root / 'core/api')]
    import django
    from src.config.celery import ensure_django_celery_configured
    django.setup()
    django_ready = True
    ensure_django_celery_configured()
    from django.contrib.auth import get_user_model
    from django.db import connection
    from modules.scout.api.models import Attempt, JobRevision, Run

    from modules.scout.api.services.snapshot_store import snapshot_root
    assert snapshot_root().resolve() == (work / 'cache/scout/snapshots').resolve()
    assert connection.vendor == 'postgresql' and connection.settings_dict['NAME'] == database_name
    with connection.cursor() as cursor:
        cursor.execute('SHOW server_version')
        pg_version = cursor.fetchone()[0]
    summary['setup'] = {'postgresql': pg_version, 'broker': 'Celery SQLAlchemy / SQLite',
                        'django_conn_max_age_s': connection.settings_dict['CONN_MAX_AGE'],
                        'logical_cpus': psutil.cpu_count(), 'ram_mib': round(psutil.virtual_memory().total / 1048576),
                        'free_ram_mib_at_start': round(psutil.virtual_memory().available/1048576), 'code': subprocess.check_output(['git','-C',str(root/'modules/scout'),'rev-parse','HEAD'], text=True).strip(), 'workers': 2, 'pool': 'solo', 'worker_db_reuse_max': reuse_max, 'method': 'per-message Celery events and Django PostgreSQL timings',
                        'rows_per_item': ROWS_PER_ITEM, 'rss_sampling_ms': 100, 'cache_isolated': True, 'working_page_limit': 200, 'expanded_limit_only_in_isolated_database': True}
    password = secrets.token_urlsafe(24)
    get_user_model().objects.create_superuser(username='scout-scale001', password=password)
    start('django', '-m', 'src.manage', 'runserver', f'127.0.0.1:{api_port}', '--noreload')
    start('media', '-m', 'media_server.manage', 'runserver', f'127.0.0.1:{media_port}', '--noreload',
          settings='media_server.settings.development')
    start('beat', '-m', 'celery', '-A', 'src', 'beat', '-l', 'INFO',
          '-S', 'celery.beat:PersistentScheduler', '-s', str(work / 'beat-schedule'))
    start_worker(f'scale_matrix_{sys.argv[1]}_1', 'scout')
    start_worker(f'scale_matrix_{sys.argv[1]}_2', 'scout')

    def ready(url, codes):
        try:
            return session.get(url, timeout=2).status_code in codes
        except requests.RequestException:
            return False
    wait_for('Django', lambda: ready(api + 'system/ready/', (200,)), 65)
    wait_for('Media API', lambda: ready(media + '/health/', (200, 404)), 65)
    auth = request('POST', 'cms/adp/authorization/', json={'username': 'scout-scale001', 'password': password, 'remember_me': False})
    session.headers['Authorization'] = 'Bearer ' + auth['access']
    log('Live PostgreSQL, Django, Beat and two Celery workers ready.')
    check_case(int(sys.argv[1]))

log(f'Artifacts: {work}')
try:
    main()
finally:
    for name in reversed(list(children)):
        stop(name)
    fixture.shutdown()
    fixture.server_close()
    if django_ready:
        from django.db import connections
        connections.close_all()
    if created_database:
        manage_database(create=False)
        log('Temporary PostgreSQL database dropped.')
