#!/usr/bin/env python3
"""progress 데이터 JSON 을 template.html 에 넣어 자체 완결 HTML 한 장으로 렌더한다."""
import json
import os
import re
import sys
import tempfile
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'template.html')
STATES = ('done', 'now', 'side', 'left', 'blocked')
STATE_SET = frozenset(STATES)
THEMES = ('system', 'light', 'dark')
HTML_OPEN = '<html lang="ko">'
USAGE = '사용법: render.py [--theme system|light|dark] <data.json> <out.html>'

# 같은 디렉터리의 config.py 를 읽으려면 HERE 가 먼저 있어야 한다.
sys.path.insert(0, HERE)
import config


def die(msg):
    sys.stderr.write('render.py: ' + msg + '\n')
    sys.exit(1)


def validate(data):
    problems = []
    if not isinstance(data, dict):
        die('데이터 최상위가 객체가 아니다')

    if not isinstance(data.get('title'), str):
        problems.append('title 이 문자열이 아니다')

    for field in ('goal', 'doneWhen'):
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            problems.append(field + ' 이 문자열이 아니다')

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
    rest = argv[1:]
    if rest[:1] == ['--theme']:
        if len(rest) < 2:
            die(USAGE)
        theme, rest = rest[1], rest[2:]
    if theme is not None and theme not in THEMES:
        die('알 수 없는 테마: %s (system/light/dark 중 하나)' % theme)
    if len(rest) != 2:
        die(USAGE)
    if theme is None:
        theme = config.get_value('theme') or 'system'
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

    if theme != 'system':
        if tpl.count(HTML_OPEN) != 1:
            die('템플릿에 %s 가 정확히 하나 있지 않다' % HTML_OPEN)
        tpl = tpl.replace(HTML_OPEN, '<html lang="ko" data-theme="%s">' % theme)

    key = data.get('key')
    title = escape((key + ' 진행 상황') if isinstance(key, str) and key else '진행 상황')
    prev_title = preserved_title(out_path)
    if prev_title is not None:
        title = prev_title

    payload = json.dumps(data, ensure_ascii=False)
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

    print('rendered: ' + out_path)


if __name__ == '__main__':
    main(sys.argv)
