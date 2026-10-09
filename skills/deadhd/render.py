#!/usr/bin/env python3
"""progress 데이터 JSON 을 template.html 에 넣어 자체 완결 HTML 한 장으로 렌더한다."""
import json
import math
import os
import pathlib
import re
import sys
import tempfile
from datetime import datetime, timedelta
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'template.html')
THEMES_CSS = os.path.join(HERE, 'themes.css')
STATES = ('done', 'now', 'side', 'left', 'blocked')
STATE_SET = frozenset(STATES)
# 레인 보드의 상태. items 의 state 와 달리 side 가 없고 waiting(선행 대기)이 있으며 now 는 개수 제한이 없다.
BOARD_STATES = ('done', 'now', 'waiting', 'left', 'blocked')
BOARD_STATE_SET = frozenset(BOARD_STATES)
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
VIEWS = config.ALLOWED['view']
DEFAULT_VIEW = 'html'
USAGE = ('사용법: render.py [--theme %s] [--font %s] [--view %s] [--page] [--session <id>] '
         '<data.json> <out.html>') % ('|'.join(THEMES), '|'.join(FONTS), '|'.join(VIEWS))


def die(msg):
    sys.stderr.write('render.py: ' + msg + '\n')
    sys.exit(1)


def script_json(obj):
    payload = json.dumps(obj, ensure_ascii=False)
    # script 태그가 데이터 안의 문자열로 조기에 닫히지 않게 한다.
    return payload.replace('</', '<\\/').replace('<!--', '<\\!--')


def theme_css():
    with open(THEMES_CSS, encoding='utf-8') as f:
        return f.read()


def file_url(path):
    return pathlib.Path(path).as_uri()


def page_url(path):
    """서빙 규칙에 맞는 파일은 로컬 서버 주소로, 아니면 file:// 로."""
    try:
        import serve
    except Exception:
        return file_url(path)
    url = serve.http_url(path)
    return url if url is not None else file_url(path)


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


