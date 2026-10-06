#!/usr/bin/env python3
"""progress 데이터 JSON 을 template.html 에 넣어 자체 완결 HTML 한 장으로 렌더한다."""
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'template.html')
STATES = ('done', 'now', 'side', 'left', 'blocked')
STATE_SET = frozenset(STATES)
LANGS = ('ko', 'en')
HTML_OPEN = '<html lang="ko">'
# 이보다 큰 estimate 는 합산 시 timedelta 가 넘친다 (525600분 = 365일).
MAX_ESTIMATE_MINUTES = 525600

# 같은 디렉터리의 config.py 를 읽으려면 HERE 가 먼저 있어야 한다.
sys.path.insert(0, HERE)
# 스킬 폴더는 Orca 공유 등으로 통째로 게시되므로 __pycache__ 를 남기지 않는다.
sys.dont_write_bytecode = True
import config
import state

THEMES = config.ALLOWED['theme']
FONTS = config.ALLOWED['font']
USAGE = '사용법: render.py [--theme %s] [--font %s] [--session <id>] <data.json> <out.html>' % (
    '|'.join(THEMES), '|'.join(FONTS))


def die(msg):
    sys.stderr.write('render.py: ' + msg + '\n')
    sys.exit(1)


def is_http_url(value):
    return isinstance(value, str) and value.lower().startswith(('http://', 'https://'))


def check_hrefs(problems, where, entries):
    if not isinstance(entries, list):
        return
    for j, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get('href') is not None and not is_http_url(entry['href']):
            problems.append('%s[%d].href 가 http(s) URL 이 아니다' % (where, j))


def parse_when(value):
    if not isinstance(value, str):
        return None
    text = value
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def pending_minutes(items):
    pending = []
    for it in items:
        item_state = it.get('state')
        if item_state == 'blocked':
            return None
        if item_state not in ('now', 'left'):
            continue
        estimate = it.get('estimate')
        if isinstance(estimate, bool) or not isinstance(estimate, (int, float)):
            return None
        pending.append(estimate)
    return sum(pending) if pending else None


def compute_eta(items, now):
    total = pending_minutes(items)
    return None if total is None else now + timedelta(minutes=total)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def history_path():
    override = os.environ.get('DEADHD_HISTORY')
    if override:
        return override
    return os.path.join(os.path.dirname(config.config_path()), 'history.jsonl')


def read_history(path):
    entries = []
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return entries
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            entries.append(row)
    return entries


def calibration(entries):
    estimates, actuals = [], []
    for row in entries[-30:]:
        est, actual = row.get('est'), row.get('actual')
        if not is_number(est) or not is_number(actual):
            continue
        estimates.append(est)
        actuals.append(actual)
    if len(estimates) < 3:
        return None
    total = sum(estimates)
    if total <= 0:
        return None
    factor = max(0.5, min(5.0, sum(actuals) / total))
    return {'factor': round(factor, 2), 'samples': len(estimates)}


def record_estimates(ledger, items, at):
    for it in items:
        iid = it.get('id')
        if not isinstance(iid, str) or not iid or iid in ledger:
            continue
        if it.get('state') not in ('now', 'left', 'side'):
            continue
        estimate = it.get('estimate')
        if not is_number(estimate):
            continue
        ledger[iid] = {'est': estimate, 'firstSeenAt': at, 'recorded': False}


def record_history(ledger, items, path, session_id, at):
    for it in items:
        iid = it.get('id')
        if not isinstance(iid, str) or it.get('state') != 'done':
            continue
        entry = ledger.get(iid)
        if not isinstance(entry, dict) or entry.get('recorded'):
            continue
        started, finished = parse_when(it.get('startedAt')), parse_when(it.get('doneAt'))
        if started is None or finished is None:
            continue
        actual = round((finished - started).total_seconds() / 60, 1)
        if actual <= 0:
            continue
        row = {'at': at, 'session': session_id, 'item': iid, 'est': entry.get('est'), 'actual': actual}
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        except OSError:
            continue
        entry['recorded'] = True


def calibrate(session_state, items, session_id, at):
    ledger = session_state.get('estimates')
    if not isinstance(ledger, dict):
        ledger = {}
        session_state['estimates'] = ledger
    record_estimates(ledger, items, at)
    record_history(ledger, items, history_path(), session_id, at)


def live_payload(session_state, at):
    if not session_state.get('status'):
        session_state['status'] = 'working'
    if not session_state.get('since'):
        session_state['since'] = at
    last_tool = session_state.get('lastTool')
    background = session_state.get('backgroundTasks')
    compactions = session_state.get('compactions')
    if not isinstance(compactions, dict):
        compactions = {}
    count = compactions.get('count')
    if not isinstance(count, int) or isinstance(count, bool):
        count = 0
    return {
        'status': session_state['status'],
        'since': session_state['since'],
        'message': session_state.get('message'),
        'lastTool': last_tool if isinstance(last_tool, dict) else None,
        'backgroundTasks': background if isinstance(background, list) else [],
        'compactions': {'count': count, 'lastAt': compactions.get('lastAt')},
    }


