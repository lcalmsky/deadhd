#!/usr/bin/env python3
"""Claude Code 훅의 stdin JSON 을 세션 상태 파일로 옮기고 페이지를 다시 렌더한다."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, 'render.py')
DEFAULT_DIR = '/tmp/deadhd-state'
STALE_SECONDS = 7 * 24 * 3600
RENDER_SKIP_SECONDS = 10
REPEAT_SECONDS = 5
REPLY_TAIL_CHARS = 120
SESSION_ID = re.compile(r'[A-Za-z0-9._-]{1,128}')
FENCE = re.compile(r'^(```|~~~)')
HEADING = re.compile(r'^#{1,6}\s+')
QUOTE = re.compile(r'^>\s*')
BULLET = re.compile(r'^(?:[-*+]\s+|\d+[.)]\s+)')
MD_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')
SPACES = re.compile(r'\s+')


def state_dir():
    return os.environ.get('DEADHD_STATE_DIR') or DEFAULT_DIR


def valid_session_id(value):
    return (isinstance(value, str) and SESSION_ID.fullmatch(value) is not None
            and value not in ('.', '..'))


def state_path(session_id):
    if not valid_session_id(session_id):
        raise ValueError('잘못된 세션 id: %r' % (session_id,))
    return os.path.join(state_dir(), session_id + '.json')


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def now_iso_ms():
    """꺼진 시각. render.py 가 데이터 파일 시각과 견주므로 밀리초까지 남긴다."""
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def load_state(session_id):
    try:
        with open(state_path(session_id), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(session_id, state):
    path = state_path(session_id)
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.deadhd-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def drop_stale_states(keep_id):
    directory = state_dir()
    cutoff = time.time() - STALE_SECONDS
    keep = state_path(keep_id)
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if not name.endswith('.json'):
            continue
        path = os.path.join(directory, name)
        if path == keep:
            continue
        try:
            if os.path.getmtime(path) < cutoff:
                os.unlink(path)
        except OSError:
            pass


def read_payload():
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def background_tasks(payload):
    raw = payload.get('background_tasks')
    if not isinstance(raw, list):
        return []
    kept = []
    for task in raw:
        if not isinstance(task, dict):
            continue
        kept.append({
            'type': task.get('type') if isinstance(task.get('type'), str) else '',
            'description': task.get('description') if isinstance(task.get('description'), str) else '',
        })
    return kept


def parse_stamp(value):
    """ISO 시각 문자열을 시간대 있는 datetime 으로. 못 읽으면 None."""
    if not isinstance(value, str):
        return None
    text = value[:-1] + '+00:00' if value.endswith('Z') else value
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def event_key(payload):
    """이벤트 하나의 지문.

    엔진은 한 이벤트를 등록된 훅마다 한 번씩 보내므로, 플러그인 훅과
    settings.json 훅이 함께 있으면 같은 입력이 두 번 들어온다.
    """
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def repeated_event(state, key):
    """방금 전에 같은 이벤트를 이미 반영했는지.

    두 번째 호출이 첫 호출의 저장 뒤에 읽었을 때만 참이 된다. 두 호출이 같은
    값을 읽고 각자 저장하는 경우에는 어차피 같은 결과가 남아 문제가 없다.
    """
    last = state.get('lastEvent')
    if not isinstance(last, dict) or last.get('key') != key:
        return False
    at = parse_stamp(last.get('at'))
    if at is None:
        return False
    return (datetime.now(at.tzinfo) - at).total_seconds() < REPEAT_SECONDS


def last_render_age(state):
    """이 세션의 마지막 렌더 이후 지난 초. 알 수 없으면 None."""
    summary = state.get('summary')
    stamp = summary.get('renderedAt') if isinstance(summary, dict) else None
    at = parse_stamp(stamp)
    if at is not None:
        return (datetime.now(at.tzinfo) - at).total_seconds()
    # 이 값이 없는 예전 상태 파일은 페이지 파일의 시각으로 판정한다.
    out = state.get('out')
    if isinstance(out, str):
        try:
            return time.time() - os.path.getmtime(out)
        except OSError:
            return None
    return None


def refresh(state, session_id, skip_recent=False):
    data, out = state.get('data'), state.get('out')
    if not isinstance(data, str) or not isinstance(out, str):
        return
    # 페이지가 없는 밴드·상태줄 세션도 같은 제한을 받는다. 기준은 페이지 파일 시각이
    # 아니라 요약의 마지막 렌더 시각이라, 쓸 페이지가 아직 없어도 도구 호출마다
    # 파이썬 프로세스를 하나씩 더 띄우지 않는다.
    if skip_recent:
        age = last_render_age(state)
        if age is not None and age < RENDER_SKIP_SECONDS:
            return
    try:
        subprocess.run(
            [sys.executable, RENDER, '--session', session_id, data, out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:
        pass


def compaction_note(state):
    data = state.get('data') or ''
    out = state.get('out') or ''
    return ("deadhd: this session's progress page data is %s (rendered to %s). "
            'Keep updating that JSON and rerunning render.py on it as steps change; '
            'do not start a new data file.' % (data, out))


def markdown_plain(line):
    """마크다운 표지를 걷어낸 한 줄."""
    line = HEADING.sub('', line)
    line = QUOTE.sub('', line)
    line = BULLET.sub('', line)
    line = MD_LINK.sub(r'\1', line)
    line = line.replace('**', '').replace('__', '').replace('`', '')
    return SPACES.sub(' ', line).strip()


def reply_tail(text):
    """마지막 응답의 끝부분.

    코드 블록과 빈 줄을 걷어낸 마지막 줄에서 표지를 지우고 끝 120자만 쓴다. 그래서
    모델이 질문을 응답의 마지막 줄에 두면 띠와 허브에 그대로 드러난다.
    """
    if not isinstance(text, str):
        return None
    kept = []
    fenced = False
    for raw in text.splitlines():
        line = raw.strip()
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced or not line:
            continue
        kept.append(line)
    if not kept:
        return None
    line = markdown_plain(kept[-1])
    if len(line) > REPLY_TAIL_CHARS:
        tail = line[-REPLY_TAIL_CHARS:]
        # 잘린 자리가 낱말 중간이면 읽기 어렵다. 앞 20자 안의 첫 공백 뒤부터 쓴다.
        gap = tail[:20].find(' ')
        if gap >= 0:
            tail = tail[gap + 1:]
        line = '…' + tail
    return line or None


def apply_event(state, payload):
    """이벤트를 상태에 반영한다. 무시할 이벤트면 None, 아니면 (렌더 건너뜀, 추가 컨텍스트)."""
    event = payload.get('hook_event_name')
    now = now_iso()
    if event == 'Notification':
        kind = payload.get('notification_type')
        if kind == 'permission_prompt':
            state['status'] = 'waiting_permission'
            state['since'] = now
            message = payload.get('message')
            state['message'] = message if isinstance(message, str) else None
        elif kind == 'idle_prompt':
            if state.get('status') != 'idle':
                state['since'] = now
            state['status'] = 'idle'
            state['message'] = None
        else:
            return None
        return (False, None)
    if event == 'UserPromptSubmit':
        state['status'] = 'working'
        state['since'] = now
        state['message'] = None
        # pop 으로 지운다. 이 키가 없던 상태 파일에 새 키를 만들지 않기 위해서다.
        state.pop('replyTail', None)
        return (False, None)
    if event == 'PostToolUse':
        name = payload.get('tool_name')
        duration = payload.get('duration_ms')
        state['lastTool'] = {
            'name': name if isinstance(name, str) else '',
            'at': now,
            'durationMs': int(duration) if isinstance(duration, (int, float))
            and not isinstance(duration, bool) else None,
        }
        if state.get('status') != 'working':
            state['status'] = 'working'
            state['since'] = now
        # 다시 도구를 쓰기 시작한 세션은 지난 응답을 기다리는 게 아니다.
        state.pop('replyTail', None)
        return (True, None)
    if event == 'Stop':
        state['status'] = 'idle'
        state['since'] = now
        state['message'] = None
        state['backgroundTasks'] = background_tasks(payload)
        state['replyTail'] = reply_tail(payload.get('last_assistant_message'))
        return (False, None)
    if event == 'SessionStart':
        if payload.get('source') != 'compact':
            return None
        compactions = state.get('compactions')
        if not isinstance(compactions, dict):
            compactions = {'count': 0, 'lastAt': None}
            state['compactions'] = compactions
        compactions['count'] = int(compactions.get('count') or 0) + 1
        compactions['lastAt'] = now
        if isinstance(state.get('offAt'), str):
            # 꺼진 세션에 갱신 지시를 다시 넣으면 모델이 데이터를 다시 써 off 가 풀린다.
            return (False, None)
        return (False, compaction_note(state))
    if event == 'SessionEnd':
        state['status'] = 'ended'
        state['since'] = now
        return (False, None)
    return None


def turn_off(argv):
    """`state.py --off [--session <id>]`: 이 세션의 갱신을 꺼진 것으로 기록한다.

    `offAt` 은 `status` 밖의 최상위 필드라, 뒤이어 오는 훅 이벤트의 `apply_event` 가
    `status` 를 덮어써도 남는다. 그 상태로 페이지·요약·허브를 다시 그린다.
    """
    rest = argv[2:]
    session_id = None
    if rest[:1] == ['--session']:
        if len(rest) < 2:
            sys.stderr.write('state.py: 사용법: state.py --off [--session <id>]\n')
            return 1
        session_id = rest[1]
        rest = rest[2:]
    if rest:
        sys.stderr.write('state.py: 사용법: state.py --off [--session <id>]\n')
        return 1
    if session_id is None:
        session_id = os.environ.get('CLAUDE_CODE_SESSION_ID')
    if not valid_session_id(session_id):
        sys.stderr.write('state.py: 세션 id 가 없어 끌 수 없다\n')
        return 1

    state = load_state(session_id)
    if not state:
        sys.stdout.write('off: none\n')
        return 0
    if not isinstance(state.get('offAt'), str) or not state['offAt']:
        state['offAt'] = now_iso_ms()
    save_state(session_id, state)
    refresh(state, session_id)
    sys.stdout.write('off: ' + session_id + '\n')
    return 0


def main():
    if sys.argv[1:2] == ['--off']:
        return turn_off(sys.argv)
    payload = read_payload()
    if payload is None:
        return 0
    session_id = payload.get('session_id')
    if not valid_session_id(session_id):
        return 0

    drop_stale_states(session_id)
    state = load_state(session_id)
    if not state:
        return 0

    key = event_key(payload)
    if repeated_event(state, key):
        return 0

    outcome = apply_event(state, payload)
    if outcome is None:
        return 0
    skip_recent, context = outcome

    # 이 세션은 훅이 돌고 있다. render.py 는 이 표시가 있을 때만 상태 띠를 붙인다.
    state['hooked'] = True
    state['sessionId'] = session_id
    state['lastEvent'] = {'key': key, 'at': now_iso()}
    state['updatedAt'] = state['lastEvent']['at']
    save_state(session_id, state)
    refresh(state, session_id, skip_recent=skip_recent)

    if context:
        note = {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': context}}
        sys.stdout.write(json.dumps(note, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        # 훅 경로는 어떤 실패에도 조용히 0 으로 끝나야 한다. --off 는 사람이 부른
        # 명령이라 실패를 삼키면 껐는지 알 수 없으므로 이유를 내고 1 로 끝낸다.
        if sys.argv[1:2] == ['--off']:
            sys.stderr.write('state.py: 끄지 못했다: %s\n' % e)
            sys.exit(1)
        sys.exit(0)