def is_index(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def as_index(value):
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    return value if is_index(value) else None


def as_col(value):
    """col 로 그려 온 숫자 문자열도 받는다. 템플릿이 산술에서 숫자로 바꿨다."""
    if isinstance(value, str):
        return int(value) if value.isdigit() and value.isascii() else None
    return as_index(value)


def lane_name(lane):
    """lanes 원소를 템플릿이 레인 이름으로 쓰는 문자열로 바꾼다. 숫자는 그대로 찍혀 왔다."""
    if isinstance(lane, dict):
        return lane['label']
    if isinstance(lane, str):
        return lane
    if isinstance(lane, float) and lane.is_integer():
        return str(int(lane))
    return '' if lane is None else str(lane)


def bad_estimate(value):
    return (not is_number(value) or value <= 0 or value > MAX_ESTIMATE_MINUTES)


def validate_board(problems, board):
    stages = board.get('stages')
    if stages is not None:
        if (not isinstance(stages, list) or not stages
                or not all(isinstance(s, str) and s for s in stages)):
            problems.append('board.stages 가 비어 있지 않은 문자열 배열이 아니다')
            stages = None
        elif len(set(stages)) != len(stages):
            problems.append('board.stages 에 중복된 값이 있다')

    lanes = board.get('lanes')
    if not isinstance(lanes, list) or not lanes:
        problems.append('board.lanes 가 비어 있지 않은 배열이 아니다')
        return

    ids = []
    for i, lane in enumerate(lanes):
        where = 'board.lanes[%d]' % i
        if not isinstance(lane, dict):
            problems.append(where + ' 가 객체가 아니다')
            continue
        lid = lane.get('id')
        if not isinstance(lid, str) or not lid:
            problems.append(where + '.id 가 비어 있지 않은 문자열이 아니다')
        else:
            ids.append(lid)
        if not isinstance(lane.get('label'), str):
            problems.append(where + '.label 이 문자열이 아니다')
        state = lane.get('state')
        if state not in BOARD_STATE_SET:
            problems.append('%s.state 가 %s 중 하나가 아니다 (값: %r)'
                            % (where, '/'.join(BOARD_STATES), state))
        stage = lane.get('stage')
        if stage is not None:
            if not isinstance(stage, str):
                problems.append(where + '.stage 가 문자열이 아니다')
            elif stages is not None and stage not in stages:
                problems.append('%s.stage 가 board.stages 에 없는 값이다 (값: %r)' % (where, stage))
        for field in ('startedAt', 'doneAt', 'lastSignal'):
            if lane.get(field) is not None and parse_when(lane[field]) is None:
                problems.append('%s.%s 이 시차가 있는 ISO 8601 시각이 아니다' % (where, field))
        started, finished = parse_when(lane.get('startedAt')), parse_when(lane.get('doneAt'))
        if started is not None and finished is not None and finished < started:
            problems.append('%s 의 doneAt 이 startedAt 보다 앞선다' % where)
        stall = lane.get('stallAfter')
        if stall is not None and (not is_number(stall) or stall <= 0):
            problems.append('%s.stallAfter 가 0 보다 큰 수가 아니다' % where)
        estimate = lane.get('estimate')
        if estimate is not None and bad_estimate(estimate):
            problems.append('%s.estimate 가 0 보다 큰 수가 아니다' % where)
        for field in ('worker', 'note', 'body'):
            if lane.get(field) is not None and not isinstance(lane[field], str):
                problems.append('%s.%s 가 문자열이 아니다' % (where, field))
        check_hrefs(problems, where + '.evidence', lane.get('evidence'))
        log = lane.get('log')
        if log is None:
            continue
        if not isinstance(log, list):
            problems.append(where + '.log 가 배열이 아니다')
            continue
        for j, entry in enumerate(log):
            log_where = '%s.log[%d]' % (where, j)
            if not isinstance(entry, dict):
                problems.append(log_where + ' 가 객체가 아니다')
                continue
            if entry.get('at') is not None and parse_when(entry['at']) is None:
                problems.append(log_where + '.at 이 시차가 있는 ISO 8601 시각이 아니다')
            if not isinstance(entry.get('text'), str):
                problems.append(log_where + '.text 가 문자열이 아니다')

    duplicated = sorted({x for x in ids if ids.count(x) > 1})
    if duplicated:
        problems.append('board.lanes 의 id 가 중복된다: ' + ', '.join(duplicated))
    known = set(ids)
    for i, lane in enumerate(lanes):
        if not isinstance(lane, dict) or lane.get('dependsOn') is None:
            continue
        deps = lane['dependsOn']
        where = 'board.lanes[%d].dependsOn' % i
        if not isinstance(deps, list):
            problems.append(where + ' 가 배열이 아니다')
            continue
        for x in deps:
            if not isinstance(x, str) or x not in known:
                problems.append(where + ' 가 없는 lane id 를 가리킨다: %r' % (x,))


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


def session_summary(data, items, lang, payload, at, hooked):
    counts = dict.fromkeys(STATES, 0)
    states = []
    now_label = None
    blocked_label = None
    for it in items:
        state = it.get('state')
        states.append(state)
        if state in counts:
            counts[state] += 1
        label = it.get('label')
        if state == 'now' and now_label is None and isinstance(label, str):
            now_label = label
        if state == 'blocked' and blocked_label is None and isinstance(label, str):
            blocked_label = label
    key, key_href = data.get('key'), data.get('keyHref')
    return {
        'title': data.get('title'),
        'key': key if isinstance(key, str) and key else None,
        'keyHref': key_href if isinstance(key_href, str) and key_href else None,
        'lang': lang,
        'updated': data.get('updated') if isinstance(data.get('updated'), str) else None,
        'counts': counts,
        'total': len(items),
        'states': states,
        'nowLabel': now_label if now_label is not None else blocked_label,
        'eta': payload.get('eta'),
        'etaCalibrated': payload.get('etaCalibrated'),
        'renderedAt': at,
        # mod 의 「N분 전」 은 훅이 도구 호출마다 다시 쓰는 상태 파일 시각이 아니라
        # 스킬이 데이터 JSON 을 마지막으로 쓴 시각을 기준으로 한다.
        'dataAt': payload.get('dataAt') if isinstance(payload.get('dataAt'), str) else None,
        'hooked': bool(hooked),
        'allDone': bool(items) and counts['done'] == len(items),
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

    raw_lanes = data.get('lanes')
    lane_names, lane_id_list = [], []
    if raw_lanes is not None:
        if not isinstance(raw_lanes, list):
            problems.append('lanes 가 배열이 아니다')
        else:
            for i, lane in enumerate(raw_lanes):
                where = 'lanes[%d]' % i
                if isinstance(lane, str):
                    lane_names.append(lane)
                    continue
                if lane is None or is_number(lane):
                    lane_names.append(lane_name(lane))
                    continue
                if not isinstance(lane, dict):
                    problems.append(where + ' 가 문자열·숫자·객체가 아니다')
                    continue
                label = lane.get('label')
                if not isinstance(label, str):
                    problems.append(where + '.label 이 문자열이 아니다')
                else:
                    lane_names.append(label)
                lid = lane.get('id')
                if lid is None:
                    continue
                if not isinstance(lid, str) or not lid:
                    problems.append(where + '.id 가 비어 있지 않은 문자열이 아니다')
                else:
                    lane_id_list.append(lid)
            duplicated = sorted({x for x in lane_id_list if lane_id_list.count(x) > 1})
            if duplicated:
                problems.append('lanes 의 id 가 중복된다: ' + ', '.join(duplicated))
    lane_ids = set(lane_id_list)

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
        lane = it.get('lane')
        if isinstance(lane, str):
            if raw_lanes is None:
                problems.append(where + '.lane 이 문자열인데 lanes 가 없다')
            elif lane not in lane_ids and lane not in lane_names:
                problems.append('%s.lane 이 없는 레인을 가리킨다 (값: %r)' % (where, lane))
        elif lane is not None:
            # lanes 보다 큰 정수 lane 은 이름 없는 줄로 그려 왔으므로 막지 않는다.
            if as_index(lane) is None:
                problems.append('%s.lane 이 0 이상의 정수가 아니다 (값: %r)' % (where, lane))
        col = it.get('col')
        if col is not None and as_col(col) is None:
            problems.append('%s.col 이 0 이상의 정수가 아니다 (값: %r)' % (where, col))
        for field in ('startedAt', 'doneAt'):
            if it.get(field) is not None and parse_when(it[field]) is None:
                problems.append('%s.%s 이 시차가 있는 ISO 8601 시각이 아니다' % (where, field))
        started, finished = parse_when(it.get('startedAt')), parse_when(it.get('doneAt'))
        if started is not None and finished is not None and finished < started:
            problems.append('%s 의 doneAt 이 startedAt 보다 앞선다' % where)
        estimate = it.get('estimate')
        if estimate is not None and bad_estimate(estimate):
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

    board = data.get('board')
    if board is not None:
        if not isinstance(board, dict):
            problems.append('board 가 객체가 아니다')
        else:
            validate_board(problems, board)

    changes = data.get('changes')
    if isinstance(changes, list):
        for j, c in enumerate(changes):
            if isinstance(c, dict):
                check_hrefs(problems, 'changes[%d].evidence' % j, c.get('evidence'))

    if problems:
        die('\n'.join(problems))


def normalize_lanes(payload):
    """lanes 원소와 item 의 lane·col 을 템플릿이 읽는 이름 문자열·정수로 바꾼다.

    validate() 를 통과한 뒤에만 부른다. 문자열 lane 은 반드시 어떤 레인을 가리킨다.
    """
    lanes = payload.get('lanes')
    names, by_id = [], {}
    if isinstance(lanes, list):
        names = [lane_name(lane) for lane in lanes]
        by_id = {lane['id']: i for i, lane in enumerate(lanes)
                 if isinstance(lane, dict) and isinstance(lane.get('id'), str) and lane['id']}
        payload['lanes'] = names
    items = []
    for it in payload['items']:
        lane, col = it.get('lane'), it.get('col')
        if not (isinstance(lane, (str, float)) or isinstance(col, (str, float))):
            items.append(it)
            continue
        it = dict(it)
        if isinstance(lane, str):
            it['lane'] = by_id[lane] if lane in by_id else names.index(lane)
        elif isinstance(lane, float):
            it['lane'] = int(lane)
        if isinstance(col, (str, float)):
            it['col'] = as_col(col)
        items.append(it)
    payload['items'] = items


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
    view = None
    page = False
    session = None
    rest = argv[1:]
    while rest[:1] in (['--theme'], ['--font'], ['--view'], ['--page'], ['--session']):
        flag = rest[0]
        if flag == '--page':
            if page:
                die(USAGE)
            page = True
            rest = rest[1:]
            continue
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
        elif flag == '--view':
            if view is not None:
                die(USAGE)
            view = rest[1]
        else:
            if session is not None:
                die(USAGE)
            session = rest[1]
        rest = rest[2:]
    if theme is not None and theme not in THEMES:
        die('알 수 없는 테마: %s (%s 중 하나)' % (theme, '/'.join(THEMES)))
    if font is not None and font not in FONTS:
        die('알 수 없는 글꼴: %s (%s 중 하나)' % (font, '/'.join(FONTS)))
    if view is not None and view not in VIEWS:
        die('알 수 없는 view: %s (%s 중 하나)' % (view, '/'.join(VIEWS)))
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

    # view 는 이번 실행의 인자, 이 세션에 이미 기록된 값, 설정, 기본값 순으로 정한다.
    # 훅의 재렌더와 mod 의 --page 는 --view 없이 돌므로 여기서 세션의 값이 유지되고,
    # 한 번 --view 로 바꾼 세션은 다음 렌더에서도 그 view 로 그린다.
    session_state = None
    stored_view = None
    if session:
        session_state = state.load_state(session)
        if session_state.get('view') in VIEWS:
            stored_view = session_state['view']
    if view is None:
        view = stored_view or config.get_value('view') or DEFAULT_VIEW

    try:
        with open(data_path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        die('데이터를 읽지 못했다: %s' % e)

    validate(data)

    lang = data.get('lang') if data.get('lang') in LANGS else 'ko'
    now = current_time()
    now_text = now.isoformat(timespec='seconds')
    # 예상 시각의 기준은 렌더 시각이 아니라 데이터가 마지막으로 쓰인 시각이다.
    # 훅이 데이터를 바꾸지 않은 채 페이지를 다시 렌더해도 예상 시각이 밀리지 않는다.
    data_at = now if os.environ.get('DEADHD_NOW') else datetime.fromtimestamp(os.path.getmtime(data_path)).astimezone()
    data_at_text = data_at.isoformat(timespec='seconds')
    payload_data = dict(data)
    normalize_lanes(payload_data)
    payload_data['renderedAt'] = now_text
    payload_data['dataAt'] = data_at_text
    items = payload_data['items']
    eta = compute_eta(items, data_at)
    if eta is None:
        payload_data.pop('eta', None)
    else:
        payload_data['eta'] = eta.isoformat(timespec='seconds')
    total_minutes = pending_minutes(items)

    if session_state is not None:
        session_state['sessionId'] = session
        session_state['data'] = os.path.abspath(data_path)
        session_state['out'] = os.path.abspath(out_path)
        session_state['cwd'] = os.getcwd()
        session_state.setdefault('message', None)
        session_state.setdefault('lastTool', None)
        session_state.setdefault('backgroundTasks', [])
        session_state.setdefault('compactions', {'count': 0, 'lastAt': None})
        session_state['view'] = view
        calibrate(session_state, items, session, now_text)

    # view 가 html 이 아니면 상태 요약만 갱신하고 HTML 은 쓰지 않는다. --page 로 한 번
    # 열거나 view 가 html 인 세션은 이후에도 계속 쓴다. 세션 id 가 없으면 어느 세션인지
    # 알 수 없어 예전처럼 항상 쓴다.
    write_page = page or view == 'html' or session_state is None or bool(session_state.get('pageOpened'))
    if page and session_state is not None:
        session_state['pageOpened'] = True

    factor = calibration(read_history(history_path()))
    if factor is not None and total_minutes is not None:
        payload_data['etaCalibrated'] = (
            data_at + timedelta(minutes=factor['factor'] * total_minutes)).isoformat(timespec='seconds')
        payload_data['calibration'] = factor

    if session_state is not None:
        live = live_payload(session_state, now_text)
        hooked = bool(session_state.get('hooked'))
        # 훅이 돌지 않은 설치에서는 띠를 붙이지 않는다. live 키 자체를 넣지 않는다.
        if hooked:
            payload_data['live'] = live
        # 허브는 상태 파일의 이 요약만 읽는다. 데이터 JSON 은 다시 읽지 않는다.
        session_state['summary'] = session_summary(data, items, lang, payload_data, now_text, hooked)

    # hub.py 가 없거나 못 읽어도 페이지는 나와야 한다. 그때는 허브 링크를 넣지 않는다.
    hub = None
    try:
        import hub
        payload_data['hubHref'] = page_url(hub.hub_path())
    except Exception:
        pass

    if write_page:
        try:
            with open(TEMPLATE, encoding='utf-8') as f:
                tpl = f.read()
        except OSError as e:
            die('템플릿을 읽지 못했다: %s' % e)

        if tpl.count(HTML_OPEN) != 1:
            die('템플릿에 %s 가 정확히 하나 있지 않다' % HTML_OPEN)
        html_open = '<html lang="%s"' % lang
        if theme != 'system':
            html_open += ' data-theme="%s"' % theme
        if font != 'default':
            html_open += ' data-font="%s"' % font
        html_open += '>'
        tpl = tpl.replace(HTML_OPEN, html_open)

        if tpl.count('__THEME_CSS__') != 1:
            die('템플릿에 __THEME_CSS__ 가 정확히 하나 있지 않다')
        try:
            css = theme_css()
        except OSError as e:
            die('테마 CSS 를 읽지 못했다: %s' % e)
        tpl = tpl.replace('__THEME_CSS__', css)

        key = data.get('key')
        has_key = isinstance(key, str) and bool(key)
        if lang == 'en':
            title = escape((key + ' Progress') if has_key else 'Progress')
        else:
            title = escape((key + ' 진행 상황') if has_key else '진행 상황')
        prev_title = preserved_title(out_path)
        if prev_title is not None:
            title = prev_title

        out = tpl.replace('__PROGRESS_TITLE__', title).replace(
            '__PROGRESS_DATA__', script_json(payload_data))

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

    # 허브를 못 써도 페이지는 이미 나왔다.
    if hub is not None:
        try:
            hub.write_hub(theme=theme, font=font, now=now)
        except Exception:
            pass

    if write_page:
        print('rendered: ' + out_path)
    else:
        print('skipped: view %s, HTML 페이지를 아직 열지 않았다' % view)


if __name__ == '__main__':
    main(sys.argv)
