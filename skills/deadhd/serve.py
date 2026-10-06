#!/usr/bin/env python3
"""deadhd 페이지를 127.0.0.1 전용 정적 서버로 제공한다."""
import http.server
import os
import re
import stat
import subprocess
import sys
import threading
import time
import urllib.request

sys.dont_write_bytecode = True

DEFAULT_PORT = 47320
DEFAULT_ROOT = '/tmp'
NAME_RE = re.compile(r'deadhd-[A-Za-z0-9._-]+\.html')
HEALTH_TIMEOUT = 3.0
USAGE = '사용법: serve.py [--ensure|--daemon|--stop|--url <파일>]'


def port():
    raw = os.environ.get('DEADHD_PORT')
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if 1 <= value <= 65535:
            return value
    return DEFAULT_PORT


def serve_root():
    return os.environ.get('DEADHD_SERVE_ROOT') or DEFAULT_ROOT


def base_url():
    return 'http://127.0.0.1:%d/' % port()


def page_name(path):
    """서빙 규칙에 맞는 파일이면 URL 에 쓸 이름, 아니면 None."""
    name = os.path.basename(path)
    if NAME_RE.fullmatch(name) is None:
        return None
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(serve_root()):
        return None
    return name


def http_url(path):
    name = page_name(path)
    return None if name is None else base_url() + name


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def allowed_host(self):
        # 외부 사이트가 브라우저를 통해 127.0.0.1 을 읽는 것을 막는다(DNS 리바인딩).
        bound = self.server.server_address[1]
        return self.headers.get('Host') in (
            '127.0.0.1:%d' % bound, 'localhost:%d' % bound, '127.0.0.1', 'localhost')

    def respond(self, code, body, ctype='text/plain; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(body)
            except OSError:
                pass

    def serve_page(self):
        if not self.allowed_host():
            return self.respond(403, b'forbidden\n')
        path = self.path.split('?', 1)[0]
        if path == '/healthz':
            return self.respond(200, b'ok\n')
        name = path[1:]
        if not path.startswith('/') or NAME_RE.fullmatch(name) is None:
            return self.respond(404, b'not found\n')
        root = os.path.realpath(serve_root())
        full = os.path.join(root, name)
        try:
            mode = os.lstat(full).st_mode
        except OSError:
            return self.respond(404, b'not found\n')
        if stat.S_ISLNK(mode):
            return self.respond(404, b'not found\n')
        if os.path.dirname(os.path.realpath(full)) != root:
            return self.respond(404, b'not found\n')
        if not os.path.isfile(full):
            return self.respond(404, b'not found\n')
        try:
            with open(full, 'rb') as f:
                body = f.read()
        except OSError:
            return self.respond(404, b'not found\n')
        self.respond(200, body, 'text/html; charset=utf-8')

    def method_not_allowed(self):
        self.respond(405, b'method not allowed\n')

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = method_not_allowed

    def do_GET(self):
        self.serve_page()

    def do_HEAD(self):
        self.serve_page()

    def do_POST(self):
        if not self.allowed_host():
            return self.respond(403, b'forbidden\n')
        if self.path.split('?', 1)[0] != '/quit':
            return self.respond(405, b'method not allowed\n')
        if self.headers.get('X-Deadhd') != 'stop':
            return self.respond(403, b'forbidden\n')
        self.respond(200, b'bye\n')
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def health():
    try:
        with urllib.request.urlopen(base_url() + 'healthz', timeout=1.0) as r:
            return r.status == 200 and r.read(2) == b'ok'
    except Exception:
        return False


def ensure():
    if health():
        print('base: ' + base_url())
        return 0
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), '--daemon'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True)
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        if health():
            print('base: ' + base_url())
            return 0
        time.sleep(0.05)
    sys.stderr.write('serve.py: 서버가 뜨지 않았다\n')
    return 1


def daemon():
    try:
        server = http.server.ThreadingHTTPServer(('127.0.0.1', port()), Handler)
    except OSError:
        return 0
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def stop():
    if not health():
        print('stopped: none')
        return 0
    try:
        request = urllib.request.Request(base_url() + 'quit', data=b'', method='POST',
                                         headers={'X-Deadhd': 'stop'})
        with urllib.request.urlopen(request, timeout=2.0) as r:
            r.read()
    except Exception:
        pass
    print('stopped: ' + base_url())
    return 0


def main(argv):
    args = argv[1:]
    if args == ['--ensure']:
        return ensure()
    if args == ['--daemon']:
        return daemon()
    if args == ['--stop']:
        return stop()
    if len(args) == 2 and args[0] == '--url':
        url = http_url(args[1])
        if url is None:
            return 2
        print(url)
        return 0
    sys.stderr.write(USAGE + '\n')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
