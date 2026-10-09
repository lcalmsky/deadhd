#!/usr/bin/env python3
"""밴드·상태줄 mod(register.tsx) 가 그리는 줄을 그대로 재현해 터미널 화면 그림 docs/band.png·docs/statusline.png 를 만든다. Chrome 헤드리스 실행 파일이 필요하다."""
import json
import math
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

from capture_themes import CASES, CHROME, HERE, REPO, chrome_args, chrome_shot, die, render_panel

CASE, THEME, SESSION = 'lanes-blocked', 'dark', 'demo-mods'
# 데모 데이터가 마지막으로 쓰인 시각. 다른 캡처 스크립트와 같은 시각을 쓴다.
NOW = CASES[CASE]
WAIT_MINUTES, STALE_MINUTES = 4, 2

FONT, LINE = 10, 14
PAD, GAP = 14, 16


# ── register.tsx 의 줄 만들기 ────────────────────────────────────────────────

STATUS_COLS = 240
BAR_CELLS = 6
SEP = ' · '
BAND_CMD = '/deadhd-band'
STATUS_CMD = '/deadhd-statusline'
OPEN_CMD = '/deadhd-open'

WORDS = {
    'ko': {
        'blocked': '막힘', 'left': '남음', 'allDone': '완료', 'next': '다음', 'eta': '예상',
        'background': '백그라운드', 'compacted': '압축', 'collapse': '접기', 'expand': '펼치기',
        'open': '열기', 'permission': '권한 승인 대기', 'input': '입력 대기',
    },
    'en': {
        'blocked': 'blocked', 'left': 'left', 'allDone': 'all done', 'next': 'next', 'eta': 'ETA',
        'background': 'background', 'compacted': 'compacted', 'collapse': 'Collapse',
        'expand': 'Expand', 'open': 'Open', 'permission': 'waiting for permission',
        'input': 'waiting for input',
    },
}

WIDE = ((0x1100, 0x115f), (0x2e80, 0xa4cf), (0xac00, 0xd7a3), (0xf900, 0xfaff),
        (0xfe30, 0xfe4f), (0xff00, 0xff60), (0xffe0, 0xffe6), (0x1f300, 0x1faff),
        (0x20000, 0x3fffd))
ZERO = ((0x0300, 0x036f), (0x200b, 0x200f), (0xfe00, 0xfe0f))


def within(code, ranges):
    return any(low <= code <= high for low, high in ranges)


def cell_width(text):
    return sum(0 if within(ord(c), ZERO) else 2 if within(ord(c), WIDE) else 1 for c in text)


def count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0
    return max(0, int(math.floor(value)))


def text(value, fallback):
    return value if isinstance(value, str) else fallback


def as_index(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return int(math.floor(value)) if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r'\d+', value):
        return int(value)
    return None


def cut(label, room):
    if cell_width(label) <= room:
        return label
    if room <= 1:
        return '…'
    kept, used = '', 0
    for code in label:
        wide = cell_width(code)
        if used + wide > room - 1:
            break
        kept += code
        used += wide
    return kept.rstrip() + '…'


def minutes_between(frm, now):
    if frm is None:
        return None
    try:
        at = datetime.fromisoformat(frm).timestamp() * 1000
    except ValueError:
        return None
    if now < at:
        return None
    return int(math.floor((now - at) / 60000))


def since(minutes, lang):
    return '%dm in' % minutes if lang == 'en' else '%d분째' % minutes


def ago(minutes, lang):
    return '%dm ago' % minutes if lang == 'en' else '%d분 전' % minutes


def clock_of(eta):
    match = re.search(r'T(\d{2}:\d{2})', eta or '')
    return match.group(1) if match else None


def status_label(status, lang):
    if status in ('', 'working', 'ended'):
        return None
    if status == 'waiting_permission':
        return WORDS[lang]['permission']
    if status == 'idle':
        return WORDS[lang]['input']
    return status


