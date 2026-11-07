"""Изолированная живая проверка SCALE-001: создаёт и удаляет только собственную тестовую БД."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from threading import Thread

import psutil
import psycopg2
from psycopg2 import sql
import requests
import yaml


ROOT = Path(__file__).resolve().parents[3]
SUFFIX = secrets.token_hex(4)
WORK = ROOT / 'virtual_env/cache/tmp' / f'scout-retention-live-{SUFFIX}'
WORK.mkdir()
DB_NAME = f'scout_retention_{SUFFIX}'
SETTINGS_NAME = 'scout_retention_live_settings'
sys.path.insert(0, str(ROOT))
from modules.scout.api.tests.fixtures.ext002_catalog import ComparisonCatalog, comparison_plan

PROCESSES = {}
ALL_PROCESSES = []
SESSION = requests.Session()
SESSION.trust_env = False


def emit(message):
    print(message, flush=True)


def free_ports():
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0))
        second.bind(('127.0.0.1', 0))
        return first.getsockname()[1], second.getsockname()[1]


def change_database(create):
    config = yaml.safe_load((ROOT / 'databases.yaml').read_text(encoding='utf-8-sig'))['databases']['default']
    assert config['engine'] == 'postgresql' and config['host'] in ('127.0.0.1', 'localhost', '::1')
    with closing(psycopg2.connect(dbname=config['name'], host=config['host'], port=config['port'],
                                  user=config['user'], password=config['password'])) as connection:
        connection.autocommit = True
        statement = sql.SQL('CREATE DATABASE {}' if create else 'DROP DATABASE {}')
        with connection.cursor() as cursor:
            cursor.execute(statement.format(sql.Identifier(DB_NAME)))


def start(name, env, *command):
    with (WORK / f'{name}.log').open('wb') as output:
        PROCESSES[name] = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
        ALL_PROCESSES.append(PROCESSES[name])


def stop(process):
    if process.poll() is None:
        try:
            descendants = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        for child in reversed(descendants):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        process.terminate()
        psutil.wait_procs(descendants, timeout=5)
    process.wait(timeout=10)


def wait_for(label, predicate, seconds=55):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for name, process in PROCESSES.items():
            if process.poll() is not None:
                raise RuntimeError(f'{name} exited with {process.returncode}. See {name}.log.')
        result = predicate()
        if result:
            return result
        time.sleep(0.35)
    raise TimeoutError(label)


def ready(url):
    try:
        return SESSION.get(url, timeout=2).status_code == 200
    except requests.RequestException:
        return False


def read_log(name):
    return (WORK / f'{name}.log').read_text(encoding='utf-8', errors='replace')


def run(fixture, api_port, media_port):
    origin = fixture.origin
    api = f'http://127.0.0.1:{api_port}/api/'
    env = dict(os.environ,
        PYTHONPATH=os.pathsep.join((str(WORK), str(ROOT), str(ROOT / 'core/api'), str(ROOT / 'core/media_api/src'))),
        DJANGO_SETTINGS_MODULE=SETTINGS_NAME, PROCESS_MODULES='scout', BRIDGE_TRANSPORT='local',
        SCOUT_TASK_RUNNER='celery',
        SCOUT_AI_LIVE_WORK=str(WORK), SCOUT_AI_LIVE_DB=DB_NAME,
        SCOUT_TRUSTED_FETCH_ENDPOINTS=f'127.0.0.1:{fixture.server_port}',
        ERGO_SEARCH_ENABLED='false', ERGO_REALTIME='http_polling', ERGO_MEDIA='local', MEDIA_ACCESS_MODE='local',
        ERGO_LOGS_DIR=str(WORK / 'logs'),
        CELERY_BROKER_URL='sqla+sqlite:///' + (WORK / 'broker.sqlite3').as_posix(),
        CELERY_RESULT_BACKEND='db+sqlite:///' + (WORK / 'results.sqlite3').as_posix(),
        PYTHONUTF8='1', PYTHONUNBUFFERED='1',
    )
    (WORK / f'{SETTINGS_NAME}.py').write_text(
        'import os\nfrom pathlib import Path\n'
        'from src.config.patterns.development import *\n'
        'DATABASES = {"default": {**DATABASES["default"], "NAME": os.environ["SCOUT_AI_LIVE_DB"]}}\n'
        'MEDIA_ROOT = str(Path(os.environ["SCOUT_AI_LIVE_WORK"]) / "media")\n'
        'from modules.scout.api.services import snapshot_store\n'
        'snapshot_store.CACHE_DIR = Path(os.environ["SCOUT_AI_LIVE_WORK"]) / "cache"\n'
        'snapshot_store._ROOT = snapshot_store.CACHE_DIR / "scout" / "snapshots"\n'
        'CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}\n',
        encoding='utf-8',
    )
    (WORK / 'scout_retention_live_beat.py').write_text(
        'import django\nfrom src.config.celery import celery_app, ensure_django_celery_configured\n'
        'django.setup()\nensure_django_celery_configured()\n'
        'from modules.scout.api.celery_beat_config import ScoutBeatConfig\n'
        "celery_app.conf.beat_schedule = ScoutBeatConfig('scout').get_beat_schedule()\n",
        encoding='utf-8',
    )
    with (WORK / 'migrate.log').open('wb') as output:
        subprocess.run([sys.executable, '-m', 'src.manage', 'migrate', '--noinput'], cwd=ROOT, env=env,
                       stdout=output, stderr=subprocess.STDOUT, check=True, timeout=150,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    os.environ.update(env)
    sys.path[:0] = [str(WORK), str(ROOT), str(ROOT / 'core/api')]
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connection
    from modules.scout.api.models import Evidence, Run

    assert connection.vendor == 'postgresql' and connection.settings_dict['NAME'] == DB_NAME
    username, password = 'scout-retention-live', secrets.token_urlsafe(24)
    user = get_user_model().objects.create_superuser(username=username, password=password)

    start('django', env, sys.executable, '-m', 'src.manage', 'runserver', f'127.0.0.1:{api_port}', '--noreload')
    start('worker', env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'), '--module=scout',
          '--concurrency=1', '--pool=solo', f'--hostname=scout-retention-{SUFFIX}@local')
    wait_for('worker readiness', lambda: 'Connected to sqla+sqlite:' in read_log('worker'))
    wait_for('Django readiness', lambda: ready(api + 'system/ready/'))
    emit('Django, PostgreSQL and one Celery worker are ready.')

    def request(method, path, code=200, **kwargs):
        response = SESSION.request(method, api + path, timeout=25, **kwargs)
        assert response.status_code == code, f'{method} {path}: {response.status_code} {response.text[:450]}'
        payload = response.json()
        return payload.get('data', payload)

    def state(path, expected, seconds=55, **kwargs):
        def probe():
            data = request('GET', path, **kwargs)
            if data['status'] == expected:
                return data
            if data['status'] in ('failed', 'cancelled', 'completed', 'completed_with_errors'):
                raise AssertionError(f"Expected {expected}, got {data['status']}: {data.get('error', data.get('error_summary'))}")
        return wait_for(expected, probe, seconds=seconds)

    auth = request('POST', 'cms/adp/authorization/', json={'username': username, 'password': password, 'remember_me': False})
    SESSION.headers['Authorization'] = 'Bearer ' + auth['access']

    from datetime import timedelta
    from django.utils import timezone
    from modules.scout.api.models import RetentionCleanup, PageSnapshot, Task
    from modules.scout.api.services.snapshot_store import safe_snapshot_path
    from modules.scout.api.tasks import execute_retention_cleanup
    from src.config.celery import ensure_django_celery_configured
    ensure_django_celery_configured()
    assert 'Applying scout.0014_retention_cleanup... OK' in read_log('migrate')
    defaults = request('GET', 'scout/retention/policy/')
    assert defaults['automatic_enabled'] is False
    job = request('POST', 'scout/jobs/', 201, json=comparison_plan(origin))

    def collect():
        pending = request('POST', f"scout/jobs/{job['public_id']}/explore/", 202)
        path = f"scout/runs/{pending['public_id']}/"
        state(path, 'awaiting_confirmation')
        request('POST', path + 'approve/')
        request('POST', path + 'start/', 202)
        result = state(path, 'completed')
        Run.objects.filter(public_id=result['public_id']).update(finished_at=timezone.now()-timedelta(days=40))
        return result

    first = collect()
    fixture.add_product_and_change_price()
    second = collect()
    comparison_path = f"scout/runs/{second['public_id']}/compare/"
    params = {'base_run_public_id': first['public_id'], 'field': 'price'}
    before = request('GET', comparison_path, params=params)
    assert [first['record_count'], second['record_count']] == [3,4]
    price = next(row for row in before['changes'] if row['sku']=='K-01')
    assert len(price['before']['evidence']) == len(price['after']['evidence']) == 2
    emit('Two actual collections: 3 and 4 records, changed price and both Evidence sides verified.')

    active = request('POST', f"scout/jobs/{job['public_id']}/explore/", 202)
    active_path = f"scout/runs/{active['public_id']}/"
    state(active_path, 'awaiting_confirmation')
    Run.objects.filter(public_id=active['public_id']).update(finished_at=timezone.now()-timedelta(days=400))
    protected = request('POST', 'scout/retention/previews/', 201, json={
        'policy_version': 1, 'job_public_id': job['public_id'], 'scopes': ['html','results'],
    })
    assert protected['protected']['active_run'] >= 1
    active_files = list(PageSnapshot.objects.filter(run__public_id=active['public_id']))
    assert active_files and all(safe_snapshot_path(row.content_path).exists() for row in active_files)
    request('POST', active_path+'approve/')
    stop(PROCESSES.pop('worker'))
    request('POST', active_path+'start/', 202)
    request('POST', active_path+'pause/')
    paused = request('POST', 'scout/retention/previews/', 201, json={
        'policy_version': 1, 'job_public_id': job['public_id'], 'scopes': ['html'],
    })
    assert paused['protected']['active_run'] >= 1
    request('POST', active_path+'cancel/')
    start('worker', env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'),
          '--module=scout', '--concurrency=1', '--pool=solo', f'--hostname=scout-retention-{SUFFIX}@local')
    wait_for('worker readiness after pause test', lambda: 'Connected to sqla+sqlite:' in read_log('worker'))
    Run.objects.filter(public_id=active['public_id']).update(finished_at=timezone.now()-timedelta(days=40))
    emit('Awaiting-confirmation and paused collection protected, including shared HTML.')

    snapshots = list(PageSnapshot.objects.all())
    paths = {safe_snapshot_path(row.content_path) for row in snapshots}
    evidence_count = Evidence.objects.count()
    task_attempts = list(Task.objects.order_by('pk').values_list('public_id','attempt_count'))
    record_ids = list(Run.objects.get(public_id=second['public_id']).records.values_list('public_id', flat=True))
    preview = request('POST', 'scout/retention/previews/', 201, json={
        'policy_version': 1, 'job_public_id': job['public_id'], 'scopes': ['html'],
    })
    assert preview['executable'] and preview['totals']['html_files'] == len(paths)
    assert preview['totals']['file_bytes_reclaimable'] == sum(path.stat().st_size for path in paths)
    assert all(path.exists() for path in paths) and Evidence.objects.count() == evidence_count
    items = request('GET', f"scout/retention/previews/{preview['preview_public_id']}/items/", params={'limit':1})
    assert items['next_cursor'] and 'path' not in items['items'][0]
    emit('Dry preview verified: exact unique files/bytes, no changes and paginated public items.')

    # Fault belongs only to this isolated stand, not to production code.
    fault = WORK / 'crash-once'
    fault.write_text('armed', encoding='utf-8')
    settings_file = WORK / f'{SETTINGS_NAME}.py'
    settings_file.write_text(settings_file.read_text(encoding='utf-8') + '''
if os.environ.get('SCOUT_RETENTION_CRASH_WORKER') == '1':
    _original_unlink = Path.unlink
    def _crash_after_unlink(path, *args, **kwargs):
        value = _original_unlink(path, *args, **kwargs)
        flag = Path(os.environ['SCOUT_AI_LIVE_WORK']) / 'crash-once'
        if path.suffix == '.html' and 'snapshots' in path.parts and flag.exists():
            _original_unlink(flag)
            print('RETENTION_FAULT_AFTER_UNLINK', flush=True)
            os._exit(77)
        return value
    Path.unlink = _crash_after_unlink
''', encoding='utf-8')
    stop(PROCESSES.pop('worker'))
    crash_env = dict(env, SCOUT_RETENTION_CRASH_WORKER='1')
    start('worker-crash', crash_env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'),
          '--module=scout', '--concurrency=1', '--pool=solo', f'--hostname=scout-retention-crash-{SUFFIX}@local')
    wait_for('fault worker readiness', lambda: 'Connected to sqla+sqlite:' in read_log('worker-crash'))
    crash_worker = PROCESSES.pop('worker-crash')
    start('beat', env, sys.executable, '-m', 'celery', '-A', 'scout_retention_live_beat:celery_app', 'beat', '-l', 'INFO',
          '-S', 'celery.beat:PersistentScheduler', '-s', str(WORK / 'beat-schedule'))
    body = {'preview_public_id': preview['preview_public_id'], 'manifest_hash': preview['manifest_hash'],
            'idempotency_key': str(__import__('uuid').uuid4())}
    cleanup = request('POST', 'scout/retention/cleanups/', 202, json=body)
    cleanup_id = cleanup['cleanup_public_id']
    wait_for('worker crashed after unlink', lambda: crash_worker.poll() is not None)
    assert 'RETENTION_FAULT_AFTER_UNLINK' in read_log('worker-crash')
    assert PageSnapshot.objects.filter(html_availability='purging').exists()
    assert any(not path.exists() for path in paths)
    saved = RetentionCleanup.objects.get(public_id=cleanup_id)
    assert saved.status == 'running'
    emit('Worker process terminated after actual unlink; deletion intent survived in PostgreSQL.')
    start('worker', env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'),
          '--module=scout', '--concurrency=1', '--pool=solo', f'--hostname=scout-retention-restored-{SUFFIX}@local')
    wait_for('restored worker readiness', lambda: 'Connected to sqla+sqlite:' in read_log('worker'))
    restored = state(f'scout/retention/cleanups/{cleanup_id}/', 'completed')
    assert all(not path.exists() for path in paths)
    assert not PageSnapshot.objects.exclude(html_availability='expired').exists()
    assert Evidence.objects.count() == evidence_count
    assert list(Run.objects.get(public_id=second['public_id']).records.values_list('public_id', flat=True)) == record_ids
    after = request('GET', comparison_path, params=params)
    for response in (before, after):
        for change in response['changes']:
            for side in ('before','after'):
                if change[side]:
                    for evidence in change[side]['evidence']:
                        evidence.pop('html_availability')
    assert before == after
    replay = request('POST', 'scout/retention/cleanups/', 202, json=body)
    assert replay['cleanup_public_id'] == cleanup_id
    delivered = execute_retention_cleanup.apply_async(args=[cleanup_id],queue='scout').get(timeout=40)
    assert delivered == {'changed': False}
    assert list(Task.objects.order_by('pk').values_list('public_id','attempt_count')) == task_attempts
    assert RetentionCleanup.objects.count() == 1
    wait_for('real Beat cleanup sweep', lambda: 'Sending due task scout-retention' in read_log('beat'))
    emit('Real Beat recovered the same cleanup. Comparison, Evidence and task attempts unchanged; no duplicates.')
    result = {'database_vendor':connection.vendor, 'isolated_database':DB_NAME,
              'migration':'0014_retention_cleanup', 'records':[3,4],
              'preview':preview['totals'], 'active_and_paused_protected':True,
              'fault':'os._exit(77) after unlink before PostgreSQL completion',
              'beat_recovered':True, 'cleanup':restored, 'evidence_preserved':evidence_count,
              'comparison_preserved':True, 'duplicate_delivery':delivered, 'automatic_enabled':False}
    # Проверка рабочего потолка: 200 страниц, без изменения лимита в коде.
    from modules.scout.api.tests.fixtures.spec001_catalog import set_product
    fixture.links = []
    for number in range(1,200):
        path = f'/products/scale-{number}'
        set_product(fixture,path,f'SCALE-{number}',f'{1000+number},00')
        fixture.links.append(path)
    fixture.update_links()
    scale_plan = comparison_plan(origin)
    scale_plan['crawl'].update(max_pages=200, max_seconds=300, preview_urls=[origin+'/products/scale-1'])
    scale_job = request('POST','scout/jobs/',201,json=scale_plan)
    pending = request('POST',f"scout/jobs/{scale_job['public_id']}/explore/",202)
    scale_path = f"scout/runs/{pending['public_id']}/"
    state(scale_path,'awaiting_confirmation')
    request('POST',scale_path+'approve/')
    started = time.monotonic()
    request('POST',scale_path+'start/',202)
    collected = state(scale_path,'completed',seconds=240)
    collection_seconds = time.monotonic()-started
    assert collected['snapshot_count']==200 and collected['record_count']==199
    scale_run = Run.objects.get(public_id=pending['public_id'])
    scale_evidence = Evidence.objects.filter(record__run=scale_run).count()
    assert scale_evidence==597
    Run.objects.filter(pk=scale_run.pk).update(finished_at=timezone.now()-timedelta(days=40))
    scale_preview = request('POST','scout/retention/previews/',201,json={
        'policy_version':1, 'job_public_id':scale_job['public_id'], 'scopes':['html'],
    })
    assert scale_preview['totals']['html_files']==200
    scale_cleanup = request('POST','scout/retention/cleanups/',202,json={
        'preview_public_id':scale_preview['preview_public_id'], 'manifest_hash':scale_preview['manifest_hash'],
        'idempotency_key':str(__import__('uuid').uuid4()),
    })
    cleanup_started = time.monotonic()
    scale_done = state(f"scout/retention/cleanups/{scale_cleanup['cleanup_public_id']}/",'completed',seconds=180)
    assert scale_done['deleted']=={'html':200}
    assert scale_run.records.count()==199 and Evidence.objects.filter(record__run=scale_run).count()==597
    result['working_limit_check'] = {'pages':200,'records':199,'evidence':597,
        'collection_seconds':round(collection_seconds,2),'html_cleanup_seconds':round(time.monotonic()-cleanup_started,2),
        'deleted_bytes':scale_done['deleted_bytes'],'preserved':True}
    emit('Working 200-page limit checked: 199 records and 597 Evidence preserved after HTML cleanup.')
    (WORK/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    emit(json.dumps(result,ensure_ascii=False))


emit(f'Artifacts: {WORK}')
database_created = False
fixture = ComparisonCatalog()
Thread(target=fixture.serve_forever, daemon=True).start()
try:
    change_database(create=True)
    database_created = True
    run(fixture, *free_ports())
finally:
    for process in reversed(ALL_PROCESSES):
        stop(process)
    fixture.shutdown()
    fixture.server_close()
    if SETTINGS_NAME in sys.modules:
        from django.db import connections
        connections.close_all()
    if database_created:
        change_database(create=False)
        emit('Temporary PostgreSQL database dropped.')
