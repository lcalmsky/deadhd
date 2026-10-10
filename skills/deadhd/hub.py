#!/usr/bin/env python3
"""상태 파일들을 한 장으로 모아 이 컴퓨터의 세션 허브 페이지를 만든다."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
HUB_TEMPLATE = os.path.join(HERE, 'hub.html')
DEFAULT_HUB = '/tmp/deadhd-hub.html'
BUCKETS = ('wait', 'stall', 'idle', 'working', 'untracked', 'done', 'ended', 'stale')
BUCKET_RANK = {name: i for i, name in enumerate(BUCKETS)}
# 이보다 오래 갱신되지 않은 세션은 지난 세션으로 접는다.
STALE_SECONDS = 24 * 3600
STALL_SECONDS = 10 * 60
TITLES = {'ko': 'deadhd 허브', 'en': 'deadhd hub'}
USAGE = '사용법: hub.py [--theme <테마>] [--font <프리셋>] [<out.html>]'

sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import config
import render
import serve
import state

EPOCH = datetime.min.replace(tzinfo=timezone.utc)


class HubError(Exception):
    pass


def die(msg):
    sys.stderr.write('hub.py: ' + msg + '\n')
    sys.exit(1)


def hub_path():
    return os.environ.get('DEADHD_HUB') or DEFAULT_HUB


def page_href(out):
    """서빙 규칙에 맞는 페이지는 http 주소로, 아니면 file:// 로."""
    if not out:
        return None
    return serve.http_url(out) or render.file_url(out)


def bucket(session, now):
    summary = session.get('summary') or {}
    if session.get('status') == 'ended':
        return 'ended'
    updated = render.parse_when(session.get('updatedAt'))
    if updated is None or (now - updated).total_seconds() > STALE_SECONDS:
        return 'stale'
    # 훅이 없는 설치는 상태를 알 수 없다. 단계 진행만으로 완료/미추적을 가른다.
    if not summary.get('hooked'):
        return 'done' if summary.get('allDone') else 'untracked'
    # 완료된 작업은 기다리는 세션이 아니다. 상태와 무관하게 완료로 둔다.
    if summary.get('allDone'):
        return 'done'
    if session.get('status') == 'waiting_permission':
        return 'wait'
    if session.get('status') == 'idle':
        return 'idle'
    tool = session.get('lastTool')
    at = render.parse_when(tool.get('at')) if isinstance(tool, dict) else None
    if session.get('status') == 'working' and at is not None and (now - at).total_seconds() > STALL_SECONDS:
        return 'stall'
    return 'working'


def order_key(session):
    # 같은 버킷 안에서는 오래 기다린 세션이 위로 온다.
    since = render.parse_when(session.get('since'))
    return (BUCKET_RANK[session['bucket']], since is None, since or EPOCH, session['sessionId'])


def collect(state_dir):
    try:
        names = os.listdir(state_dir)
    except OSError:
        return []
    sessions = []
    for name in sorted(names):
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(state_dir, name), encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get('summary'), dict):
            continue
        out = data.get('out')
        out = out if isinstance(out, str) and os.path.isabs(out) else None
        # 아직 페이지를 쓰지 않은 세션에는 링크를 걸지 않는다. 깨진 링크가 되기 때문이다.
        href = page_href(out) if out and os.path.exists(out) else None
        view = data.get('view')
        # 페이지가 없는 세션은 view 로 어디를 보고 있는지 알린다. html 세션은 페이지 파일이
        # 사라진 경우라 이름 대신 「페이지 없음」으로 드러난다.
        view = view if href is None and view in ('html', 'band', 'statusline') else None
        tasks = data.get('backgroundTasks')
        compactions = data.get('compactions')
        tool = data.get('lastTool')
        sessions.append({
            'sessionId': data.get('sessionId') if isinstance(data.get('sessionId'), str) else name[:-5],
            'out': out,
            'href': href,
            'view': view,
            'status': data.get('status') if isinstance(data.get('status'), str) else None,
            'since': data.get('since') if isinstance(data.get('since'), str) else None,
            'message': data.get('message') if isinstance(data.get('message'), str) else None,
            'lastTool': tool if isinstance(tool, dict) else None,
            'backgroundTasks': tasks if isinstance(tasks, list) else [],
            'compactions': compactions if isinstance(compactions, dict) else {},
            'updatedAt': data.get('updatedAt') if isinstance(data.get('updatedAt'), str) else None,
            'cwd': data.get('cwd') if isinstance(data.get('cwd'), str) else None,
            'summary': data['summary'],
        })
    return sessions


def write_hub(theme=None, font=None, now=None, out=None):
    path = out or hub_path()
    if theme is None:
        theme = config.get_value('theme') or 'system'
    if font is None:
        font = config.get_value('font') or 'default'
    current = now or render.current_time()
    sessions = collect(state.state_dir())
    for session in sessions:
        session['bucket'] = bucket(session, current)
    sessions.sort(key=order_key)

    lang = 'en' if sessions and all(s['summary'].get('lang') == 'en' for s in sessions) else 'ko'
    try:
        with open(HUB_TEMPLATE, encoding='utf-8') as f:
            tpl = f.read()
    except OSError as e:
        raise HubError('허브 템플릿을 읽지 못했다: %s' % e)
    try:
        css = render.theme_css()
    except OSError as e:
        raise HubError('테마 CSS 를 읽지 못했다: %s' % e)

    if tpl.count(render.HTML_OPEN) != 1:
        raise HubError('템플릿에 %s 가 정확히 하나 있지 않다' % render.HTML_OPEN)
    html_open = '<html lang="%s"' % lang
    if theme != 'system':
        html_open += ' data-theme="%s"' % theme
    if font != 'default':
        html_open += ' data-font="%s"' % font
    html_open += '>'

    if tpl.count('__THEME_CSS__') != 1:
        raise HubError('템플릿에 __THEME_CSS__ 가 정확히 하나 있지 않다')
    payload = {'lang': lang, 'renderedAt': current.isoformat(timespec='seconds'), 'sessions': sessions}
    page = (tpl.replace(render.HTML_OPEN, html_open)
               .replace('__THEME_CSS__', css)
               .replace('__HUB_TITLE__', escape(TITLES[lang]))
               .replace('__HUB_DATA__', render.script_json(payload)))

    out_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix='.hub-', suffix='.html')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(page)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    return path


def main(argv):
    theme = None
    font = None
    out = None
    rest = argv[1:]
    while rest[:1] in (['--theme'], ['--font']):
        flag = rest[0]
        if len(rest) < 2:
            die(USAGE)
        if flag == '--theme':
            if theme is not None:
                die(USAGE)
            theme = rest[1]
        else:
            if font is not None:
                die(USAGE)
            font = rest[1]
        rest = rest[2:]
    if len(rest) > 1:
        die(USAGE)
    if rest:
        out = rest[0]
    if theme is not None and theme not in render.THEMES:
        die('알 수 없는 테마: %s (%s 중 하나)' % (theme, '/'.join(render.THEMES)))
    if font is not None and font not in render.FONTS:
        die('알 수 없는 글꼴: %s (%s 중 하나)' % (font, '/'.join(render.FONTS)))
    try:
        path = write_hub(theme=theme, font=font, out=out)
    except Exception as e:
        die(str(e))
    print('rendered: ' + path)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