def bar_parts(done, total):
    cells = max(0, min(BAR_CELLS, int(math.floor(done / total * BAR_CELLS + 0.5))))
    parts = []
    if cells > 0:
        parts.append(('▓' * cells, 'success', False))
    if cells < BAR_CELLS:
        parts.append(('░' * (BAR_CELLS - cells), 'subtle', False))
    return parts


def step_mark(state, running):
    if state == 'side':
        return '◇', 'autoAccept', False
    return running, 'suggestion', True


def step_field(step, lang, now, running):
    mark, tone, bold = step_mark(step['state'], running)
    minutes = minutes_between(step['startedAt'], now)
    tail = '' if minutes is None else ' ' + since(minutes, lang)
    return ('current', [('%s %s%s' % (mark, step['label'], tail), tone, bold)])


def wait_field(state, now):
    if state['status'] not in ('waiting_permission', 'idle'):
        return None
    word = status_label(state['status'], state['lang']) or state['status']
    minutes = minutes_between(state['since'], now)
    tail = '' if minutes is None else ' ' + since(minutes, state['lang'])
    asking = state['status'] == 'waiting_permission'
    return ('wait', [('%s %s%s' % ('🔐' if asking else '⌨️', word, tail),
                      'warning' if asking else 'merged', True)])


def band_fields(state, now):
    words = WORDS[state['lang']]
    fields = [('name', [(BAND_CMD, 'claude', True)])]
    if state['total'] > 0:
        fields.append(('bar', bar_parts(state['done'], state['total']) + [
            (' ', 'plain', False),
            ('%d/%d' % (state['done'], state['total']), 'success', True)]))
    if state['current'] is not None:
        fields.append(step_field(state['current'], state['lang'], now, '▶'))
    if state['blocked'] > 0:
        fields.append(('stuck', [('%s %d' % (words['blocked'], state['blocked']), 'error', True)]))
    if state['left'] > 0:
        fields.append(('leftCount', [('%s %d' % (words['left'], state['left']), 'text', False)]))
    if state['allDone']:
        fields.append(('allDone', [(words['allDone'], 'success', True)]))
    return fields


def band_alert_fields(state, now):
    words = WORDS[state['lang']]
    fields = []
    if state['stuck'] is not None:
        stuck = state['stuck']
        note = stuck['label'] if stuck['sub'] == '' else '%s (%s)' % (stuck['label'], stuck['sub'])
        fields.append(('blocked', [('⛔ %s: ' % words['blocked'], 'error', True), (note, 'error', True)]))
    wait = wait_field(state, now)
    if wait is not None:
        fields.append(wait)
    return fields


def status_fields(state, now):
    words = WORDS[state['lang']]
    fields = [('name', [(STATUS_CMD, 'claude', True)])]
    if state['total'] > 0:
        fields.append(('count', [
            ('✅ %d/%d' % (state['done'], state['total']), 'success', True),
            (' ', 'plain', False)] + bar_parts(state['done'], state['total'])))
    heading = []
    if state['key'] is not None:
        heading.append((state['key'] if state['title'] == '' else state['key'] + ' ', 'permission', True))
    if state['title'] != '':
        heading.append((state['title'], 'text', False))
    if heading:
        fields.append(('title', heading))
    if state['current'] is not None:
        fields.append(step_field(state['current'], state['lang'], now, '▶️'))
    if state['next'] is not None:
        fields.append(('next', [('⏭ %s %s' % (words['next'], state['next']['label']), 'inactive', False)]))
    eta = clock_of(state['eta'])
    if eta is not None:
        fields.append(('eta', [('⏱ %s %s' % (words['eta'], eta), 'planMode', False)]))
    stale = minutes_between(state['updatedAt'], now)
    if stale is not None:
        fields.append(('ago', [update_piece(stale, state['lang'])]))
    if state['blocked'] > 0:
        parts = [('⛔ %s %d' % (words['blocked'], state['blocked']), 'error', True)]
        if state['stuck'] is not None:
            parts.append((': %s' % state['stuck']['label'], 'error', True))
        fields.append(('blocked', parts))
    if state['left'] > 0:
        fields.append(('left', [('⏳ %s %d' % (words['left'], state['left']), 'text', False)]))
    wait = wait_field(state, now)
    if wait is not None:
        fields.append(wait)
    if state['background'] > 0:
        fields.append(('background',
                       [('🧵 %s %d' % (words['background'], state['background']), 'ide', False)]))
    if state['compactions'] > 0:
        fields.append(('compacted',
                       [('🗜 %s %d' % (words['compacted'], state['compactions']), 'remember', False)]))
    fields.append(('openCmd', [('↗ %s' % OPEN_CMD, 'suggestion', False)]))
    return fields


