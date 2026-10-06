#!/usr/bin/env python3
"""Claude Code 훅의 stdin JSON 을 세션 상태 파일로 옮기고 페이지를 다시 렌더한다."""
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
SESSION_ID = re.compile(r'[A-Za-z0-9._-]{1,128}')


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


def refresh(state, session_id, skip_recent=False):
    data, out = state.get('data'), state.get('out')
    if not isinstance(data, str) or not isinstance(out, str):
        return
    if skip_recent:
        try:
            if time.time() - os.path.getmtime(out) < RENDER_SKIP_SECONDS:
                return
        except OSError:
            pass
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
        return (True, None)
    if event == 'Stop':
        state['status'] = 'idle'
        state['since'] = now
        state['message'] = None
        state['backgroundTasks'] = background_tasks(payload)
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
        return (False, compaction_note(state))
    if event == 'SessionEnd':
        state['status'] = 'ended'
        state['since'] = now
        return (False, None)
    return None


def main():
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

    outcome = apply_event(state, payload)
    if outcome is None:
        return 0
    skip_recent, context = outcome

    state['sessionId'] = session_id
    state['updatedAt'] = now_iso()
    save_state(session_id, state)
    refresh(state, session_id, skip_recent=skip_recent)

    if context:
        note = {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': context}}
        sys.stdout.write(json.dumps(note, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
