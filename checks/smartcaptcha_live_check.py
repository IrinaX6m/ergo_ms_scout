"""Изолированные Django/Celery/Beat/PostgreSQL и собственная HTTPS-форма.

--checko дополнительно читает одну реальную публичную карточку, без серий запросов.
--text-task включает собственную текстовую картинку и настоящую локальную Ollama.
Модель задаётся SCOUT_CAPTCHA_ML_MODEL, по умолчанию qwen3.5:4b.
Никаких внешних решателей, токенов Яндекса или собственных обученных весов этот стенд не подменяет.
"""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import psutil
import psycopg2
from psycopg2 import sql
import requests
import yaml
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[3]
SUFFIX = secrets.token_hex(4)
WORK = ROOT / 'virtual_env/cache/tmp' / ('scout-smartcaptcha-' + SUFFIX)
WORK.mkdir(parents=True)
DB_NAME = 'scout_captcha_' + SUFFIX
SETTINGS = 'scout_captcha_settings'
PROCESSES = []
SESSION = requests.Session()
SESSION.trust_env = False
sys.path.insert(0, str(ROOT))
from modules.scout.api.tests.fixtures.smartcaptcha_site import COOKIE, SmartCaptchaSite


def emit(value):
    print(json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value, flush=True)


def database(create):
    assert DB_NAME.startswith('scout_captcha_') and DB_NAME != 'ergo_ms'
    db = yaml.safe_load((ROOT / 'databases.yaml').read_text(encoding='utf-8-sig'))['databases']['default']
    assert db['engine'] == 'postgresql' and db['host'] in ('127.0.0.1', 'localhost', '::1')
    with closing(psycopg2.connect(dbname=db['name'], host=db['host'], port=db['port'],
                                  user=db['user'], password=db['password'])) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}' if create else 'DROP DATABASE {}').format(sql.Identifier(DB_NAME)))


def start(name, env, *args):
    with (WORK / (name + '.log')).open('wb') as log:
        process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    PROCESSES.append(process)
    return process


def stop(process):
    if process.poll() is not None:
        return
    parent = psutil.Process(process.pid)
    children = parent.children(recursive=True)
    for child in reversed(children):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    process.terminate()
    process.wait(timeout=10)
    psutil.wait_procs(children, timeout=5)


def wait(label, predicate, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.3)
    raise TimeoutError(label)