def update_piece(minutes, lang):
    body = ago(minutes, lang)
    if minutes > 30:
        return '🛑 ' + body, 'error', False
    if minutes > 10:
        return '⚠️ ' + body, 'warning', False
    return '🔄 ' + body, 'subtle', False


def field_width(field):
    return sum(cell_width(part[0]) for part in field[1])


def line_width(fields):
    if not fields:
        return 0
    return sum(field_width(f) for f in fields) + (len(fields) - 1) * cell_width(SEP)


def cut_last(field, room):
    parts = field[1]
    if not parts:
        return
    last = parts[-1]
    fixed = sum(cell_width(part[0]) for part in parts[:-1])
    left = room - fixed
    if left <= 1:
        parts.pop()
        return
    parts[-1] = (cut(last[0], left), last[1], last[2])


def fit(fields, max_cols):
    def shrink(tag):
        field = next((f for f in fields if f[0] == tag), None)
        if field is not None:
            cut_last(field, max_cols - (line_width(fields) - field_width(field)))

    def drop(tag):
        at = next((i for i, f in enumerate(fields) if f[0] == tag), -1)
        if at >= 0:
            del fields[at]

    if line_width(fields) > max_cols:
        shrink('title')
    if line_width(fields) > max_cols:
        drop('next')
    if line_width(fields) > max_cols:
        shrink('blocked')
    if line_width(fields) > max_cols:
        drop('blocked')
    if line_width(fields) > max_cols:
        shrink('current')
    if line_width(fields) > max_cols:
        drop('current')
    if line_width(fields) > max_cols:
        drop('openCmd')
    return [f for f in fields if f[1]]


def flatten(fields):
    parts = []
    for index, field in enumerate(fields):
        if index > 0:
            parts.append((SEP, 'subtle', False))
        parts.extend(field[1])
    return parts


def band_line(state, now, max_cols):
    return [] if state is None else flatten(fit(band_fields(state, now), max_cols))


def band_alert_line(state, now, max_cols):
    return [] if state is None else flatten(fit(band_alert_fields(state, now), max_cols))


def status_line(state, now, max_cols):
    return [] if state is None else flatten(fit(status_fields(state, now), max_cols))


def folded_segments(state):
    parts = [(BAND_CMD, 'claude', True)]
    if state['total'] > 0:
        parts.append((' ', 'plain', False))
        parts.append(('✓ %d/%d' % (state['done'], state['total']), 'success', False))
    return parts


def segments_text(parts):
    return ''.join(part[0] for part in parts)


def format_line(state, now, max_cols):
    return '' if state is None else segments_text(status_line(state, now, max_cols))


def read_steps(data):
    if not isinstance(data, dict):
        return []
    raw = data.get('items')
    if not isinstance(raw, list):
        return []
    lanes = data.get('lanes') if isinstance(data.get('lanes'), list) else []

    def lane_of(value):
        direct = as_index(value)
        if direct is not None:
            return direct
        if isinstance(value, str):
            for at, lane in enumerate(lanes):
                if lane == value or (isinstance(lane, dict)
                                     and (lane.get('id') == value or lane.get('label') == value)):
                    return at
        return 0

    filled, steps = {}, []
    for index, item in enumerate(raw):
        source = item if isinstance(item, dict) else {}
        lane = lane_of(source.get('lane'))
        given = as_index(source.get('col'))
        col = filled.get(lane, 0) if given is None else given
        filled[lane] = col + 1
        steps.append(({
            'state': text(source.get('state'), ''),
            'label': text(source.get('label'), ''),
            'sub': text(source.get('sub'), ''),
            'startedAt': source.get('startedAt') if isinstance(source.get('startedAt'), str) else None,
            'lane': lane, 'col': col,
        }, index))
    steps.sort(key=lambda one: (one[0]['lane'], one[0]['col'], one[1]))
    return [step for step, _ in steps]