def current_time():
    raw = os.environ.get('DEADHD_NOW')
    if raw:
        parsed = parse_when(raw)
        if parsed is None:
            die('DEADHD_NOW 가 시차가 있는 ISO 8601 시각이 아니다: %s' % raw)
        return parsed
    return datetime.now().astimezone()


def validate(data):
    problems = []
    if not isinstance(data, dict):
        die('데이터 최상위가 객체가 아니다')

    if not isinstance(data.get('title'), str):
        problems.append('title 이 문자열이 아니다')

    lang = data.get('lang')
    if lang is not None and lang not in LANGS:
        problems.append('lang 이 %s 중 하나가 아니다 (값: %r)' % ('/'.join(LANGS), lang))

    for field in ('goal', 'doneWhen'):
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            problems.append(field + ' 이 문자열이 아니다')

    key_href = data.get('keyHref')
    if key_href is not None and not is_http_url(key_href):
        problems.append('keyHref 가 http(s) URL 이 아니다')

    links = data.get('links')
    if links is not None:
        if not isinstance(links, dict):
            problems.append('links 가 객체가 아니다')
        else:
            for k, v in links.items():
                if not isinstance(k, str) or not k:
                    problems.append('links 의 키가 비어 있지 않은 문자열이 아니다')
                if not is_http_url(v):
                    problems.append('links[%s] 가 http(s) URL 이 아니다' % k)

    meta = data.get('meta')
    if meta is not None:
        if not isinstance(meta, list):
            problems.append('meta 가 배열이 아니다')
        else:
            for j, m in enumerate(meta):
                where = 'meta[%d]' % j
                if isinstance(m, str):
                    continue
                if not isinstance(m, dict):
                    problems.append(where + ' 가 문자열 또는 객체가 아니다')
                    continue
                if not isinstance(m.get('text'), str):
                    problems.append(where + '.text 가 문자열이 아니다')
                href = m.get('href')
                if href is not None and not is_http_url(href):
                    problems.append(where + '.href 가 http(s) URL 이 아니다')

    items = data.get('items')
    if not isinstance(items, list) or not items:
        problems.append('items 가 비어 있지 않은 배열이 아니다')
        items = []

    ids = []
    now_count = 0
    for i, it in enumerate(items):
        where = 'items[%d]' % i
        if not isinstance(it, dict):
            problems.append(where + ' 가 객체가 아니다')
            continue
        iid = it.get('id')
        if not isinstance(iid, str) or not iid:
            problems.append(where + '.id 가 비어 있지 않은 문자열이 아니다')
        else:
            ids.append(iid)
        if not isinstance(it.get('label'), str):
            problems.append(where + '.label 이 문자열이 아니다')
        state = it.get('state')
        if state not in STATE_SET:
            problems.append('%s.state 가 %s 중 하나가 아니다 (값: %r)' % (where, '/'.join(STATES), state))
        if state == 'now':
            now_count += 1
        for field in ('startedAt', 'doneAt'):
            if it.get(field) is not None and parse_when(it[field]) is None:
                problems.append('%s.%s 이 시차가 있는 ISO 8601 시각이 아니다' % (where, field))
        started, finished = parse_when(it.get('startedAt')), parse_when(it.get('doneAt'))
        if started is not None and finished is not None and finished < started:
            problems.append('%s 의 doneAt 이 startedAt 보다 앞선다' % where)
        estimate = it.get('estimate')
        if estimate is not None and (
            isinstance(estimate, bool)
            or not isinstance(estimate, (int, float))
            or estimate <= 0
            or estimate > MAX_ESTIMATE_MINUTES
            or not math.isfinite(estimate)
        ):
            problems.append('%s.estimate 가 0 보다 큰 수가 아니다' % where)
        check_hrefs(problems, where + '.evidence', it.get('evidence'))
        check_hrefs(problems, where + '.substeps', it.get('substeps'))

    duplicated = sorted({x for x in ids if ids.count(x) > 1})
    if duplicated:
        problems.append('id 가 중복된다: ' + ', '.join(duplicated))
    if now_count > 1:
        problems.append('now 상태 항목이 %d개다 (최대 1개)' % now_count)

    edges = data.get('edges')
    if edges is not None:
        if not isinstance(edges, list):
            problems.append('edges 가 배열이 아니다')
        else:
            known = set(ids)
            for j, e in enumerate(edges):
                if not isinstance(e, list) or len(e) != 2 or not all(isinstance(x, str) for x in e):
                    problems.append('edges[%d] 가 [id, id] 형태가 아니다' % j)
                    continue
                for x in e:
                    if x not in known:
                        problems.append('edges[%d] 가 없는 id 를 가리킨다: %s' % (j, x))

    changes = data.get('changes')
    if isinstance(changes, list):
        for j, c in enumerate(changes):
            if isinstance(c, dict):
                check_hrefs(problems, 'changes[%d].evidence' % j, c.get('evidence'))

    if problems:
        die('\n'.join(problems))