def run(site):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1', PROCESS_MODULES='scout',
               PYTHONPATH=os.pathsep.join((str(WORK), str(ROOT), str(ROOT / 'core/api'))),
               DJANGO_SETTINGS_MODULE=SETTINGS, BRIDGE_TRANSPORT='local', SCOUT_TASK_RUNNER='celery',
               SCOUT_CAPTCHA_WORK=str(WORK), SCOUT_CAPTCHA_DB=DB_NAME,
               SCOUT_CAPTCHA_FIXTURE_CERT=str(site.cert_file), SCOUT_CAPTCHA_FIXTURE_SPKI=site.spki,
               SCOUT_TRUSTED_FETCH_ENDPOINTS=f'127.0.0.1:{site.port}', SCOUT_BROWSER_ENABLED='true',
               SCOUT_BROWSER_ORIGINS=json.dumps([site.origin, 'https://checko.ru']), SCOUT_BROWSER_CHANNEL='chrome',
               SCOUT_BROWSER_KEYS=json.dumps({'probe': Fernet.generate_key().decode()}), SCOUT_BROWSER_ACTIVE_KEY='probe',
               ERGO_REALTIME='http_polling', ERGO_MEDIA='local', MEDIA_ACCESS_MODE='local',
               ERGO_SEARCH_ENABLED='false', ERGO_LOGS_DIR=str(WORK / 'logs'),
               CELERY_BROKER_URL='sqla+sqlite:///' + (WORK / 'broker.sqlite3').as_posix(),
               CELERY_RESULT_BACKEND='db+sqlite:///' + (WORK / 'results.sqlite3').as_posix())
    env.update(SCOUT_CAPTCHA_TEST_ORIGIN=site.origin,
               SCOUT_CAPTCHA_TEST_KEYS=env['SCOUT_BROWSER_KEYS'],
               SCOUT_CAPTCHA_TEST_ML='true' if '--text-task' in sys.argv else 'false',
               SCOUT_CAPTCHA_TEST_MODEL=os.environ.get('SCOUT_CAPTCHA_ML_MODEL', 'qwen3.5:4b'))
    (WORK / (SETTINGS + '.py')).write_text('''import os,ssl,json
from pathlib import Path
from src.config.patterns.development import *
SCOUT_BROWSER_ENABLED = True
SCOUT_BROWSER_CHANNEL = 'chrome'
SCOUT_BROWSER_ORIGINS = [os.environ['SCOUT_CAPTCHA_TEST_ORIGIN'], 'https://checko.ru']
SCOUT_BROWSER_KEYS = json.loads(os.environ['SCOUT_CAPTCHA_TEST_KEYS'])
SCOUT_BROWSER_ACTIVE_KEY = 'probe'
SCOUT_CAPTCHA_ML_ENABLED = os.environ['SCOUT_CAPTCHA_TEST_ML'] == 'true'
SCOUT_CAPTCHA_ML_MODEL = os.environ['SCOUT_CAPTCHA_TEST_MODEL']
SCOUT_CAPTCHA_ML_TIMEOUT_SECONDS = 25
DATABASES = {'default': {**DATABASES['default'], 'NAME': os.environ['SCOUT_CAPTCHA_DB']}}
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
from modules.scout.api.services import snapshot_store, smartcaptcha_browser
snapshot_store.CACHE_DIR = Path(os.environ['SCOUT_CAPTCHA_WORK']) / 'cache'
snapshot_store._ROOT = snapshot_store.CACHE_DIR / 'scout' / 'snapshots'
_original_context = ssl.create_default_context
def _fixture_trust(*args, **kwargs):
    context = _original_context(*args, **kwargs)
    context.load_verify_locations(cafile=os.environ['SCOUT_CAPTCHA_FIXTURE_CERT'])
    return context
ssl.create_default_context = _fixture_trust
ssl._create_default_https_context = _fixture_trust
_arguments = smartcaptcha_browser._launch_arguments
def _fixture_arguments(gateway, channel):
    options = _arguments(gateway, channel)
    options['args'].append('--ignore-certificate-errors-spki-list=' + os.environ['SCOUT_CAPTCHA_FIXTURE_SPKI'])
    return options
smartcaptcha_browser._launch_arguments = _fixture_arguments
if SCOUT_CAPTCHA_ML_ENABLED:
    import modules.ollama_framework
    modules.ollama_framework.__path__ = [str(Path(__file__).resolve().parents[4] / 'modules/ollama_framework')]
    INSTALLED_APPS = [*INSTALLED_APPS, 'modules.ollama_framework.api.apps.OllamaFrameworkConfig']
    from modules.scout.api.services import smartcaptcha_tasks
    _provider_frame = smartcaptcha_tasks.is_provider_frame
    def _fixture_frame(url):
        return url == os.environ['SCOUT_CAPTCHA_TEST_ORIGIN'] + '/advanced' or _provider_frame(url)
    smartcaptcha_tasks.is_provider_frame = _fixture_frame
''', encoding='utf-8')
    with (WORK / 'migrate.log').open('wb') as log:
        subprocess.run([sys.executable, '-m', 'src.manage', 'migrate', '--noinput'], cwd=ROOT, env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=150,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    os.environ.update(env)
    sys.path[:0] = [str(WORK), str(ROOT / 'core/api')]
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.utils import timezone
    from datetime import timedelta
    from modules.scout.api.models import Evidence, ProtectionSession, Run, VisualSnapshot
    from modules.scout.api.tasks import execute_scout_task
    from src.config.celery import ensure_django_celery_configured
    ensure_django_celery_configured()
    assert connection.vendor == 'postgresql' and connection.settings_dict['NAME'] == DB_NAME
    from modules.scout.api.services.protection_sessions import browser_enabled
    assert browser_enabled(site.origin)
    password = secrets.token_urlsafe(24)
    user = get_user_model().objects.create_superuser(username='scout-captcha-live', password=password)
    api = f'http://127.0.0.1:{port}/api/'
    start('django', env, sys.executable, '-m', 'src.manage', 'runserver', f'127.0.0.1:{port}', '--noreload')

    def worker(name):
        return start(name, env, sys.executable, str(ROOT / 'core/api/scripts/start_celery_worker.py'),
                     '--module=scout', '--pool=solo', '--concurrency=1', f'--hostname={name}-{SUFFIX}@local')

    active_worker = worker('worker')

    def ready():
        try:
            return SESSION.get(api + 'system/ready/', timeout=2).status_code == 200
        except requests.RequestException:
            return False
    wait('Django readiness', ready)
    wait('worker readiness', lambda: 'Connected to ' in (WORK / 'worker.log').read_text(errors='replace'))

    def request(method, path, code=200, **kwargs):
        response = SESSION.request(method, api + path, timeout=20, **kwargs)
        assert response.status_code == code, (path, response.status_code)
        value = response.json()
        return value.get('data', value)

    auth = request('POST', 'cms/adp/authorization/', json={'username': user.username, 'password': password})
    SESSION.headers['Authorization'] = 'Bearer ' + auth['access']
    report = {'fixture_is_our_own_form': True, 'database': 'postgresql', 'cases': [],
              'text_task': site.text_task,
              'local_model': env['SCOUT_CAPTCHA_TEST_MODEL'] if site.text_task else None}

    def state(path, status):
        def probe():
            row = request('GET', path)
            if row['status'] == status:
                return row
            if row['status'] in ('failed', 'cancelled', 'completed', 'completed_with_errors'):
                raise AssertionError({'expected': status, 'status': row['status'], 'error': row.get('error'),
                                      'task_codes': [task.get('error_code') for task in row.get('tasks', [])]})
        return wait(status, probe)

    def prepare(origin=site.origin, crawl=True):
        plan = {'title': 'Scout CAPTCHA check', 'seed_urls': [origin + '/catalog' if crawl else origin],
                'fields': [{'name': 'title', 'kind': 'css', 'selector': 'h1'}],
                'crawl': {'mode': 'site', 'parallel_fetch': 1, 'preview_pages': 1, 'max_pages': 200} if crawl else {'mode': 'pages'}}
        job = request('POST', 'scout/jobs/', 201, json=plan)
        started = request('POST', f"scout/jobs/{job['public_id']}/explore/", 202, json={})
        path = f"scout/runs/{started['public_id']}/"
        return Run.objects.get(public_id=started['public_id']), path

    def begin(path):
        state(path, 'awaiting_confirmation')
        request('POST', path + 'approve/', json={})
        request('POST', path + 'start/', 202, json={})

    def browser_busy(run):
        return ProtectionSession.objects.filter(run=run, busy_until__gt=timezone.now()).exists()

    def assert_complete(run, path):
        state(path, 'completed')
        assert run.records.count() == 3 and Evidence.objects.filter(record__run=run).count() == 3
        assert run.protection_sessions.get().ciphertext and COOKIE not in run.protection_sessions.get().ciphertext
        for task in run.tasks.all():
            assert execute_scout_task.apply_async(args=[str(task.public_id), task.fencing_token], queue='scout').get(timeout=20) == {'changed': False}
        assert run.records.count() == 3

    visual = request('POST', 'scout/visual-snapshots/', 202, json={'url': site.origin + '/catalog'})
    state(f"scout/visual-snapshots/{visual['public_id']}/", 'ready')
    assert ProtectionSession.objects.filter(visual_snapshot__public_id=visual['public_id']).count() == 1
    run, path = prepare()
    begin(path)
    assert_complete(run, path)
    rows = request('GET', path + 'records/')['records']
    assert COOKIE not in json.dumps(rows)
    if site.text_task:
        run.refresh_from_db()
        assert 'Текстовое задание SmartCaptcha решено локальной моделью' in json.dumps(run.events, ensure_ascii=False)
        assert site.text_submissions and all(site.text_submissions)
        assert site.text_answer not in json.dumps(rows)
        assert site.text_answer not in json.dumps(request('GET', path))
    report['cases'].append({'case': 'preview_collection', 'records': 3, 'evidence': 3, 'duplicate_delivery': 'ignored'})

    run, path = prepare()
    state(path, 'awaiting_confirmation')
    site.hold = True
    begin(path)
    wait('browser pause point', lambda: browser_busy(run))
    request('POST', path + 'pause/', json={})
    state(path, 'paused')
    assert not run.tasks.filter(status='failed').exists()
    site.hold = False
    request('POST', path + 'resume/', 202, json={})
    assert_complete(run, path)
    report['cases'].append({'case': 'pause_resume', 'records': 3})

    run, path = prepare()
    state(path, 'awaiting_confirmation')
    site.hold = True
    begin(path)
    wait('browser cancel point', lambda: browser_busy(run))
    request('POST', path + 'cancel/', json={})
    state(path, 'cancelled')
    site.hold = False
    count = run.records.count()
    assert not run.records.filter(snapshot__source_url__endswith='/hold').exists()
    report['cases'].append({'case': 'cancel', 'records_preserved': count})

    run, path = prepare()
    state(path, 'awaiting_confirmation')
    site.hold = True
    begin(path)
    wait('worker crash point', lambda: browser_busy(run))
    leased = run.tasks.get(status='leased')
    old_token = leased.fencing_token
    stop(active_worker)
    run.tasks.filter(pk=leased.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    run.protection_sessions.update(busy_until=timezone.now() - timedelta(seconds=1))
    site.hold = False
    active_worker = worker('worker-recovered')
    (WORK / 'captcha_beat.py').write_text('''import django
from src.config.celery import celery_app,ensure_django_celery_configured
django.setup()
ensure_django_celery_configured()
from modules.scout.api.celery_beat_config import ScoutBeatConfig
celery_app.conf.beat_schedule = ScoutBeatConfig('scout').get_beat_schedule()
''', encoding='utf-8')
    start('beat', env, sys.executable, '-m', 'celery', '-A', 'captcha_beat:celery_app', 'beat',
          '--loglevel=INFO', '--schedule=' + str(WORK / 'beat.db'))
    assert_complete(run, path)
    assert execute_scout_task.apply_async(args=[str(leased.public_id), old_token], queue='scout').get(timeout=20) == {'changed': False}
    report['cases'].append({'case': 'worker_crash_beat_recovery', 'records': 3, 'old_attempt': 'ignored'})

    site.reject = True
    run, path = prepare()
    failed = state(path, 'failed')
    assert run.tasks.get(status='failed').error_code == 'captcha_not_cleared', run.tasks.get(status='failed').error_code
    assert not run.records.exists() and not run.snapshots.exists() and not run.protection_sessions.get().ciphertext
    site.reject = False
    report['cases'].append({'case': 'rejected_form', 'records': 0})

    if '--checko' in sys.argv:
        if '--trigger-checko' in sys.argv:
            from modules.scout.api.services.public_http import fetch_public_html
            from modules.scout.api.services.errors import FetchError
            count = 0
            reason = ''
            for count in range(1, 201):
                tick = time.monotonic()
                try:
                    fetch_public_html('https://checko.ru/company/promyshlennost-1021100507999',
                                      timeout_seconds=10, max_bytes=1000000)
                except FetchError as exc:
                    reason = exc.code
                    break
                time.sleep(max(0, 1 - (time.monotonic() - tick)))
            report['checko_trigger'] = {'requests': count, 'stop_code': reason}
            emit(report['checko_trigger'])
        run, path = prepare('https://checko.ru/company/promyshlennost-1021100507999', crawl=False)
        try:
            begin(path)
            state(path, 'completed')
        except AssertionError:
            # Отказ настоящего провайдера — результат проверки, а не успех нашей формы.
            run.refresh_from_db()
            report['checko_failure'] = {'status': run.status,
                                       'task_codes': list(run.tasks.exclude(error_code='').values_list('error_code', flat=True))}
            if run.status not in ('failed', 'cancelled', 'completed', 'completed_with_errors'):
                raise
        run.refresh_from_db()
        report['checko'] = {'records': run.records.count(), 'evidence': Evidence.objects.filter(record__run=run).count(),
                           'browser_sessions': run.protection_sessions.count(),
                           'checkbox_cleared': 'Флажок SmartCaptcha пройден' in json.dumps(run.events, ensure_ascii=False)}
        report['checko']['text_task_cleared'] = 'Текстовое задание SmartCaptcha решено локальной моделью' in json.dumps(run.events, ensure_ascii=False)
    for path in WORK.glob('*.log'):
        assert COOKIE.encode() not in path.read_bytes(), path.name
    assert COOKIE.encode() not in (WORK / 'broker.sqlite3').read_bytes()
    if site.text_task:
        report['fixture_text_submissions'] = len(site.text_submissions)
        for path in [*WORK.glob('*.log'), WORK / 'broker.sqlite3']:
            assert site.text_answer.encode() not in path.read_bytes(), path.name
    report['secrets_in_api_logs_broker'] = False
    report['working_limit'] = 200
    (WORK / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    emit(report)
    if report.get('checko_failure'):
        raise AssertionError('Реальное прохождение Чекко не подтверждено; причина сохранена в result.json')


if __name__ == '__main__':
    emit('Artifacts: ' + str(WORK))
    site = SmartCaptchaSite(WORK / 'fixture')
    site.text_task = '--text-task' in sys.argv
    created = False
    try:
        database(True)
        created = True
        run(site)
    finally:
        for process in reversed(PROCESSES):
            stop(process)
        site.close()
        if SETTINGS in sys.modules:
            from django.db import connections
            connections.close_all()
        if created:
            database(False)
            emit('Temporary database dropped')
