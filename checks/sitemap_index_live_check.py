"""Изолированная проверка индексов sitemap на Django, Celery, Beat и PostgreSQL."""

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
WORK = ROOT / 'virtual_env/cache/tmp' / f'scout-sitemap-index-live-{SUFFIX}'
WORK.mkdir()
DB_NAME = f'scout_sitemap_index_{SUFFIX}'
SETTINGS_NAME = 'scout_sitemap_index_live_settings'
sys.path.insert(0, str(ROOT))
from modules.scout.api.tests.fixtures.sitemap_index_catalog import SitemapIndexCatalog, index_plan

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
    (WORK / 'scout_sitemap_index_live_beat.py').write_text(
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
    username, password = 'scout-sitemap-index-live', secrets.token_urlsafe(24)
    user = get_user_model().objects.create_superuser(username=username, password=password)

    start('django', env, sys.executable, '-m', 'src.manage', 'runserver', f'127.0.0.1:{api_port}', '--noreload')
    start('worker', env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'), '--module=scout',
          '--concurrency=1', '--pool=solo', f'--hostname=scout-sitemap-index-{SUFFIX}@local')
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
    from modules.scout.api.models import Task,Attempt
    from modules.scout.api.tasks import execute_scout_task
    from src.config.celery import ensure_django_celery_configured
    ensure_django_celery_configured()
    job=request('POST','scout/jobs/',201,json=index_plan(origin))
    pending=request('POST',f"scout/jobs/{job['public_id']}/explore/",202)
    path=f"scout/runs/{pending['public_id']}/"
    state(path,'awaiting_confirmation')
    assert fixture.hits['/index.xml']==0
    request('POST',path+'start/',409)
    request('POST',path+'approve/')
    fixture.block_path='/one.xml.gz'
    request('POST',path+'start/',202)
    wait_for('child map HTTP started',fixture.entered.is_set)
    root_task=Task.objects.get(run__public_id=pending['public_id'],idempotency_key='sitemap')
    assert root_task.status=='succeeded'
    scan=root_task.payload['sitemap_scan']
    assert scan['processed']==1 and not scan['sealed']
    run=Run.objects.get(public_id=pending['public_id'])
    assert not run.crawl_urls.exists() and not run.records.exists()
    leased=run.tasks.get(kind='sitemap',status='leased')
    stale_id,stale_token=str(leased.public_id),leased.fencing_token
    stop(PROCESSES.pop('worker'))
    fixture.release.set()
    fixture.block_path=None
    # Только срок аренды проверочного запуска сдвигается; сам HTTP и падение процесса настоящие.
    Task.objects.filter(pk=leased.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
    start('worker',env,sys.executable,str(ROOT/'core/api/scripts/start_celery_worker.py'),'--module=scout',
          '--concurrency=1','--pool=solo',f'--hostname=scout-sitemap-index-restored-{SUFFIX}@local')
    wait_for('restored worker',lambda:'Connected to sqla+sqlite:' in read_log('worker'))
    start('beat',env,sys.executable,'-m','celery','-A','scout_sitemap_index_live_beat:celery_app','beat','-l','INFO',
          '-S','celery.beat:PersistentScheduler','-s',str(WORK/'beat-schedule'))
    completed=state(path,'completed')
    assert completed['record_count']==3 and completed['sitemap']['ready']
    assert completed['sitemap']['maps_discovered']==completed['sitemap']['maps_processed']==4
    assert fixture.hits['/index.xml']==1 and fixture.hits['/one.xml.gz']==2
    assert run.tasks.filter(kind='sitemap').count()==4
    assert run.records.count()==3 and Evidence.objects.filter(record__run=run).count()==11
    before=(run.records.count(),Evidence.objects.filter(record__run=run).count(),run.tasks.count())
    assert execute_scout_task.apply_async(args=[stale_id,stale_token],queue='scout').get(timeout=35)=={'changed':False}
    for task in run.tasks.filter(kind='sitemap'):
        assert execute_scout_task.apply_async(args=[str(task.public_id),task.fencing_token],queue='scout').get(timeout=35)=={'changed':False}
    assert before==(run.records.count(),Evidence.objects.filter(record__run=run).count(),run.tasks.count())
    wait_for('Beat recovered expired lease',lambda:'Sending due task scout-dispatch-pending' in read_log('beat'))
    assert Attempt.objects.filter(task=leased,error_code='lease_lost').count()==1
    emit('Index + gzip + nested map recovered after worker crash: 3 records, 11 Evidence, no duplicate tasks/records.')

    bad_job=request('POST','scout/jobs/',201,json=index_plan(origin,'/broken-index.xml'))
    pending=request('POST',f"scout/jobs/{bad_job['public_id']}/explore/",202)
    bad_path=f"scout/runs/{pending['public_id']}/"
    state(bad_path,'awaiting_confirmation')
    request('POST',bad_path+'approve/')
    request('POST',bad_path+'start/',202)
    failed=state(bad_path,'failed')
    bad=Run.objects.get(public_id=pending['public_id'])
    assert failed['record_count']==0 and not bad.crawl_urls.exists()
    assert bad.tasks.get(status='failed').error_code=='sitemap_invalid'
    report={'database_vendor':connection.vendor,'records':3,'evidence':11,'maps':4,
            'root_requests':fixture.hits['/index.xml'],'retried_child_requests':fixture.hits['/one.xml.gz'],
            'worker_crashed_during_child_http':True,'lease_deadline_shortened_for_test':True,
            'beat_recovered':True,'stale_attempt_ignored':True,'duplicates':False,
            'bad_child_failed_before_frontier':True,'max_pages_unchanged':200}
    (WORK/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    emit(json.dumps(report,ensure_ascii=False))


emit(f'Artifacts: {WORK}')
database_created=False
fixture=SitemapIndexCatalog()
Thread(target=fixture.serve_forever,daemon=True).start()
try:
    change_database(create=True)
    database_created=True
    run(fixture,*free_ports())
finally:
    fixture.release.set()
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
