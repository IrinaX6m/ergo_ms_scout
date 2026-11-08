"""Собственная HTTPS-форма с тестовым флажком. Не эмуляция ML/токена настоящего Яндекса."""

import base64
import hashlib
import ipaddress
import io
import json
import ssl
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

COOKIE = 'fixture-clearance-sentinel'


class SmartCaptchaSite:
    def __init__(self, directory):
        self.hold = False
        self.reject = False
        self.hits = []
        self.text_task = False
        self.text_answer = '48271'
        self.text_submissions = []
        self.task_version = 1
        self.refresh_text = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cleared = 'hc=' + COOKIE in self.headers.get('Cookie', '')
                owner.hits.append({'method': 'GET', 'path': self.path, 'cleared': cleared})
                if self.path == '/frame':
                    callback = '' if owner.hold else "parent.document.querySelector('[name=smart-token]').value='fixture-answer'"
                    if owner.text_task and not owner.hold:
                        callback = "let f=parent.document.createElement('iframe');f.dataset.testid='advanced-iframe';f.src='/advanced';parent.document.body.append(f)"
                    return self.respond(200, '<input type="checkbox" aria-label="Я не робот" onclick="' + callback + '">')
                if self.path == '/advanced':
                    poll = ("let poll=setInterval(async()=>{let v=await (await fetch('/version')).text();"
                            "if(v!='1'){document.querySelector('img').src='/task.png?v='+v;clearInterval(poll)}},100)") if owner.refresh_text else ''
                    return self.respond(200, '''<img aria-hidden="true" alt="Задание с картинкой" src="/task.png?v=1">
<input name="rep" placeholder="Строчные или прописные буквы"><button onclick="send()">Отправить</button>
<script>async function send(){let r=await fetch('/verify-text',{method:'POST',body:new URLSearchParams({answer:document.querySelector('[name=rep]').value})});
if((await r.json()).valid){parent.document.querySelector('[name=smart-token]').value='fixture-answer';parent.document.querySelector('[data-testid=advanced-iframe]').style.display='none'}
else{document.querySelector('img').src='/task.png?v='+Date.now()}};''' + poll + '</script>')
                if self.path.startswith('/task.png'):
                    from PIL import Image, ImageDraw, ImageFont
                    image = Image.new('RGB', (240, 80), 'white')
                    ImageDraw.Draw(image).text((16, 12), owner.text_answer, font=ImageFont.load_default(size=44), fill='black')
                    buffer = io.BytesIO()
                    image.save(buffer, format='PNG')
                    return self.respond(200, buffer.getvalue(), mime='image/png')
                if self.path == '/version':
                    return self.respond(200, str(owner.task_version))
                if not cleared or self.path == '/hold' and owner.hold:
                    return self.respond(429, '''<title>Пожалуйста, подтвердите, что вы человек!</title>
<script src="https://smartcaptcha.yandexcloud.net/captcha.js"></script>
<form action="/check/humaneness" method="post"><input name="challenge" value="fixture-challenge">
<input name="authenticity_token" value="fixture-csrf"><input type="hidden" name="smart-token">
<div class="smart-captcha"><iframe data-testid="checkbox-iframe" src="/frame"></iframe></div>
<button type="submit">Подтвердить</button></form>''')
                links = '<a href="/one">One</a><a href="/hold">Hold</a>' if self.path == '/catalog' else ''
                self.respond(200, '<h1>Product ' + self.path + '</h1>' + links)

            def do_POST(self):
                body = self.rfile.read(min(int(self.headers.get('Content-Length', '0')), 8192)).decode()
                fields = parse_qs(body)
                if self.path == '/verify-text':
                    valid = fields.get('answer') == [owner.text_answer]
                    owner.text_submissions.append(valid)
                    return self.respond(200, json.dumps({'valid': valid}), mime='application/json')
                owner.hits.append({'method': 'POST', 'path': self.path, 'valid': fields.get('smart-token') == ['fixture-answer']})
                if owner.reject or fields.get('smart-token') != ['fixture-answer']:
                    return self.respond(429, '<title>CAPTCHA</title>Not cleared')
                self.send_response(303)
                self.send_header('Location', '/catalog')
                self.send_header('Set-Cookie', 'hc=' + COOKIE + '; Secure; HttpOnly; SameSite=Lax; Path=/')
                self.send_header('Content-Length', '0')
                self.end_headers()

            def respond(self, code, text, mime='text/html; charset=utf-8'):
                body = text if isinstance(text, bytes) else text.encode()
                self.send_response(code)
                self.send_header('Content-Type', mime)
                # Собственный виджет ниже: к настоящему провайдеру фикстура не обращается.
                self.send_header('Content-Security-Policy', "script-src 'unsafe-inline'; object-src 'none'")
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Scout local browser fixture')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                       .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                       .not_valid_after(now + timedelta(days=1))
                       .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
                       .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                       .sign(key, hashes.SHA256()))
        self.cert_file = directory / 'fixture.pem'
        key_file = directory / 'fixture.key'
        self.cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.spki = base64.b64encode(hashlib.sha256(spki).digest()).decode()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert_file, key_file)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.origin = f'https://127.0.0.1:{self.port}'
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
