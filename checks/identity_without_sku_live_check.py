"""Проверка явного ключа по полю и URL на отдельной PostgreSQL и живых Django/Celery."""

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
WORK = ROOT / 'virtual_env/cache/tmp' / f'scout-no-sku-live-{SUFFIX}'
WORK.mkdir()
DB_NAME = f'scout_no_sku_{SUFFIX}'
SETTINGS_NAME = 'scout_no_sku_live_settings'
sys.path.insert(0, str(ROOT))
from modules.scout.api.tests.fixtures.ext002_catalog import ComparisonCatalog

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
    (WORK / 'scout_no_sku_live_beat.py').write_text(
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
    username, password = 'scout-no-sku-live', secrets.token_urlsafe(24)
    user = get_user_model().objects.create_superuser(username=username, password=password)

    start('django', env, sys.executable, '-m', 'src.manage', 'runserver', f'127.0.0.1:{api_port}', '--noreload')
    start('worker', env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'), '--module=scout',
          '--concurrency=1', '--pool=solo', f'--hostname=scout-no-sku-{SUFFIX}@local')
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

    from modules.scout.api.tests.fixtures.spec001_catalog import identity_plan
    from modules.scout.api.models import ExportArtifact
    from modules.scout.api.tasks import execute_scout_task
    from src.config.celery import ensure_django_celery_configured
    ensure_django_celery_configured()
    def collect(job):
        pending=request('POST',f"scout/jobs/{job['public_id']}/explore/",202)
        path=f"scout/runs/{pending['public_id']}/"
        state(path,'awaiting_confirmation')
        preview=request('GET',path,params={'value_format':'typed_v1'})['preview']
        request('POST',path+'approve/')
        request('POST',path+'start/',202)
        state(path,'completed')
        rows=request('GET',path+'records/',params={'value_format':'typed_v1'})['records']
        return Run.objects.get(public_id=pending['public_id']),rows,preview,path

    for path,body in list(fixture.pages.items()):
        fixture.pages[path]=body.replace('class="sku"','class="external-id"')
    plan=identity_plan(origin)
    plan['fields'][0].update(name='external_id',selector='.external-id')
    plan['identity']={'kind':'field','namespace':'external_catalog','field':'external_id'}
    job=request('POST','scout/jobs/',201,json=plan)
    base,old,preview,base_path=collect(job)
    assert len(old)==len(preview)==3
    for path in ('/products/k-01','/sale/k-01'):
        fixture.pages[path]=fixture.pages[path].replace('1 250,00','1 350,00')
    target,new,preview,target_path=collect(job)
    comparison=request('GET',target_path+'compare/',params={'base_run_public_id':str(base.public_id),'field':'price'})
    assert comparison['counts']['changed']==1
    change=comparison['changes'][0]
    assert change['key']=={'kind':'field','value':'K-01'}
    assert len(change['before']['evidence'])==len(change['after']['evidence'])==2
    assert comparison['base']['unkeyed_records']==comparison['target']['unkeyed_records']==1
    count=(target.records.count(),Evidence.objects.filter(record__run=target).count())
    for task in target.tasks.all():
        assert execute_scout_task.apply_async(args=[str(task.public_id),task.fencing_token],queue='scout').get(timeout=35)=={'changed':False}
    assert count==(target.records.count(),Evidence.objects.filter(record__run=target).count())
    emit('Text field identity: grouped aliases, changed price with two Evidence per side, missing key separate, no duplicates.')

    base_handler=fixture.RequestHandlerClass
    class RedirectHandler(base_handler):
        def do_GET(handler):
            if handler.path=='/identity-alias':
                handler.send_response(302)
                handler.send_header('Location','/products/k-01')
                handler.end_headers()
                return
            return super().do_GET()
    fixture.RequestHandlerClass=RedirectHandler
    plan=identity_plan(origin)
    plan['seed_urls'].append(origin+'/identity-alias')
    plan['fields']=plan['fields'][1:]
    plan['identity']={'kind':'url','namespace':'url_catalog'}
    url_job=request('POST','scout/jobs/',201,json=plan)
    first,old,preview,first_path=collect(url_job)
    assert len(old)==len(preview)==4
    fixture.pages['/products/k-01']=fixture.pages['/products/k-01'].replace('1 350,00','1 450,00')
    second,new,preview,second_path=collect(url_job)
    assert {row['identity']['entity_key'] for row in old}=={row['identity']['entity_key'] for row in new}
    comparison=request('GET',second_path+'compare/',params={'base_run_public_id':str(first.public_id),'field':'price'})
    assert comparison['counts']['changed']==1 and comparison['base']['unkeyed_records']==0
    change=comparison['changes'][0]
    assert change['key']=={'kind':'url','value':origin+'/products/k-01'}
    assert len(change['before']['evidence'])==len(change['after']['evidence'])==2
    assert len({row['identity']['key_value'] for row in new})==4
    exported=request('POST',second_path+'export/',json={'kind':'json','value_format':'typed_v1'})
    from src.core.utils.media_client import get_media_client
    artifact=ExportArtifact.objects.filter(run=second).latest('pk')
    assert json.loads(get_media_client().read_bytes(artifact.storage_path))==new
    emit('URL identity: redirects merged, identical names at distinct URLs separate, stable keys and JSON with Evidence verified.')
    report={'database_vendor':connection.vendor,'field_records':3,'field_unkeyed':1,
            'field_price_change':['1250.00','1350.00'],'field_price_evidence_per_side':[2,2],
            'url_records':4,'url_price_change':['1350.00','1450.00'],'url_price_evidence_per_side':[2,2],
            'url_alias_merged':True,'same_names_not_merged':True,'stable_keys':True,
            'duplicate_delivery_ignored':True,'typed_json_verified':True}
    (WORK/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    emit(json.dumps(report,ensure_ascii=False))


emit(f'Artifacts: {WORK}')
database_created=False
fixture=ComparisonCatalog()
Thread(target=fixture.serve_forever,daemon=True).start()
try:
    change_database(create=True)
    database_created=True
    run(fixture,*free_ports())
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