def preserved_title(out_path):
    if not os.path.exists(out_path):
        return None
    try:
        with open(out_path, encoding='utf-8') as f:
            prev = f.read()
    except OSError:
        return None
    m = re.search(r'<title>(.*?)</title>', prev, re.S)
    return m.group(1) if m else None


def main(argv):
    theme = None
    font = None
    session = None
    rest = argv[1:]
    while rest[:1] in (['--theme'], ['--font'], ['--session']):
        flag = rest[0]
        if len(rest) < 2:
            die(USAGE)
        if flag == '--theme':
            if theme is not None:
                die(USAGE)
            theme = rest[1]
        elif flag == '--font':
            if font is not None:
                die(USAGE)
            font = rest[1]
        else:
            if session is not None:
                die(USAGE)
            session = rest[1]
        rest = rest[2:]
    if theme is not None and theme not in THEMES:
        die('알 수 없는 테마: %s (%s 중 하나)' % (theme, '/'.join(THEMES)))
    if font is not None and font not in FONTS:
        die('알 수 없는 글꼴: %s (%s 중 하나)' % (font, '/'.join(FONTS)))
    if len(rest) != 2:
        die(USAGE)
    if theme is None:
        theme = config.get_value('theme') or 'system'
    if font is None:
        font = config.get_value('font') or 'default'
    if session is None:
        session = os.environ.get('CLAUDE_CODE_SESSION_ID') or None
    if session is not None and not state.valid_session_id(session):
        die('세션 id 가 올바르지 않다: %r' % session)
    data_path, out_path = rest

    try:
        with open(data_path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        die('데이터를 읽지 못했다: %s' % e)

    validate(data)

    try:
        with open(TEMPLATE, encoding='utf-8') as f:
            tpl = f.read()
    except OSError as e:
        die('템플릿을 읽지 못했다: %s' % e)

    lang = data.get('lang') if data.get('lang') in LANGS else 'ko'
    if tpl.count(HTML_OPEN) != 1:
        die('템플릿에 %s 가 정확히 하나 있지 않다' % HTML_OPEN)
    html_open = '<html lang="%s"' % lang
    if theme != 'system':
        html_open += ' data-theme="%s"' % theme
    if font != 'default':
        html_open += ' data-font="%s"' % font
    html_open += '>'
    tpl = tpl.replace(HTML_OPEN, html_open)

    key = data.get('key')
    has_key = isinstance(key, str) and bool(key)
    if lang == 'en':
        title = escape((key + ' Progress') if has_key else 'Progress')
    else:
        title = escape((key + ' 진행 상황') if has_key else '진행 상황')
    prev_title = preserved_title(out_path)
    if prev_title is not None:
        title = prev_title

    now = current_time()
    now_text = now.isoformat(timespec='seconds')
    payload_data = dict(data)
    payload_data['renderedAt'] = now_text
    items = payload_data['items']
    eta = compute_eta(items, now)
    if eta is None:
        payload_data.pop('eta', None)
    else:
        payload_data['eta'] = eta.isoformat(timespec='seconds')
    total_minutes = pending_minutes(items)

    session_state = None
    if session:
        session_state = state.load_state(session)
        session_state['sessionId'] = session
        session_state['data'] = os.path.abspath(data_path)
        session_state['out'] = os.path.abspath(out_path)
        session_state['cwd'] = os.getcwd()
        session_state.setdefault('message', None)
        session_state.setdefault('lastTool', None)
        session_state.setdefault('backgroundTasks', [])
        session_state.setdefault('compactions', {'count': 0, 'lastAt': None})
        calibrate(session_state, items, session, now_text)

    factor = calibration(read_history(history_path()))
    if factor is not None and total_minutes is not None:
        payload_data['etaCalibrated'] = (
            now + timedelta(minutes=factor['factor'] * total_minutes)).isoformat(timespec='seconds')
        payload_data['calibration'] = factor

    if session_state is not None:
        payload_data['live'] = live_payload(session_state, now_text)

    payload = json.dumps(payload_data, ensure_ascii=False)
    # script 태그가 데이터 안의 문자열로 조기에 닫히지 않게 한다.
    payload = payload.replace('</', '<\\/').replace('<!--', '<\\!--')

    out = tpl.replace('__PROGRESS_TITLE__', title).replace('__PROGRESS_DATA__', payload)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix='.progress-', suffix='.html')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(out)
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    if session_state is not None:
        # 상태 파일을 못 써도 페이지는 이미 나왔다.
        try:
            session_state['updatedAt'] = now_text
            state.save_state(session, session_state)
        except Exception:
            pass

    print('rendered: ' + out_path)


if __name__ == '__main__':
    main(sys.argv)
