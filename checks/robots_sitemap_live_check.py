"""Изолированная проверка поиска sitemap через robots.txt на Django, Celery, Beat и PostgreSQL."""

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
WORK = ROOT / 'virtual_env/cache/tmp' / f'scout-robots-sitemap-live-{SUFFIX}'
WORK.mkdir()
DB_NAME = f'scout_robots_sitemap_{SUFFIX}'
SETTINGS_NAME = 'scout_robots_sitemap_live_settings'
sys.path.insert(0, str(ROOT))
from modules.scout.api.tests.fixtures.robots_catalog import RobotsCatalog, robots_plan

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
    (WORK / 'scout_robots_sitemap_live_beat.py').write_text(
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
    username, password = 'scout-robots-sitemap-live', secrets.token_urlsafe(24)
    user = get_user_model().objects.create_superuser(username=username, password=password)

    start('django', env, sys.executable, '-m', 'src.manage', 'runserver', f'127.0.0.1:{api_port}', '--noreload')
    start('worker', env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'), '--module=scout',
          '--concurrency=1', '--pool=solo', f'--hostname=scout-robots-sitemap-{SUFFIX}@local')
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

    from modules.scout.api.models import Task
    from modules.scout.api.tasks import execute_scout_task
    from src.config.celery import ensure_django_celery_configured
    ensure_django_celery_configured()
    cases=[]

    def exercise(name, expected='completed', error=None, **crawl):
        before_robots=fixture.hits['/robots.txt']
        plan=robots_plan(origin)
        plan['crawl'].update(crawl)
        job=request('POST','scout/jobs/',201,json=plan)
        if crawl.get('max_pages')==1000:
            assert job['revision']['crawl']['max_pages']==200
        pending=request('POST',f"scout/jobs/{job['public_id']}/explore/",202)
        path=f"scout/runs/{pending['public_id']}/"
        state(path,'awaiting_confirmation')
        assert fixture.hits['/robots.txt']==before_robots
        request('POST',path+'start/',409)
        request('POST',path+'approve/')
        started=time.monotonic()
        request('POST',path+'start/',202)
        finished=state(path,expected)
        run=Run.objects.get(public_id=pending['public_id'])
        if error:
            assert run.tasks.get(status='failed').error_code==error
            assert not run.crawl_urls.exists() and not run.records.exists()
        else:
            assert finished['sitemap']['ready'] and finished['sitemap']['robots_processed']
        cases.append({'case':name,'status':finished['status'],'error':error,
                      'records':run.records.count(),'robots_requests':fixture.hits['/robots.txt']-before_robots,
                      'seconds':round(time.monotonic()-started,2)})
        emit(json.dumps(cases[-1],ensure_ascii=False))
        return run,finished

    run,finished=exercise('several_maps_index_gzip',max_pages=1000)
    assert run.records.count()==3 and Evidence.objects.filter(record__run=run).count()==11
    assert finished['sitemap']['maps_discovered']==finished['sitemap']['maps_processed']==4
    assert run.tasks.filter(kind='sitemap').count()==5
    assert fixture.hits['/robots.txt']==1
    for path in ('/index.xml','/one.xml.gz','/nested.xml','/two.xml'):
        assert fixture.hits[path]==1,(path,fixture.hits[path])
    before=(run.records.count(),Evidence.objects.filter(record__run=run).count(),run.tasks.count())
    for task in run.tasks.filter(kind='sitemap'):
        assert execute_scout_task.apply_async(args=[str(task.public_id),task.fencing_token],queue='scout').get(timeout=35)=={'changed':False}
    assert before==(run.records.count(),Evidence.objects.filter(record__run=run).count(),run.tasks.count())
    run,finished=exercise('shared_page_limit_and_filter',max_pages=2,visit=[{'kind':'prefix','pattern':'/products/'}])
    assert run.crawl_urls.filter(state='done').count()==2 and finished['stop_reason']=='max_pages'
    assert not run.snapshots.filter(source_url__contains='/sale/').exists()

    good_body=fixture.robots_body
    fixture.robots_status=[503,200]
    run,_=exercise('temporary_503_then_success')
    assert cases[-1]['robots_requests']==2
    assert run.tasks.get(idempotency_key='sitemap').attempt_count==2
    fixture.robots_status=503
    run,_=exercise('persistent_503','failed','http_503')
    assert run.tasks.get(idempotency_key='sitemap').attempt_count==3
    fixture.robots_status=404
    exercise('missing_robots','failed','http_404')
    fixture.robots_status=200
    for name,body,error in (
        ('no_sitemap',b'User-agent: *\nDisallow: /','robots_no_sitemap'),
        ('relative_url',b'Sitemap: /map.xml','robots_invalid'),
        ('html_instead_of_robots',b'<html>Login</html>','robots_invalid'),
        ('bad_child_xml',(f'Sitemap: {origin}/one.xml.gz\nSitemap: {origin}/broken.xml').encode(),'sitemap_invalid'),
        ('foreign_map',b'Sitemap: https://example.org/map.xml','sitemap_scope'),
        ('private_network',b'Sitemap: http://127.0.0.1/map.xml','url_blocked'),
    ):
        fixture.robots_body=body
        exercise(name,'failed',error)
    fixture.robots_body=good_body
    fixture.robots_status=302
    fixture.robots_redirect='http://127.0.0.1:1/robots.txt'
    exercise('private_redirect','failed','url_blocked')
    fixture.robots_status=200
    fixture.robots_redirect=''
    fixture.robots_body=b'#'+b'x'*(512*1024)
    exercise('oversize_robots','failed','too_large')

    report={'database_vendor':connection.vendor,'cases':cases,'maps':4,'records':3,'evidence':11,
            'duplicates':False,'approval_required':True,'failed_before_frontier':True,'max_pages_unchanged':200}
    (WORK/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    emit(json.dumps(report,ensure_ascii=False))


emit(f'Artifacts: {WORK}')
database_created=False
fixture=RobotsCatalog()
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
