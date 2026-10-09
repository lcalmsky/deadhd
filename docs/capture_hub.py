#!/usr/bin/env python3
"""세션 네 개를 docs/demos 의 사례로 렌더하고 상태를 주입해 허브 그림 docs/hub.png 와 세션 페이지 그림 docs/live.png 를 만든다. Chrome 헤드리스 실행 파일이 필요하다."""
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

from capture_themes import CASES, CHROME, CLOCK, RENDER, chrome_args, chrome_shot, die, render_panel

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HUB = os.path.join(REPO, 'skills', 'deadhd', 'hub.py')
STATE = os.path.join(REPO, 'skills', 'deadhd', 'state.py')

THEME = 'dark'
# 경과 시간을 재는 기준 시각. 세 페이지와 허브를 모두 이 시각에 맞춘다.
NOW = CASES['lanes-blocked']
# 창 폭은 README 본문에 맞춘 900 CSS 다. 배율 2 로 찍으므로 결과는 1800px 이 된다.
WINDOW_W = 900
# 타일 수가 세션에 따라 달라지므로 허브 높이는 내용을 재서 정하고, live 는 띠·진행 막대·흐름도 윗부분이 보이는 값으로 고정한다.
LIVE_H = 850
SIZE_MARK = 'deadhd-hub-height:'
LIVE_SESSION = 'demo-2'
# 아직 페이지를 쓰지 않은 세션. 허브가 링크 대신 표시 방식 이름을 그리는지 그림에서 보이게 한다.
BAND_SESSION, BAND_VIEW = 'demo-1', 'band'
STATUS_OF = {'Notification': 'waiting_permission', 'PostToolUse': 'working',
             'Stop': 'idle', 'SessionEnd': 'ended'}
# 보정 계수 1.6 이 나오는 세 줄. 세션 페이지의 완료 예상이 보정값으로 바뀐다.
HISTORY_ROWS = ({'est': 10, 'actual': 16}, {'est': 20, 'actual': 32}, {'est': 30, 'actual': 48})

