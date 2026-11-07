"""Живая проверка одного черновика по нескольким типам через локальную Ollama."""

import json
import os
import re
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
sys.path.insert(0,str(ROOT))
SUFFIX = secrets.token_hex(4)
WORK = ROOT / 'virtual_env/cache/tmp' / f'scout-ai-pages-live-{SUFFIX}'
WORK.mkdir()
DB_NAME = f'scout_ai_pages_{SUFFIX}'
MODEL = 'qwen3.5:4b'
PROVIDER = Path(os.environ.get('SCOUT_AI_PROVIDER_ROOT', str(ROOT / 'modules/ollama_framework')))
SETTINGS_NAME = 'scout_ai_pages_live_settings'
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


def model_posts():
    return re.findall(r'\bPOST\s+"(/api/(?:chat|generate|embed|embeddings))"', read_log('ollama'))


def run(fixture, api_port, ollama_port):
    origin = fixture.origin
    api = f'http://127.0.0.1:{api_port}/api/'
    ollama = f'http://127.0.0.1:{ollama_port}'
    env = dict(os.environ,
        PYTHONPATH=os.pathsep.join((str(WORK), str(ROOT), str(ROOT / 'core/api'))),
        DJANGO_SETTINGS_MODULE=SETTINGS_NAME, PROCESS_MODULES='scout', BRIDGE_TRANSPORT='local',
        SCOUT_AI_ENABLED='true', SCOUT_AI_TIMEOUT_SECONDS='60', SCOUT_TASK_RUNNER='celery',
        SCOUT_AI_LIVE_WORK=str(WORK), SCOUT_AI_LIVE_DB=DB_NAME, SCOUT_AI_LIVE_PROVIDER=str(PROVIDER),
        SCOUT_TRUSTED_FETCH_ENDPOINTS=f'127.0.0.1:{fixture.server_port}',
        ERGO_SEARCH_ENABLED='false', ERGO_REALTIME='http_polling', ERGO_MEDIA='local', MEDIA_ACCESS_MODE='local',
        ERGO_LOGS_DIR=str(WORK / 'logs'),
        CELERY_BROKER_URL='sqla+sqlite:///' + (WORK / 'broker.sqlite3').as_posix(),
        CELERY_RESULT_BACKEND='db+sqlite:///' + (WORK / 'results.sqlite3').as_posix(),
        OLLAMA_BASE_URL_OVERRIDE=ollama, OLLAMA_DEFAULT_MODEL=MODEL,
        PYTHONUTF8='1', PYTHONUNBUFFERED='1',
    )
    (WORK / f'{SETTINGS_NAME}.py').write_text(
        'import os\nfrom pathlib import Path\n'
        'from src.config.patterns.development import *\n'
        'import modules.ollama_framework\n'
        'modules.ollama_framework.__path__ = [os.environ["SCOUT_AI_LIVE_PROVIDER"]]\n'
        'INSTALLED_APPS = [*INSTALLED_APPS, "modules.ollama_framework.api.apps.OllamaFrameworkConfig"]\n'
        'DATABASES = {"default": {**DATABASES["default"], "NAME": os.environ["SCOUT_AI_LIVE_DB"]}}\n'
        'from modules.scout.api.services import snapshot_store\n'
        'snapshot_store.CACHE_DIR = Path(os.environ["SCOUT_AI_LIVE_WORK"]) / "cache"\n'
        'snapshot_store._ROOT = snapshot_store.CACHE_DIR / "scout" / "snapshots"\n'
        'CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}\n',
        encoding='utf-8',
    )
    settings_path=WORK/f'{SETTINGS_NAME}.py'
    settings_path.write_text(settings_path.read_text(encoding='utf-8')+'''
from modules.scout.api.services import plan_suggestions as _suggestions
_original_generate = _suggestions._generate
def _capture_public_fixture_reply(*args, **kwargs):
    value = _original_generate(*args, **kwargs)
    (Path(os.environ['SCOUT_AI_LIVE_WORK']) / 'model-reply.txt').write_text(str(value), encoding='utf-8')
    return value
_suggestions._generate = _capture_public_fixture_reply
''',encoding='utf-8')
    (WORK / 'scout_ai_pages_live_beat.py').write_text(
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
    username, password = 'scout-ai-pages-live', secrets.token_urlsafe(24)
    # Bootstrap живёт вне каталога модулей: AppConfig провайдера загружает Django, а Scout обращается к нему через мост.
    provision=WORK/'provision.py'
    provision.write_text('''import os, django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection
from src.core.integrations import bridge
assert connection.vendor == 'postgresql' and connection.settings_dict['NAME'] == os.environ['SCOUT_AI_LIVE_DB']
assert bridge.has('ollama_framework.chat')
get_user_model().objects.create_superuser(username=os.environ['SCOUT_CHECK_USERNAME'],password=os.environ['SCOUT_CHECK_PASSWORD'])
print('PROVISIONED_POSTGRESQL')
''',encoding='utf-8')
    with (WORK/'provision.log').open('wb') as output:
        subprocess.run([sys.executable,str(provision)],cwd=ROOT,env=dict(env,SCOUT_CHECK_USERNAME=username,
            SCOUT_CHECK_PASSWORD=password),stdout=output,stderr=subprocess.STDOUT,check=True,timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW)

    start('ollama', dict(env, OLLAMA_HOST=f'127.0.0.1:{ollama_port}', OLLAMA_NO_CLOUD='1'),
          os.environ.get('SCOUT_OLLAMA_EXE', str(Path(os.environ['LOCALAPPDATA']) / 'Programs/Ollama/ollama.exe')), 'serve')
    start('django', env, sys.executable, '-m', 'src.manage', 'runserver', f'127.0.0.1:{api_port}', '--noreload')
    start('worker', env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'), '--module=scout',
          '--concurrency=1', '--pool=solo', f'--hostname=scout-ai-pages-{SUFFIX}@local')
    start('beat', env, sys.executable, '-m', 'celery', '-A', 'scout_ai_pages_live_beat:celery_app', 'beat', '-l', 'INFO',
          '-S', 'celery.beat:PersistentScheduler', '-s', str(WORK / 'beat-schedule'))
    wait_for('Ollama readiness', lambda: ready(ollama + '/api/tags'))
    warmed = SESSION.post(ollama + '/api/generate', json={'model': MODEL, 'stream': False}, timeout=65)
    warmed.raise_for_status()
    assert not warmed.json().get('response')
    wait_for('worker readiness', lambda: 'Connected to sqla+sqlite:' in read_log('worker'))
    wait_for('Django readiness', lambda: ready(api + 'system/ready/'))
    emit('Django, PostgreSQL, Celery and warmed local Ollama are ready.')

    def request(method, path, code=200, **kwargs):
        response = SESSION.request(method, api + path, timeout=75, **kwargs)
        assert response.status_code == code, f'{method} {path}: {response.status_code} {response.text[:450]}'
        payload = response.json()
        return payload.get('data', payload)

    def state(path, expected, **kwargs):
        def probe():
            data = request('GET', path, **kwargs)
            if data['status'] == expected:
                return data
            if data['status'] in ('failed', 'cancelled', 'completed', 'completed_with_errors'):
                raise AssertionError(f"Expected {expected}, got {data['status']}: {data.get('error', data.get('error_summary'))}")
        return wait_for(expected, probe)

    auth = request('POST', 'cms/adp/authorization/', json={'username': username, 'password': password, 'remember_me': False})
    SESSION.headers['Authorization'] = 'Bearer ' + auth['access']

    snapshots=[]
    for path,type_id,action,patterns in (
        ('/catalog/','catalog','discover',['/catalog/','/bridge/']),
        ('/products/a','product','extract',['/products/']),
        ('/archive/c','archive','extract',['/archive/']),
    ):
        created=request('POST','scout/visual-snapshots/',202,json={'url':origin+path})
        state(f"scout/visual-snapshots/{created['public_id']}/",'ready')
        snapshots.append({'snapshot_public_id':created['public_id'],'id':type_id,'action':action,
                          'match':[{'kind':'prefix','pattern':value} for value in patterns]})
    wait_for('warm-up counted',lambda:model_posts()==['/api/generate'])
    before_jobs=len(request('GET','scout/jobs/')['jobs'])
    started=time.monotonic()
    proposed=request('POST','scout/plan-suggestions/',json={
        'goal':'Собери ровно два поля title (название) и price (цена в рублях) со страниц product и archive. '
               'Каталог catalog только для ссылок. Одна запись на страницу: record=null. '
               'Цена содержит запятую как разделитель. Другие поля не добавляй.',
        'pages':snapshots,
    })
    suggestion_seconds=round(time.monotonic()-started,2)
    draft=proposed['draft']
    assert {field['name'] for field in draft['fields']}=={'title','price'}
    assert draft['record'] is None and len(draft['crawl']['page_types'])==3
    assert len(request('GET','scout/jobs/')['jobs'])==before_jobs
    assert model_posts()==['/api/generate','/api/chat']
    # Как и обычный пользователь, сверяем предложенное преобразование с числами до сохранения плана.
    price_field=next(field for field in draft['fields'] if field['name']=='price')
    expected_conversion={'type':'money','currency':'RUB','decimal_separator':','}
    conversion_corrected=price_field.get('conversion')!=expected_conversion
    price_field['conversion']=expected_conversion
    (WORK/'draft.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding='utf-8')
    job=request('POST','scout/jobs/',201,json=draft)
    pending=request('POST',f"scout/jobs/{job['public_id']}/explore/",202)
    path=f"scout/runs/{pending['public_id']}/"
    ready_run=state(path,'awaiting_confirmation',params={'value_format':'typed_v1'})
    assert ready_run['page_type_preview']['can_approve']
    assert len(ready_run['preview'])==2
    request('POST',path+'start/',409)
    request('POST',path+'approve/')
    request('POST',path+'start/',202)
    completed=state(path,'completed')
    rows=request('GET',path+'records/',params={'value_format':'typed_v1'})['records']
    assert len(rows)==3 and all(len(row['evidence'])==2 for row in rows)
    assert all(row['values']['price']['typed']['status']=='ok' for row in rows)
    assert any(row['values']['title']['normalized']=='Кружка' for row in rows)
    wait_for('Beat after completion',lambda:'Sending due task scout-dispatch-pending' in read_log('beat'),seconds=60)
    assert model_posts()==['/api/generate','/api/chat']
    report={'database_vendor':'postgresql','model':MODEL,'model_warmed':True,
            'samples':3,'types':['catalog','product','archive'],'suggestion_seconds':suggestion_seconds,
            'scout_model_calls':1,'calls_after_proposal':0,'preview_rows':2,
            'money_conversion_corrected_before_preview':conversion_corrected,
            'collection_records':3,'evidence':6,'typed_prices_ok':True,
            'approval_required':True,'beat_checked':True,'model_posts':model_posts()}
    (WORK/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    emit(json.dumps(report,ensure_ascii=False))


emit(f'Artifacts: {WORK}')
assert (PROVIDER/'api/apps.py').is_file(), 'Set SCOUT_AI_PROVIDER_ROOT to the optional ollama_framework checkout'
database_created=False
from modules.scout.api.tests.fixtures.spec002_catalog import CatalogServer
fixture=CatalogServer()
fixture.pages['/archive/c']='<h2>Кружка</h2><strong class="cost">110,00 ₽</strong>'
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
    if database_created:
        change_database(create=False)
        emit('Temporary PostgreSQL database dropped.')