def next_step(steps, current):
    if current is None:
        first = 0
    else:
        first = steps.index(current) + 1 if current in steps else 0
    for at in range(max(0, first), len(steps)):
        if steps[at]['state'] == 'left':
            return steps[at]
    return None


def normalize(raw, data=None):
    if not isinstance(raw, dict):
        return None
    summary = raw.get('summary') if isinstance(raw.get('summary'), dict) else {}
    counts = summary.get('counts') if isinstance(summary.get('counts'), dict) else {}
    steps = read_steps(data)
    now_label = text(summary.get('nowLabel'), '')
    done, now = count(counts.get('done')), count(counts.get('now'))
    side, left = count(counts.get('side')), count(counts.get('left'))
    blocked = count(counts.get('blocked'))
    summary_step = None
    if not steps and now_label != '':
        summary_step = {'state': 'now' if now > 0 else 'blocked', 'label': now_label, 'sub': '',
                        'startedAt': None, 'lane': 0, 'col': 0}
    running = (next((s for s in steps if s['state'] == 'now'), None)
               or next((s for s in steps if s['state'] == 'side'), None))
    compactions = raw.get('compactions') if isinstance(raw.get('compactions'), dict) else {}
    key = summary.get('key')
    return {
        'status': text(raw.get('status'), 'working'),
        'lang': 'en' if summary.get('lang') == 'en' else 'ko',
        'key': key if isinstance(key, str) and key != '' else None,
        'title': text(summary.get('title'), ''),
        'done': done, 'now': now, 'side': side, 'left': left, 'blocked': blocked,
        'total': count(summary.get('total')),
        'allDone': summary.get('allDone') is True,
        'current': running if running is not None else (summary_step if now > 0 else None),
        'next': next_step(steps, running),
        'stuck': (next((s for s in steps if s['state'] == 'blocked'), None)
                  or (summary_step if now == 0 and blocked > 0 else None)),
        'eta': summary.get('eta') if isinstance(summary.get('eta'), str) else None,
        'updatedAt': raw.get('updatedAt') if isinstance(raw.get('updatedAt'), str) else None,
        'since': raw.get('since') if isinstance(raw.get('since'), str) else None,
        'background': len(raw['backgroundTasks']) if isinstance(raw.get('backgroundTasks'), list) else 0,
        'compactions': count(compactions.get('count')),
    }


# ── 그림 ────────────────────────────────────────────────────────────────────

# Claude Code 다크 테마가 테마 키에 배정한 색에 맞춘 근사치다. 정확한 값은 그 테마가 정한다.
TONES = {
    'claude': '#d97757', 'permission': '#9db4ff', 'text': '#d8d8dc', 'success': '#5fd38d',
    'subtle': '#7c7d86', 'planMode': '#9d8cff', 'warning': '#f2c94c', 'error': '#ff6b6b',
    'suggestion': '#6cc7e8', 'inactive': '#8b8d98', 'autoAccept': '#ff8ac6', 'merged': '#b39dff',
    'ide': '#6ca9e8', 'remember': '#e8a0ff', 'plain': '#d8d8dc',
}

# 엔진이 그리는 부분(대화 영역·입력칸·힌트)의 색. deadhd 의 테마 키와는 무관하다.
TEXT, DIM, EDGE, PERMISSION = '#d8d8dc', '#7a7b82', '#3a3b44', '#e06c75'

SIZE_MARK = 'deadhd-mods-size:'

# 가로선 자리. 터미널 폭은 그 조각의 줄들로 정해지므로 그릴 때 채운다.
RULE = object()

HINT_STRONG = '⏵⏵ bypass permissions on'
HINT_REST = ' (shift+tab to cycle) · ← for agents'