# (세션, 사례, 주입할 훅, since 를 되돌릴 분, lastTool.at 을 되돌릴 초)
SESSIONS = (
    ('demo-1', 'lanes-blocked', {'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                                 'message': 'Claude needs your permission to use Bash'}, 12, None),
    ('demo-2', 'parallel', {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'duration_ms': 1200},
     None, 8),
    ('demo-3', 'overnight', {'hook_event_name': 'Stop'}, 23, None),
    ('demo-4', 'done', {'hook_event_name': 'SessionEnd', 'reason': 'exit'}, None, None),
)

# live 그림은 허브와 다른 상태로 찍는다. 허브가 네 상태를 그대로 보여 주도록 주입은 허브 캡처 뒤에 한다.
LIVE_HOOK = {'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
             'message': 'Claude needs your permission to use Bash'}
LIVE_MINUTES = 12
LIVE_CASE = next(case for session, case, _, _, _ in SESSIONS if session == LIVE_SESSION)


def work_env(work):
    # 렌더·훅·허브가 이 컴퓨터의 실제 세션 상태와 허브를 건드리지 않게 전부 작업 디렉터리로 돌린다.
    env = dict(os.environ, TZ='Asia/Seoul', DEADHD_NOW=NOW,
               DEADHD_STATE_DIR=os.path.join(work, 'state'),
               DEADHD_HUB=os.path.join(work, 'hub.html'),
               DEADHD_HISTORY=os.path.join(work, 'history.jsonl'))
    env.pop('CLAUDE_CODE_SESSION_ID', None)
    return env


def inject(session, payload, env):
    subprocess.run([sys.executable, STATE], input=json.dumps(dict(payload, session_id=session)),
                   capture_output=True, text=True, env=env)


def render_band_state(case, session, work, demos_dir, env):
    # 밴드는 페이지를 쓰지 않는다. 상태 요약만 갱신하고, 허브는 그 요약을 읽어 칩을 그린다.
    src = os.path.join(demos_dir, case + '.json')
    result = subprocess.run([sys.executable, RENDER, '--theme', THEME, '--view', BAND_VIEW,
                             '--session', session, src, os.path.join(work, case + '.band.html')],
                            capture_output=True, text=True, env=env)
    if result.returncode != 0:
        die('%s 밴드 렌더 실패: %s' % (case, (result.stderr or result.stdout).strip()))


def backdate(state_dir, session, minutes, tool_seconds):
    # 훅은 실제 시계로 찍은 시각을 남긴다. 페이지 시계는 NOW 에 고정하므로, 되돌리지 않으면
    # 경과 시간이 며칠로 나온다.
    path = os.path.join(state_dir, session + '.json')
    with open(path, encoding='utf-8') as f:
        state = json.load(f)
    base = datetime.fromisoformat(NOW)
    if minutes:
        state['since'] = (base - timedelta(minutes=minutes)).isoformat(timespec='seconds')
    if tool_seconds and isinstance(state.get('lastTool'), dict):
        state['lastTool']['at'] = (base - timedelta(seconds=tool_seconds)).isoformat(timespec='seconds')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    return state


def clocked(path):
    probe = ("<script>window.addEventListener('load', function () {"
             "console.log('%s' + document.documentElement.scrollHeight);});</script>" % SIZE_MARK)
    with open(path, encoding='utf-8') as f:
        page = f.read()
    page = page.replace('<head>', '<head>\n' + CLOCK % NOW + probe, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page)
    return path


def page_height(html):
    """페이지가 알려 준 내용 높이(CSS px). 창을 이 높이로 찍어 아래 빈 배경이 남지 않게 한다."""
    ud_dir = tempfile.mkdtemp(prefix='deadhd-hub-measure-')
    args = chrome_args(ud_dir, (WINDOW_W, 400),
                       ['--enable-logging=stderr', '--v=1', 'file://' + html])
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    fd = proc.stderr.fileno()
    buf = b''
    deadline = time.time() + 60
    try:
        while time.time() < deadline:
            if select.select([fd], [], [], 0.5)[0]:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                buf += chunk
                found = re.search(re.escape(SIZE_MARK.encode()) + rb'(\d+)', buf)
                if found:
                    return int(found.group(1))
            elif proc.poll() is not None:
                break
        return None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        shutil.rmtree(ud_dir, ignore_errors=True)


def shoot(ud_dir, html, window, out_png, what):
    # 캡처가 실패해도 기존 그림을 잃지 않게 임시 파일에 찍고 옮긴다.
    tmp_png = out_png + '.tmp.png'
    chrome_shot(chrome_args(ud_dir, window, ['--screenshot=' + tmp_png, 'file://' + html]), tmp_png)
    os.replace(tmp_png, out_png)
    print('%s: %s (%dx%d)' % (what, out_png, window[0], window[1]))


def main(argv):
    lang = 'ko'
    rest = argv[1:]
    if rest[:1] == ['--lang']:
        if len(rest) < 2:
            die('사용법: capture_hub.py [--lang ko|en]')
        lang, rest = rest[1], rest[2:]
    if lang not in ('ko', 'en') or rest:
        die('사용법: capture_hub.py [--lang ko|en]')
    if not os.path.exists(CHROME):
        die('Chrome 을 찾지 못했다: %s (환경 변수 CHROME 로 지정)' % CHROME)

    demos_dir = os.path.join(HERE, 'demos', 'en') if lang == 'en' else os.path.join(HERE, 'demos')
    suffix = '.en.png' if lang == 'en' else '.png'

    work = tempfile.mkdtemp(prefix='deadhd-hub-')
    ud_root = tempfile.mkdtemp(prefix='deadhd-chrome-')
    try:
        state_dir = os.path.join(work, 'state')
        hub_html = os.path.join(work, 'hub.html')
        history = os.path.join(work, 'history.jsonl')
        with open(history, 'w', encoding='utf-8') as f:
            for row in HISTORY_ROWS:
                f.write(json.dumps(row) + '\n')
        env = work_env(work)
        # 이 컴퓨터의 설정이 band·statusline 이면 render.py 가 HTML 페이지를 쓰지 않아 캡처할 것이 없다.
        # 세션마다 view 를 못박은 설정을 줘서 찍는 사람의 설정과 무관하게 같은 그림이 나오게 한다.
        html_config = os.path.join(work, 'html-config.json')
        with open(html_config, 'w', encoding='utf-8') as f:
            json.dump({'view': 'html'}, f)
        env = dict(env, DEADHD_CONFIG=html_config)
        # 밴드 세션은 설정도 밴드여야 한다. 훅이 페이지를 다시 렌더할 때 설정값으로 view 를 덮어쓰기 때문이다.
        band_config = os.path.join(work, 'band-config.json')
        with open(band_config, 'w', encoding='utf-8') as f:
            json.dump({'view': BAND_VIEW}, f)
        band_env = dict(env, DEADHD_CONFIG=band_config)
        panels = {}
        for session, case, payload, minutes, tool_seconds in SESSIONS:
            band = session == BAND_SESSION
            session_env = band_env if band else env
            if band:
                render_band_state(case, session, work, demos_dir, session_env)
            else:
                panels[session] = render_panel(case, THEME, work, demos_dir, session=session, now=NOW,
                                               extra_env={'DEADHD_HISTORY': history,
                                                          'DEADHD_CONFIG': html_config})
            inject(session, payload, session_env)
            state = backdate(state_dir, session, minutes, tool_seconds)
            if state.get('status') != STATUS_OF[payload['hook_event_name']]:
                die('%s 상태가 주입대로 바뀌지 않았다: %r' % (session, state.get('status')))
            if state.get('view') != (BAND_VIEW if band else 'html'):
                die('%s 표시 방식이 %r 이다' % (session, state.get('view')))
            # 띠와 타일은 상태 파일을 읽어 만든다. 되돌린 시각을 반영하려면 다시 렌더해야 한다.
            if not band:
                panels[session] = render_panel(case, THEME, work, demos_dir, session=session, now=NOW,
                                               extra_env={'DEADHD_HISTORY': history,
                                                          'DEADHD_CONFIG': html_config})
            print('session: %s (%s)' % (session, case))

        result = subprocess.run([sys.executable, HUB, '--theme', THEME],
                                capture_output=True, text=True, env=env)
        if result.returncode != 0:
            die('허브 렌더 실패: %s' % (result.stderr or result.stdout).strip())

        hub_page = clocked(hub_html)
        height = page_height(hub_page)
        if height is None:
            die('허브 페이지가 자기 높이를 알려 주지 않았다: %s' % hub_page)
        shoot(os.path.join(ud_root, 'hub'), hub_page, (WINDOW_W, height),
              os.path.join(HERE, 'hub' + suffix), 'hub')

        inject(LIVE_SESSION, LIVE_HOOK, env)
        state = backdate(state_dir, LIVE_SESSION, LIVE_MINUTES, None)
        if state.get('status') != STATUS_OF['Notification']:
            die('%s 상태가 주입대로 바뀌지 않았다: %r' % (LIVE_SESSION, state.get('status')))
        panels[LIVE_SESSION] = render_panel(LIVE_CASE, THEME, work, demos_dir, session=LIVE_SESSION,
                                            now=NOW, extra_env={'DEADHD_HISTORY': history,
                                                                'DEADHD_CONFIG': html_config})
        shoot(os.path.join(ud_root, 'live'), panels[LIVE_SESSION], (WINDOW_W, LIVE_H),
              os.path.join(HERE, 'live' + suffix), 'live')
    finally:
        shutil.rmtree(ud_root, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv)
