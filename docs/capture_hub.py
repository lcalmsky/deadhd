#!/usr/bin/env python3
"""세션 네 개를 docs/demos 의 사례로 렌더하고 상태를 주입해 허브 그림 docs/hub.png 와 세션 페이지 그림 docs/live.png 를 만든다. Chrome 헤드리스 실행 파일이 필요하다."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

from capture_themes import CASES, CHROME, CLOCK, chrome_args, chrome_shot, die, render_panel

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HUB = os.path.join(REPO, 'skills', 'deadhd', 'hub.py')
STATE = os.path.join(REPO, 'skills', 'deadhd', 'state.py')

THEME = 'dark'
# 경과 시간을 재는 기준 시각. 세 페이지와 허브를 모두 이 시각에 맞춘다.
NOW = CASES['lanes-blocked']
HUB_WINDOW, LIVE_WINDOW = (1200, 820), (1200, 760)
LIVE_SESSION = 'demo-2'
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
    with open(path, encoding='utf-8') as f:
        page = f.read()
    page = page.replace('<head>', '<head>\n' + CLOCK % NOW, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page)
    return path


def shoot(ud_dir, html, window, out_png, what):
    # 캡처가 실패해도 기존 그림을 잃지 않게 임시 파일에 찍고 옮긴다.
    tmp_png = out_png + '.tmp.png'
    chrome_shot(chrome_args(ud_dir, window, ['--screenshot=' + tmp_png, 'file://' + html]), tmp_png)
    os.replace(tmp_png, out_png)
    print('%s: %s' % (what, out_png))


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
        panels = {}
        for session, case, payload, minutes, tool_seconds in SESSIONS:
            panels[session] = render_panel(case, THEME, work, demos_dir, session=session, now=NOW,
                                           extra_env={'DEADHD_HISTORY': history})
            inject(session, payload, env)
            state = backdate(state_dir, session, minutes, tool_seconds)
            if state.get('status') != STATUS_OF[payload['hook_event_name']]:
                die('%s 상태가 주입대로 바뀌지 않았다: %r' % (session, state.get('status')))
            # 띠와 타일은 상태 파일을 읽어 만든다. 되돌린 시각을 반영하려면 다시 렌더해야 한다.
            panels[session] = render_panel(case, THEME, work, demos_dir, session=session, now=NOW,
                                           extra_env={'DEADHD_HISTORY': history})
            print('session: %s (%s)' % (session, case))

        result = subprocess.run([sys.executable, HUB, '--theme', THEME],
                                capture_output=True, text=True, env=env)
        if result.returncode != 0:
            die('허브 렌더 실패: %s' % (result.stderr or result.stdout).strip())

        shoot(os.path.join(ud_root, 'hub'), clocked(hub_html), HUB_WINDOW,
              os.path.join(HERE, 'hub' + suffix), 'hub')

        inject(LIVE_SESSION, LIVE_HOOK, env)
        state = backdate(state_dir, LIVE_SESSION, LIVE_MINUTES, None)
        if state.get('status') != STATUS_OF['Notification']:
            die('%s 상태가 주입대로 바뀌지 않았다: %r' % (LIVE_SESSION, state.get('status')))
        panels[LIVE_SESSION] = render_panel(LIVE_CASE, THEME, work, demos_dir, session=LIVE_SESSION,
                                            now=NOW, extra_env={'DEADHD_HISTORY': history})
        shoot(os.path.join(ud_root, 'live'), panels[LIVE_SESSION], LIVE_WINDOW,
              os.path.join(HERE, 'live' + suffix), 'live')
    finally:
        shutil.rmtree(ud_root, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv)