class Line:
    """터미널 한 줄: 그린 HTML 과, 터미널 폭을 정할 평문."""

    def __init__(self, html, text):
        self.html = html
        self.text = text


def esc(value):
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def spans(parts, tail=''):
    parts = list(parts)
    if tail and parts:
        last = parts[-1]
        parts[-1] = (last[0] + tail, last[1], last[2])
    return ''.join('<span style="color:%s%s">%s</span>'
                   % (TONES[tone], ';font-weight:700' if bold else '', esc(part))
                   for part, tone, bold in parts)


def row(parts, tail=''):
    return Line('<div class="row">%s</div>' % spans(parts, tail),
                ''.join(part[0] for part in parts) + tail)


def plain(content, cls=''):
    """색 없이 그리는 한 줄: 대화 영역과 엔진 힌트."""
    return Line('<div class="row%s">%s</div>' % ((' ' + cls) if cls else '', esc(content)), content)


def control_row(parts, controls):
    """밴드·상태줄 한 줄: 조각들 끝에 터미널 버튼 `[ label ]` 을 붙인다."""
    drawn = ''.join('<span class="btn%s">[ %s ]</span>' % (' primary' if primary else '', esc(label))
                    for label, primary in controls)
    text = ''.join(part[0] for part in parts) + ' ' + ' '.join('[ %s ]' % label
                                                              for label, _ in controls)
    return Line('<div class="row">%s%s</div>' % (spans(parts, ' '), drawn), text)


def prompt_row():
    """입력칸: `❯ ` 와 흰 블록 커서 한 줄."""
    return Line('<div class="row">❯ <span class="cursor"> </span></div>', '❯  ')


def hint_row():
    return Line('<div class="row"><span style="color:%s">%s</span><span class="dim">%s</span></div>'
                % (PERMISSION, esc(HINT_STRONG), esc(HINT_REST)), HINT_STRONG + HINT_REST)


def terminal(rows):
    cols = max([cell_width(one.text) for one in rows if one is not RULE] or [0])
    edge = '<div class="row rule">%s</div>' % ('─' * cols)
    return '<div class="term">%s</div>' % ''.join(edge if one is RULE else one.html
                                                  for one in rows)


def page(lang, blocks):
    caps = ''.join('<div class="block"><div class="cap">%s</div>%s</div>' % (esc(caption), body)
                   for caption, body in blocks)
    return """<!doctype html>
<html lang="%s"><head><meta charset="utf-8"><style>
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: #0d0d0d; }
.page { display: flex; flex-direction: column; gap: %dpx; padding: %dpx; width: max-content; }
.block { display: flex; flex-direction: column; gap: 7px; }
.cap { color: #8a8f9e; font: 13px -apple-system, "Apple SD Gothic Neo", sans-serif; }
.term { background: #101012; padding: 10px 12px; width: max-content;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: %dpx; line-height: %dpx; }
.row { color: %s; white-space: pre; }
.dim { color: %s; }
.rule { color: %s; }
.cursor { background: %s; }
.btn { color: %s; }
.btn.primary { color: %s; }
</style>
<script>window.addEventListener('load', function () {
  var r = document.querySelector('.page').getBoundingClientRect();
  console.log('%s' + Math.ceil(r.width) + 'x' + Math.ceil(r.height));
});</script>
</head><body><div class="page">%s</div></body></html>
""" % (lang, GAP, PAD, FONT, LINE, TEXT, DIM, EDGE, TEXT, TEXT, TONES['claude'], SIZE_MARK, caps)


def content_size(html):
    # 그림 크기를 내용에 맞춘다. 창을 크게 잡으면 빈 배경이 함께 찍힌다.
    # Chrome 이 로그를 흘리는 때가 있어 몇 번 다시 물어본다.
    for _ in range(3):
        size = measure_once(html)
        if size is not None:
            return size
    return None


def measure_once(html):
    ud_dir = tempfile.mkdtemp(prefix='deadhd-mods-measure-')
    args = chrome_args(ud_dir, (1600, 600),
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
                found = re.search(re.escape(SIZE_MARK.encode()) + rb'(\d+)x(\d+)', buf)
                if found:
                    return int(found.group(1)), int(found.group(2))
            elif proc.poll() is not None:
                break
        return None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        shutil.rmtree(ud_dir, ignore_errors=True)


def shoot(ud_dir, html, out_png, what):
    size = content_size(html)
    if size is None:
        die('페이지가 자기 크기를 알려 주지 않았다: %s' % html)
    # 캡처가 실패해도 기존 그림을 잃지 않게 임시 파일에 찍고 옮긴다.
    tmp_png = out_png + '.tmp.png'
    chrome_shot(chrome_args(ud_dir, size, ['--screenshot=' + tmp_png, 'file://' + html]), tmp_png)
    os.replace(tmp_png, out_png)
    print('%s: %s (%dx%d)' % (what, out_png, size[0], size[1]))


# ── mod 문자열 대조 ─────────────────────────────────────────────────────────

# register.test.ts 의 SAMPLE·BOARD·NOW 와 같다.
NOW_TEST = int(datetime.fromisoformat('2026-10-09T15:38:53+09:00').timestamp() * 1000)
SAMPLE = {
    'status': 'working', 'since': '2026-10-09T15:34:53+09:00', 'view': 'band',
    'backgroundTasks': [{'type': 'bash', 'description': 'watch'}, {'type': 'bash', 'description': 'build'}],
    'compactions': {'count': 1, 'lastAt': '2026-10-09T15:00:00+09:00'},
    'summary': {
        'title': 'CAS-1161 콘솔 dev 회귀 3회차', 'key': 'CAS-1161', 'lang': 'ko',
        'counts': {'done': 3, 'now': 1, 'side': 0, 'left': 2, 'blocked': 1}, 'total': 6,
        'nowLabel': '실제 화면 확인', 'eta': '2026-10-09T16:20:00+09:00', 'allDone': False,
    },
    'updatedAt': '2026-10-09T15:36:53+09:00',
}
BOARD = {
    'key': 'CAS-1161', 'title': 'CAS-1161 콘솔 dev 회귀 3회차', 'lanes': ['준비', '배포'],
    'items': [
        {'lane': 0, 'col': 0, 'label': '준비', 'sub': '완료', 'state': 'done'},
        {'lane': 0, 'col': 1, 'label': 'setup 통합', 'state': 'left'},
        {'lane': 1, 'col': 0, 'label': '실제 화면 확인', 'sub': '진행', 'state': 'now',
         'startedAt': '2026-10-09T15:34:53+09:00'},
        {'lane': 1, 'col': 1, 'label': '배포 검증', 'sub': '권한 대기', 'state': 'blocked'},
        {'lane': 1, 'col': 2, 'label': '정리', 'state': 'left'},
        {'lane': 1, 'col': 3, 'label': '보고', 'sub': '완료', 'state': 'done'},
    ],
}
BAND_EXPECT = '/deadhd-band · ▓▓▓░░░ 3/6 · ▶ 실제 화면 확인 4분째 · 막힘 1 · 남음 2'
ALERT_EXPECT = '⛔ 막힘: 배포 검증 (권한 대기) · 🔐 권한 승인 대기 4분째'
CUT_EXPECT = '/deadhd-band · ▓▓▓░░░ 3/6 · 막힘 1 · 남음 2'
LONG_LABEL = '아주 긴 단계 이름이 여기에 들어 있다'
LONG_ROW = ('/deadhd-statusline · ✅ 3/6 ▓▓▓░░░ · CAS-1161 CAS-1161 콘솔 dev 회귀 3회차 · '
            '▶️ 실제 화면 확인 4분째 · ⏭ 다음 정리 · ⏱ 예상 16:20 · 🔄 2분 전 · ⛔ 막힘 1: 배포 검증 · '
            '⏳ 남음 2 · 🧵 백그라운드 2 · 🗜 압축 1 · ↗ /deadhd-open')
# LONG_ROW 는 테스트에서 두 줄로 쪼개 붙이므로 조각으로 확인한다.
TEST_FRAGMENTS = (BAND_EXPECT, ALERT_EXPECT,
                  '✅ 3/6 ▓▓▓░░░ · CAS-1161 CAS-1161 콘솔 dev 회귀 3회차 · ',
                  '⏳ 남음 2 · 🧵 백그라운드 2 · 🗜 압축 1',
                  '↗ /deadhd-open')


def check_lines():
    """재현한 줄이 실제 mod 와 register.test.ts 의 기대 문자열에 모두 맞는지 본다. 어긋나면 그림을 만들지 않는다."""
    source = open(os.path.join(REPO, 'skills', 'deadhd', 'hooks', 'register.test.ts'),
                  encoding='utf-8').read()
    state = normalize(SAMPLE, BOARD)
    waiting = dict(state, status='waiting_permission')
    long_step = dict(state, current=dict(state['current'], label=LONG_LABEL))
    drawn = (('bandLine', segments_text(band_line(state, NOW_TEST, 200)), BAND_EXPECT),
             ('bandAlertLine', segments_text(band_alert_line(waiting, NOW_TEST, 200)), ALERT_EXPECT),
             ('statusLine', format_line(state, NOW_TEST, 240), LONG_ROW),
             ('bandLine/maxCols 40', segments_text(band_line(long_step, NOW_TEST, 40)), CUT_EXPECT))
    for name, produced, expected in drawn:
        if produced != expected:
            die('%s 가 테스트 기대 문자열과 다르다\n  재현: %s\n  기대: %s' % (name, produced, expected))
        print('mod 대조 OK %s: %s' % (name, produced))
    # 자르는 줄은 60칸에 맞춰 줄어들고, 말줄임표를 붙이며, 숫자는 남긴다.
    cut_line = segments_text(band_line(long_step, NOW_TEST, 60))
    if cell_width(cut_line) > 60 or '…' not in cut_line or '3/6' not in cut_line or '남음 2' not in cut_line:
        die('bandLine/maxCols 60 이 자르기 규칙과 다르다: %s' % cut_line)
    print('mod 대조 OK bandLine/maxCols 60: %s' % cut_line)
    for fragment in TEST_FRAGMENTS:
        if fragment not in source:
            die('register.test.ts 에서 기대 문자열을 찾지 못했다: %s' % fragment)
    print('mod 대조 OK: 위 줄들이 register.test.ts 의 기대 문자열과 같다')


def main(argv):
    lang = 'ko'
    rest = argv[1:]
    if rest[:1] == ['--lang']:
        if len(rest) < 2:
            die('사용법: capture_mods.py [--lang ko|en]')
        lang, rest = rest[1], rest[2:]
    if lang not in ('ko', 'en') or rest:
        die('사용법: capture_mods.py [--lang ko|en]')
    if not os.path.exists(CHROME):
        die('Chrome 을 찾지 못했다: %s (환경 변수 CHROME 로 지정)' % CHROME)

    check_lines()

    demos_dir = os.path.join(HERE, 'demos', 'en') if lang == 'en' else os.path.join(HERE, 'demos')
    suffix = '.en.png' if lang == 'en' else '.png'
    talk = {
        'ko': {
            'call': 'Bash(python3 -m unittest skills/deadhd/test_render.py)',
            'result': '  ⎿  Ran 398 tests in 6.21s — OK',
            'say': '테스트가 통과했다. 카나리 전에 남은 검증만 돌리면 된다.',
            'worked': 'Worked for 27s · done 2026-10-09 16:19',
            'bandCap': '밴드: 입력칸 위 한 줄. 막힌 단계나 대기가 있으면 둘째 줄이 붙는다.',
            'foldedCap': '접힌 밴드: /deadhd-band 로 접었을 때',
            'statusCap': '상태줄: 입력칸 아래, 엔진 힌트 다음 줄',
        },
        'en': {
            'call': 'Bash(python3 -m unittest skills/deadhd/test_render.py)',
            'result': '  ⎿  Ran 398 tests in 6.21s — OK',
            'say': 'Tests pass. Only the last canary checks are left.',
            'worked': 'Worked for 27s · done 2026-10-09 16:19',
            'bandCap': 'Band: one row above the input. A second row appears when a step is '
                       'stuck or the session waits.',
            'foldedCap': 'Folded band: after /deadhd-band',
            'statusCap': 'Status line: under the input, on the row after the engine hint',
        },
    }[lang]

    work = tempfile.mkdtemp(prefix='deadhd-mods-')
    ud_root = tempfile.mkdtemp(prefix='deadhd-chrome-')
    try:
        history = os.path.join(work, 'history.jsonl')
        with open(history, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'est': 10, 'actual': 16}) + '\n')
        render_panel(CASE, THEME, work, demos_dir, session=SESSION, now=NOW,
                     extra_env={'DEADHD_HISTORY': history,
                                'DEADHD_CONFIG': os.path.join(work, 'config.json')})

        health = os.path.join(work, 'state', SESSION + '.json')
        with open(health, encoding='utf-8') as f:
            raw = json.load(f)
        # 상태 파일에 적히는 필드는 훅(state.py)이 남긴다. 찍는 시각에 맞춰 같은 값으로 채운다.
        base = datetime.fromisoformat(NOW)
        raw['status'] = 'waiting_permission'
        raw['since'] = (base - timedelta(minutes=WAIT_MINUTES)).isoformat(timespec='seconds')
        raw['updatedAt'] = (base - timedelta(minutes=STALE_MINUTES)).isoformat(timespec='seconds')
        raw['backgroundTasks'] = [{'type': 'bash', 'description': 'watch'},
                                  {'type': 'bash', 'description': 'build'}]
        raw['compactions'] = {'count': 1, 'lastAt': raw['updatedAt']}
        with open(health, 'w', encoding='utf-8') as f:
            json.dump(raw, f, ensure_ascii=False)

        with open(raw['data'], encoding='utf-8') as f:
            board = json.load(f)
        state = normalize(raw, board)
        if state is None:
            die('상태 파일을 읽지 못했다: %s' % health)
        now = int(base.timestamp() * 1000)
        words = WORDS[lang]
        print('case: %s (%s, %s)' % (CASE, lang, state['status']))

        band = band_line(state, now, STATUS_COLS)
        alerts = band_alert_line(state, now, STATUS_COLS)
        status = status_line(state, now, STATUS_COLS)
        folded = folded_segments(state)

        # 실제 화면 순서 그대로다: 대화 영역, 밴드(프롬프트 위), 입력칸, 엔진 힌트,
        # 그리고 상태줄 모드에서만 그 아래에 deadhd 상태줄.
        talk_lines = [
            plain('⏺ ' + talk['call']),
            plain(talk['result'], 'dim'),
            plain('⏺ ' + talk['say']),
            plain('* ' + talk['worked'], 'dim'),
        ]
        under_input = [RULE, prompt_row(), RULE, hint_row()]
        band_blocks = [
            (talk['foldedCap'], terminal(talk_lines + [
                control_row(folded, [(words['open'], True), (words['expand'], False)]),
            ] + under_input)),
            (talk['bandCap'], terminal(talk_lines + [
                control_row(band, [(words['open'], True), (words['collapse'], False)]),
                row(alerts),
            ] + under_input)),
        ]
        status_blocks = [
            (talk['statusCap'], terminal(talk_lines + under_input + [
                control_row(status, [(words['open'], True)]),
            ])),
        ]

        for what, blocks, name in (('band', band_blocks, 'band' + suffix),
                                   ('statusline', status_blocks, 'statusline' + suffix)):
            html = os.path.join(work, what + '.' + lang + '.html')
            with open(html, 'w', encoding='utf-8') as f:
                f.write(page(lang, blocks))
            shoot(os.path.join(ud_root, 'ud-' + what), html, os.path.join(HERE, name), what)
    finally:
        shutil.rmtree(ud_root, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv)
