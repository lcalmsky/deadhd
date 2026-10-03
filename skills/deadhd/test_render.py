#!/usr/bin/env python3
"""render.py 의 렌더 결과와 입력 검증을 확인한다."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, 'render.py')
TEMPLATE = os.path.join(HERE, 'template.html')
EXAMPLE = os.path.join(HERE, 'example.json')
MISSING_CONFIG = os.path.join(tempfile.gettempdir(), 'deadhd-no-such-config', 'config.json')

EXTRA_THEMES = ('neon', 'synthwave', 'matrix', 'nord', 'paper', 'sakura')
THEME_TOKENS = (
    '--bg', '--bg-2', '--card', '--card-line', '--ink', '--ink-2', '--ink-3',
    '--done', '--done-2', '--done-deep', '--now', '--now-2', '--now-deep', '--now-hi',
    '--side', '--side-hi', '--left', '--blocked', '--blocked-2', '--blocked-deep',
    '--track', '--tip', '--count-end', '--scroll', '--scroll-hover',
    '--glow-a', '--glow-b', '--glow-c',
)


def run_render(data_path, out_path, theme=None, config_path=None, env_extra=None):
    env = dict(os.environ)
    env['DEADHD_CONFIG'] = config_path if config_path is not None else MISSING_CONFIG
    env.pop('XDG_CONFIG_HOME', None)
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, RENDER]
    if theme is not None:
        cmd += ['--theme', theme]
    cmd += [data_path, out_path]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def load_example():
    with open(EXAMPLE, encoding='utf-8') as f:
        return json.load(f)


def html_tag(html):
    m = re.search(r'<html[^>]*>', html)
    assert m is not None, '<html> 태그를 찾지 못했다'
    return m.group(0)


def data_block(html):
    m = re.search(r'<script id="progress-data" type="application/json">(.*?)</script>', html, re.S)
    assert m is not None, '데이터 script 블록을 찾지 못했다'
    return m.group(1)


def parse_block(block):
    return json.loads(block.replace('<\\/', '</').replace('<\\!--', '<!--'))


NODE = shutil.which('node')

# 렌더된 HTML 의 본문 스크립트를 그대로 실행해 linkify 가 만든 <a> 를 꺼낸다.
# 링크 동작은 스크립트 전체가 돌아야 만들어지므로, 스크립트가 요구하는 만큼의
# 가짜 DOM 만 node 쪽에 세우고 함수 정의를 줄 번호로 잘라내지 않는다.
LINKIFY_HARNESS = r'''
const fs = require('fs');
const code0 = fs.readFileSync(process.argv[2], 'utf8');
const rawData = fs.readFileSync(process.argv[3], 'utf8');

function textOf(n) {
  if (n.tag === '#text') return n.text;
  let s = '';
  for (const k of n.children) s += textOf(k);
  return s;
}

function textNode(s) {
  const n = new El('#text');
  n.text = String(s);
  return n;
}

function El(tag) {
  this.tag = tag;
  this.tagName = tag === '#text' ? '#text' : tag.toUpperCase();
  this.children = [];
  this.attrs = {};
  this.dataset = {};
  this.hidden = false;
  this.text = '';
  this.id = '';
  this.href = null;
  this._cls = '';
  const self = this;
  this.style = { setProperty: function (k, v) { this[k] = v; } };
  this.classList = { add: function (c) { self._cls = self._cls ? self._cls + ' ' + c : c; } };
}

Object.defineProperty(El.prototype, 'className', {
  get: function () { return this._cls; },
  set: function (v) { this._cls = String(v); }
});

Object.defineProperty(El.prototype, 'textContent', {
  get: function () { return textOf(this); },
  set: function (v) {
    v = String(v);
    this.children = v === '' ? [] : [textNode(v)];
  }
});

El.prototype.appendChild = function (c) {
  if (c.tag === '#fragment') {
    for (const k of c.children) this.children.push(k);
    return c;
  }
  this.children.push(c);
  return c;
};
El.prototype.setAttribute = function (k, v) {
  this.attrs[k] = String(v);
  if (k === 'class') this._cls = String(v);
};
El.prototype.addEventListener = function () {};
El.prototype.remove = function () {};
El.prototype.getBoundingClientRect = function () { return { left: 0, top: 0, width: 0, height: 0 }; };
El.prototype.querySelector = function () { return null; };

function makeDocument(raw) {
  const byId = new Map();
  const queries = new Map();
  const doc = {
    body: new El('body'),
    createElement: function (t) { return new El(t); },
    createElementNS: function (ns, t) { return new El(t); },
    createTextNode: function (t) { return textNode(t); },
    createDocumentFragment: function () { return new El('#fragment'); },
    getElementById: function (id) {
      if (!byId.has(id)) { const e = new El('div'); e.id = id; byId.set(id, e); }
      return byId.get(id);
    },
    querySelector: function (sel) {
      if (!queries.has(sel)) { const e = new El('div'); e.sel = sel; queries.set(sel, e); }
      return queries.get(sel);
    }
  };
  doc.getElementById('progress-data').textContent = raw;
  doc._byId = byId;
  return doc;
}

function serialize(n) {
  if (n.tag === '#text') return { t: '#text', text: n.text };
  const o = { t: n.tagName, text: textOf(n) };
  if (n.id) o.id = n.id;
  if (n.className) o.cls = n.className;
  if (n.href != null) o.href = n.href;
  if (n.sel) o.sel = n.sel;
  if (n.dataset && Object.keys(n.dataset).length) o.data = Object.assign({}, n.dataset);
  const style = {};
  for (const k in n.style) { if (typeof n.style[k] !== 'function') style[k] = n.style[k]; }
  if (Object.keys(style).length) o.style = style;
  if (n.children.length) o.kids = n.children.map(serialize);
  return o;
}

const probeSrc = "\n  globalThis.__linkProbe = { httpHref: httpHref, linkElInfo: function (h) { var n = linkEl(h, document.createTextNode('t'), 'lnk'); return { tag: n.tagName, href: n.href == null ? null : n.href }; }, fmtClock: function (t, v) { return fmtClock(t, v); }, fmtDur: fmtDur };\n";
const idx = code0.lastIndexOf('})();');
if (idx < 0) throw new Error('IIFE 끝을 찾지 못했다');
const code = code0.slice(0, idx) + probeSrc + code0.slice(idx);

// 인자 없는 new Date() 와 Date.now 만 고정 시각으로 바꾼다. 인자가 있으면 실제 Date 그대로다.
function fixClock(iso) {
  const RealDate = Date;
  const fixedMs = new RealDate(iso).getTime();
  function FixedDate(...args) {
    if (!new.target) return new RealDate(fixedMs).toString();
    return args.length === 0 ? new RealDate(fixedMs) : new RealDate(...args);
  }
  FixedDate.prototype = RealDate.prototype;
  FixedDate.now = function () { return fixedMs; };
  FixedDate.parse = RealDate.parse;
  FixedDate.UTC = RealDate.UTC;
  globalThis.Date = FixedDate;
}

const fixedNow = process.argv[5] || '';
if (fixedNow) fixClock(fixedNow);

const doc = makeDocument(rawData);
const ss = {
  _m: {},
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(this._m, k) ? this._m[k] : null; },
  setItem: function (k, v) { this._m[k] = String(v); }
};
const run = new Function('document', 'matchMedia', 'sessionStorage', code);
run(doc, function () { return { matches: false }; }, ss);

const probe = globalThis.__linkProbe;
function info(h) { return probe.linkElInfo(h); }

const nodes = {};
for (const entry of doc._byId) {
  if (entry[0] === 'progress-data') continue;
  nodes[entry[0]] = serialize(entry[1]);
}

const cases = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], 'utf8')) : null;
const fmt = cases ? {
  clock: (cases.clock || []).map(c => probe.fmtClock(c[0], c[1])),
  dur: (cases.dur || []).map(m => probe.fmtDur(m))
} : null;

process.stdout.write(JSON.stringify({
  fmt: fmt,
  probe: {
    httpHref_javascript: probe.httpHref('javascript:alert(1)'),
    httpHref_http: probe.httpHref('http://ok.test/x'),
    httpHref_upper: probe.httpHref('HTTPS://OK.test/y'),
    httpHref_null: probe.httpHref(null),
    link_javascript: info('javascript:alert(1)'),
    link_data: info('data:text/html,x'),
    link_ftp: info('ftp://example.com/x'),
    link_mailto: info('mailto:a@b.c'),
    link_http: info('http://ok.test/x'),
    link_upper: info('HTTPS://OK.test/y'),
    link_null: info(null),
    link_number: info(123)
  },
  nodes: nodes
}));
'''


def script_block(html):
    blocks = re.findall(r'<script>(.*?)</script>', html, re.S)
    assert len(blocks) == 1, '본문 script 블록이 정확히 하나가 아니다: %d개' % len(blocks)
    return blocks[0]


def run_linkify_harness(html, cases=None, fixed_now=None):
    with tempfile.TemporaryDirectory(prefix='progress-linkify-') as d:
        files = {}
        for name, text in (
            ('harness.js', LINKIFY_HARNESS),
            ('script.js', script_block(html)),
            ('data.txt', data_block(html)),
        ):
            path = os.path.join(d, name)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            files[name] = path
        cmd = [NODE, files['harness.js'], files['script.js'], files['data.txt']]
        env = dict(os.environ)
        cases_path = ''
        if cases is not None:
            cases_path = os.path.join(d, 'cases.json')
            with open(cases_path, 'w', encoding='utf-8') as f:
                json.dump(cases, f, ensure_ascii=False)
        # fmtClock 은 로컬 날짜를 보므로 실행 시차를 고정해 기대값을 결정적으로 만든다.
        if cases is not None or fixed_now is not None:
            env['TZ'] = 'Asia/Seoul'
        cmd += [cases_path, fixed_now or '']
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=d, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def iter_nodes(node):
    yield node
    for kid in node.get('kids', ()):
        yield from iter_nodes(kid)


class TemplateLinkifyTest(unittest.TestCase):
    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-linkify-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_data(self, data):
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            return run_linkify_harness(f.read())

    def links(self, result):
        found = []
        for tree in result['nodes'].values():
            for node in iter_nodes(tree):
                if node['t'] == 'A':
                    found.append((node.get('href'), node['text']))
        return found

    def body_texts(self, result):
        card = result['nodes'].get('cards', {})
        return [n['text'] for n in iter_nodes(card) if n['t'] == 'P']

    def data_with_text(self, text, links=None, evidence=None):
        item = {'id': 'a', 'label': 'L', 'state': 'done', 'body': text}
        if evidence is not None:
            item['evidence'] = evidence
        data = {'title': 'T', 'items': [item]}
        if links is not None:
            data['links'] = links
        return data

    def test_longest_key_wins_and_boundaries_hold(self):
        text = 'SHOP-130 와 SHOP-13 그리고 SHOP-1300'
        links = {'SHOP-13': 'https://x.test/13', 'SHOP-130': 'https://x.test/130'}
        result = self.run_data(self.data_with_text(text, links))
        self.assertEqual(self.links(result), [
            ('https://x.test/130', 'SHOP-130'),
            ('https://x.test/13', 'SHOP-13'),
        ])
        self.assertIn(text, self.body_texts(result))

    def test_adjacent_word_chars_are_not_linked(self):
        text = 'xSHOP-13 그리고 SHOP-13_a'
        links = {'SHOP-13': 'https://x.test/13'}
        result = self.run_data(self.data_with_text(text, links))
        self.assertEqual(self.links(result), [])

    def test_regex_special_keys_match_only_themselves(self):
        text = 'shop-api#4120 와 a.b(1) 와 xshop-api#4120 그리고 a.b(1)2'
        links = {'shop-api#4120': 'https://gh.test/4120', 'a.b(1)': 'https://gh.test/ab1'}
        result = self.run_data(self.data_with_text(text, links))
        self.assertEqual(self.links(result), [
            ('https://gh.test/4120', 'shop-api#4120'),
            ('https://gh.test/ab1', 'a.b(1)'),
        ])
        self.assertIn(text, self.body_texts(result))

    def test_bare_url_drops_trailing_punctuation(self):
        text = '자세한 건 https://example.com/a?b=1. 참고'
        result = self.run_data(self.data_with_text(text))
        self.assertEqual(self.links(result), [
            ('https://example.com/a?b=1', 'https://example.com/a?b=1'),
        ])
        self.assertIn(text, self.body_texts(result))

    def test_url_links_work_without_links_map(self):
        text = 'SHOP-9999 그리고 https://example.com/x 참고'
        for links in (None, {}):
            with self.subTest(links=links):
                result = self.run_data(self.data_with_text(text, links))
                self.assertEqual(self.links(result), [
                    ('https://example.com/x', 'https://example.com/x'),
                ])

    def test_non_http_href_makes_no_anchor(self):
        result = self.run_data(self.data_with_text('평범한 본문', {}))
        probe = result['probe']
        self.assertIsNone(probe['httpHref_javascript'])
        self.assertIsNone(probe['httpHref_null'])
        self.assertEqual(probe['httpHref_http'], 'http://ok.test/x')
        self.assertEqual(probe['httpHref_upper'], 'HTTPS://OK.test/y')
        for key in ('link_javascript', 'link_data', 'link_ftp', 'link_mailto', 'link_null', 'link_number'):
            with self.subTest(href=key):
                self.assertNotEqual(probe[key]['tag'], 'A')
                self.assertIsNone(probe[key]['href'])
        self.assertEqual(probe['link_http'], {'tag': 'A', 'href': 'http://ok.test/x'})
        self.assertEqual(probe['link_upper'], {'tag': 'A', 'href': 'HTTPS://OK.test/y'})

    def test_evidence_href_text_does_not_nest_anchor(self):
        links = {'SHOP-13': 'https://x.test/13'}
        evidence = [{'text': 'SHOP-13 티켓 확인', 'href': 'https://tracker.test/9'}]
        result = self.run_data(self.data_with_text('증거는 아래와 같다', links, evidence))
        anchors = [
            node for tree in result['nodes'].values()
            for node in iter_nodes(tree) if node['t'] == 'A'
        ]
        self.assertEqual(len(anchors), 1)
        anchor = anchors[0]
        self.assertEqual(anchor.get('href'), 'https://tracker.test/9')
        self.assertEqual(anchor['text'], 'SHOP-13 티켓 확인')
        self.assertFalse(any(n['t'] == 'A' for n in iter_nodes(anchor) if n is not anchor))


FIXED_NOW = '2026-10-03T10:00:00+09:00'


def mini_item(iid, state, **extra):
    item = {'id': iid, 'label': iid.upper(), 'state': state}
    item.update(extra)
    return item


class EtaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-eta-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def render(self, items, extra=None, now=FIXED_NOW):
        data = {'title': 'T', 'items': items}
        if extra:
            data.update(extra)
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out, env_extra={'DEADHD_NOW': now})
        if r.returncode != 0:
            return r, None
        with open(out, encoding='utf-8') as f:
            return r, parse_block(data_block(f.read()))

    def payload(self, items, **kwargs):
        r, parsed = self.render(items, **kwargs)
        self.assertEqual(r.returncode, 0, r.stderr)
        return parsed

    def test_eta_sums_now_and_left_estimates_without_side(self):
        items = [
            mini_item('a', 'done'),
            mini_item('b', 'now', estimate=30),
            mini_item('c', 'left', estimate=15),
            mini_item('d', 'side', estimate=999),
        ]
        parsed = self.payload(items)
        self.assertEqual(parsed['eta'], '2026-10-03T10:45:00+09:00')
        self.assertEqual(parsed['renderedAt'], FIXED_NOW)

    def test_eta_absent_when_blocked(self):
        items = [mini_item('a', 'now', estimate=30), mini_item('b', 'blocked')]
        self.assertNotIn('eta', self.payload(items))

    def test_eta_absent_when_any_pending_estimate_missing(self):
        for items in (
            [mini_item('a', 'now'), mini_item('b', 'left', estimate=15)],
            [mini_item('a', 'now', estimate=30), mini_item('b', 'left')],
        ):
            with self.subTest(items=items):
                self.assertNotIn('eta', self.payload(items))

    def test_eta_absent_when_nothing_pending(self):
        for items in ([mini_item('a', 'done')], [mini_item('a', 'side', estimate=30)]):
            with self.subTest(items=items):
                self.assertNotIn('eta', self.payload(items))

    def test_input_eta_and_rendered_at_are_replaced(self):
        items = [mini_item('a', 'now', estimate=30)]
        stale = '1999-01-01T00:00:00+09:00'
        parsed = self.payload(items, extra={'eta': stale, 'renderedAt': stale})
        self.assertEqual(parsed['eta'], '2026-10-03T10:30:00+09:00')
        self.assertEqual(parsed['renderedAt'], FIXED_NOW)

    def test_zulu_timestamps_are_accepted(self):
        items = [mini_item('a', 'done', startedAt='2026-10-02T22:35:00Z', doneAt='2026-10-03T01:35:00Z')]
        self.assertNotIn('eta', self.payload(items))

    def test_started_at_without_offset_is_rejected(self):
        items = [mini_item('a', 'done', startedAt='2026-10-02T22:35:00')]
        r, _ = self.render(items)
        self.assertEqual(r.returncode, 1)
        self.assertIn('items[0].startedAt', r.stderr)
        self.assertIn('시차', r.stderr)

    def test_unparsable_timestamp_is_rejected(self):
        items = [mini_item('a', 'done', doneAt='yesterday')]
        r, _ = self.render(items)
        self.assertEqual(r.returncode, 1)
        self.assertIn('items[0].doneAt', r.stderr)

    def test_done_before_started_is_rejected(self):
        items = [mini_item('a', 'done', startedAt='2026-10-03T10:00:00+09:00', doneAt='2026-10-03T09:00:00+09:00')]
        r, _ = self.render(items)
        self.assertEqual(r.returncode, 1)
        self.assertIn('items[0]', r.stderr)
        self.assertIn('doneAt', r.stderr)

    def test_bad_estimate_is_rejected(self):
        for value in (0, -3, True, '5'):
            with self.subTest(estimate=value):
                items = [mini_item('a', 'left', estimate=value)]
                r, _ = self.render(items)
                self.assertEqual(r.returncode, 1)
                self.assertIn('items[0].estimate', r.stderr)

    def test_non_finite_or_oversized_estimate_is_rejected(self):
        for value in (float('nan'), float('inf'), 525601, 1e30):
            with self.subTest(estimate=repr(value)):
                items = [mini_item('a', 'left', estimate=value)]
                r, _ = self.render(items)
                self.assertEqual(r.returncode, 1)
                self.assertIn('items[0].estimate', r.stderr)
                self.assertNotIn('Traceback', r.stderr)

    def test_started_at_alone_is_accepted(self):
        items = [mini_item('a', 'now', startedAt='2026-10-03T09:00:00+09:00', estimate=30)]
        self.assertEqual(self.payload(items)['eta'], '2026-10-03T10:30:00+09:00')


class TemplateTimeFormatTest(unittest.TestCase):
    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-fmt-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cases(self, cases):
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'title': 'T', 'items': [mini_item('a', 'done')]}, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            return run_linkify_harness(f.read(), cases)['fmt']

    def test_fmt_clock(self):
        stamp = '2026-10-03T01:00:00+09:00'
        cases = {'clock': [
            ['2026-10-03T03:52:00+09:00', stamp],
            ['2026-10-04T03:52:00+09:00', stamp],
            ['2026-10-05T04:57:00+09:00', stamp],
            ['2026-10-01T04:57:00+09:00', stamp],
            ['2026-09-07T04:57:00+09:00', stamp],
            ['2026-10-04T00:05:00+09:00', '2026-10-03T23:59:00+09:00'],
            ['2026-10-04T00:05:00+09:00', '2026-10-04T00:01:00+09:00'],
        ]}
        self.assertEqual(self.run_cases(cases)['clock'], [
            '03:52', '내일 03:52', '10.05 04:57', '10.01 04:57', '9.07 04:57',
            '내일 00:05', '00:05',
        ])

    def test_fmt_dur(self):
        cases = {'dur': [59, 60, 70, 1439, 1440, 1560]}
        self.assertEqual(
            self.run_cases(cases)['dur'],
            ['59분', '1시간', '1시간 10분', '23시간 59분', '1일', '1일 2시간'],
        )


class TemplateDomStateTest(unittest.TestCase):
    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-dom-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def render_dom(self, items, extra=None, now=FIXED_NOW, view=FIXED_NOW):
        data = {'title': 'T', 'items': items}
        if extra:
            data.update(extra)
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out, env_extra={'DEADHD_NOW': now})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            return run_linkify_harness(f.read(), fixed_now=view)

    def find(self, result, cls):
        found = []
        for tree in result['nodes'].values():
            for node in iter_nodes(tree):
                if cls in (node.get('cls') or '').split():
                    found.append(node)
        return found

    def by_id(self, result, iid):
        for tree in result['nodes'].values():
            for node in iter_nodes(tree):
                if (node.get('data') or {}).get('id') == iid:
                    return node
        self.fail('그래프 노드를 찾지 못했다: ' + iid)

    def when_text(self, result, iid):
        for kid in self.by_id(result, iid).get('kids', ()):
            if 'when' in (kid.get('cls') or '').split():
                return kid['cls'], kid['text']
        return None

    def test_eta_line_same_day_and_next_day(self):
        same = self.find(self.render_dom([mini_item('a', 'now', estimate=30)]), 'eta')
        self.assertEqual([n['cls'] for n in same], ['eta'])
        self.assertEqual([n['text'] for n in same], ['완료 예상 10:30'])

        nxt = self.find(self.render_dom([mini_item('a', 'now', estimate=1080)]), 'eta')
        self.assertEqual([n['text'] for n in nxt], ['완료 예상 내일 04:00'])

    def test_eta_past_gets_class_and_suffix(self):
        result = self.render_dom(
            [mini_item('a', 'now', estimate=30)], view='2026-10-03T11:00:00+09:00'
        )
        eta = self.find(result, 'eta')
        self.assertEqual([n['cls'] for n in eta], ['eta past'])
        self.assertEqual([n['text'] for n in eta], ['완료 예상 10:30 (지남)'])

    def test_eta_absent_without_estimate(self):
        self.assertEqual(self.find(self.render_dom([mini_item('a', 'done')]), 'eta'), [])

    def test_node_when_texts(self):
        items = [
            mini_item('a', 'done', startedAt='2026-10-03T09:00:00+09:00', doneAt='2026-10-03T10:30:00+09:00'),
            mini_item('b', 'now', startedAt='2026-10-03T09:30:00+09:00', estimate=30),
            mini_item('c', 'left', estimate=45),
            mini_item('d', 'side', estimate=90),
            mini_item('e', 'left'),
        ]
        result = self.render_dom(items)
        self.assertEqual(self.when_text(result, 'a'), ('when', '1시간 30분'))
        self.assertEqual(self.when_text(result, 'b'), ('when when-now', '~10:30'))
        self.assertEqual(self.when_text(result, 'c'), ('when', '~45분'))
        self.assertEqual(self.when_text(result, 'd'), ('when', '~1시간 30분'))
        self.assertIsNone(self.when_text(result, 'e'))

    def test_now_card_etime_rows(self):
        result = self.render_dom(
            [mini_item('a', 'now', startedAt='2026-10-03T09:00:00+09:00', estimate=30)]
        )
        etime = self.find(result, 'etime')
        self.assertEqual(len(etime), 1)
        rows = [k for k in etime[0]['kids'] if 'etime-row' in (k.get('cls') or '').split()]
        self.assertEqual(len(rows), 2)
        self.assertEqual([s['text'] for s in rows[0]['kids']], ['시작 09:00', '완료 예상 10:30'])
        self.assertEqual(rows[1]['kids'][0]['text'], '경과 1시간')

    def test_now_card_etime_clamps_future_start(self):
        result = self.render_dom(
            [mini_item('a', 'now', startedAt='2026-10-03T11:00:00+09:00', estimate=30)]
        )
        rows = [k for k in self.find(result, 'etime')[0]['kids'] if 'etime-row' in (k.get('cls') or '').split()]
        self.assertEqual(rows[1]['kids'][0]['text'], '경과 0분')

    def test_lane_band_height_follows_time_rows(self):
        with_time = [
            mini_item('a', 'done', lane=0, startedAt='2026-10-03T09:00:00+09:00', doneAt='2026-10-03T10:00:00+09:00'),
            mini_item('b', 'left', lane=1, estimate=30),
        ]
        bands = self.find(self.render_dom(with_time, {'lanes': ['L1', 'L2']}), 'lane-band')
        self.assertEqual([b['style']['height'] for b in bands], ['176px', '176px'])

        without_time = [mini_item('a', 'done', lane=0), mini_item('b', 'left', lane=1)]
        bands = self.find(self.render_dom(without_time, {'lanes': ['L1', 'L2']}), 'lane-band')
        self.assertEqual([b['style']['height'] for b in bands], ['142px', '142px'])

    def test_lane_band_state_classes(self):
        items = [
            mini_item('a', 'now', lane=0),
            mini_item('b', 'done', lane=1),
            mini_item('c', 'left', lane=2),
            mini_item('d', 'done', lane=3),
            mini_item('e', 'blocked', lane=3),
        ]
        result = self.render_dom(items, {'lanes': ['L1', 'L2', 'L3', 'L4']})
        classes = [(b.get('cls') or '').split() for b in self.find(result, 'lane-band')]
        self.assertEqual(len(classes), 4)
        self.assertIn('live', classes[0])
        self.assertIn('done', classes[1])
        self.assertEqual([c for c in classes[2] if c != 'lane-band'], [])
        self.assertIn('blocked', classes[3])

    def test_edge_flow_only_on_done_edges(self):
        items = [
            mini_item('a', 'done', lane=0),
            mini_item('b', 'done', lane=0),
            mini_item('c', 'now', lane=0),
            mini_item('d', 'left', lane=0),
        ]
        extra = {'edges': [['a', 'b'], ['b', 'c'], ['c', 'd']]}
        result = self.render_dom(items, extra)
        self.assertEqual(len(self.find(result, 'edge')), 3)
        self.assertEqual(len(self.find(result, 'edge-flow')), 1)

    def test_now_node_has_orbit(self):
        result = self.render_dom([mini_item('a', 'now')])
        fnode = self.by_id(result, 'a')
        circle = next(k for k in fnode['kids'] if 'node' in (k.get('cls') or '').split())
        self.assertEqual(
            [k.get('cls') for k in circle.get('kids', []) if 'orbit' in (k.get('cls') or '').split()],
            ['orbit'],
        )


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_data(self, data, name='data.json'):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    def out(self, name='out.html'):
        return os.path.join(self.tmp, name)

    def test_example_renders_without_placeholders(self):
        out = self.out()
        r = run_render(EXAMPLE, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'rendered: ' + out)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        self.assertNotIn('__PROGRESS_DATA__', html)
        self.assertNotIn('__PROGRESS_TITLE__', html)
        self.assertIn('SHOP-128 진행 상황', html)

    def test_input_data_file_is_left_untouched(self):
        path = self.write_data(load_example())
        with open(path, 'rb') as f:
            before = f.read()
        r = run_render(path, self.out())
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_refresh_meta_present(self):
        out = self.out()
        self.assertEqual(run_render(EXAMPLE, out).returncode, 0)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        self.assertIn('<meta http-equiv="refresh" content="15">', html)

    def test_existing_title_is_preserved(self):
        out = self.out()
        with open(out, 'w', encoding='utf-8') as f:
            f.write('<!doctype html><html><head><title>[vault2] 나만의 제목 · 진행 상황</title></head></html>')
        r = run_render(EXAMPLE, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        self.assertIn('<title>[vault2] 나만의 제목 · 진행 상황</title>', html)
        self.assertNotIn('SHOP-128 진행 상황', html)

    def test_script_end_tag_in_data_does_not_close_early(self):
        data = load_example()
        data['items'][0]['body'] = '본문 </script><script>window.__x=1</script> 끝'
        data['footer'] = '<!-- 주석 -->'
        out = self.out()
        path = self.write_data(data)
        r = run_render(path, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        block = data_block(html)
        self.assertNotIn('</script>', block)
        self.assertIn('<\\/script>', block)
        parsed = parse_block(block)
        self.assertIn('</script>', parsed['items'][0]['body'])
        self.assertIn('<!-- 주석 -->', parsed['footer'])
        self.assertEqual(html.count('<script id="progress-data"'), 1)

    def test_now_twice_is_rejected(self):
        data = load_example()
        data['items'][3]['state'] = 'now'
        data['items'][4]['state'] = 'now'
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('now', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_unknown_edge_id_is_rejected(self):
        data = load_example()
        data['edges'] = data['edges'] + [['s2v', 'nope']]
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('nope', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_bad_state_is_rejected(self):
        data = load_example()
        data['items'][0]['state'] = 'finished'
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('finished', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_non_string_goal_is_rejected(self):
        data = load_example()
        data['goal'] = 1
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('goal', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_duplicate_id_and_empty_items_are_rejected(self):
        data = load_example()
        data['items'][1]['id'] = data['items'][0]['id']
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('중복', r.stderr)

        empty = load_example()
        empty['items'] = []
        r = run_render(self.write_data(empty, 'empty.json'), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('items', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_failed_render_leaves_existing_out_untouched(self):
        out = self.out()
        self.assertEqual(run_render(EXAMPLE, out).returncode, 0)
        with open(out, encoding='utf-8') as f:
            before = f.read()
        broken = load_example()
        broken['items'][0]['state'] = 'nope'
        r = run_render(self.write_data(broken), out)
        self.assertEqual(r.returncode, 1)
        with open(out, encoding='utf-8') as f:
            self.assertEqual(f.read(), before)

    def test_links_and_meta_object_carry_into_page(self):
        data = load_example()
        data['links'] = {'SHOP-999': 'https://example.atlassian.net/browse/SHOP-999'}
        data['meta'] = ['webhook-retry-20261001', {'text': 'staging', 'href': 'https://example.com/deploy/1'}]
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            parsed = parse_block(data_block(f.read()))
        self.assertEqual(parsed['links'], {'SHOP-999': 'https://example.atlassian.net/browse/SHOP-999'})
        self.assertEqual(parsed['meta'][1], {'text': 'staging', 'href': 'https://example.com/deploy/1'})

    def test_links_value_must_be_http_url(self):
        data = load_example()
        data['links'] = {'SHOP-130': 'javascript:alert(1)'}
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('links[SHOP-130]', r.stderr)
        self.assertIn('http(s)', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_links_must_be_object(self):
        data = load_example()
        data['links'] = ['https://example.com']
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('links', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_links_key_must_not_be_empty(self):
        data = load_example()
        data['links'] = {'': 'https://example.com'}
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('links', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_hrefs_must_be_http_urls(self):
        def bad_key_href(d):
            d['keyHref'] = 'javascript:alert(1)'

        def bad_meta_href(d):
            d['meta'] = [{'text': 'staging', 'href': 'ftp://example.com/deploy'}]

        def bad_evidence_href(d):
            d['items'][1]['evidence'][0]['href'] = 'mailto:ops@example.com'

        def bad_substep_href(d):
            d['items'][3]['substeps'][0]['href'] = 'file:///etc/passwd'

        def bad_changes_evidence_href(d):
            d['changes'][0]['evidence'] = [{'text': '측정 대시보드', 'href': 'javascript:alert(1)'}]

        cases = (
            ('keyHref', bad_key_href, 'keyHref'),
            ('meta[0].href', bad_meta_href, 'meta[0].href'),
            ('items[1].evidence[0].href', bad_evidence_href, 'items[1].evidence[0].href'),
            ('items[3].substeps[0].href', bad_substep_href, 'items[3].substeps[0].href'),
            ('changes[0].evidence[0].href', bad_changes_evidence_href, 'changes[0].evidence[0].href'),
        )
        for name, mutate, where in cases:
            with self.subTest(case=name):
                data = load_example()
                mutate(data)
                out = self.out()
                r = run_render(self.write_data(data), out)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(where, r.stderr)
                self.assertFalse(os.path.exists(out))

    def test_meta_entry_must_be_string_or_text_object(self):
        data = load_example()
        data['meta'] = ['ok', 3]
        out = self.out()
        r = run_render(self.write_data(data), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('meta[1]', r.stderr)
        self.assertFalse(os.path.exists(out))

        data = load_example()
        data['meta'] = [{'href': 'https://example.com/deploy'}]
        r = run_render(self.write_data(data, 'meta2.json'), out)
        self.assertEqual(r.returncode, 1)
        self.assertIn('meta[0].text', r.stderr)

    def test_template_defines_source_icons(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            tpl = f.read()
        for name in ('i-run', 'i-chat', 'i-doc', 'i-link', 'i-chart'):
            with self.subTest(icon=name):
                self.assertIn('<symbol id="%s"' % name, tpl)

    def test_template_has_single_data_slot(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            tpl = f.read()
        self.assertEqual(tpl.count('__PROGRESS_DATA__'), 1)
        self.assertEqual(tpl.count('__PROGRESS_TITLE__'), 1)


class RenderThemeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-theme-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = os.path.join(self.tmp, 'config.json')

    def save_theme(self, value):
        with open(self.config, 'w', encoding='utf-8') as f:
            json.dump({'theme': value}, f)

    def render(self, theme=None, config_path=None):
        out = os.path.join(self.tmp, 'out.html')
        return run_render(EXAMPLE, out, theme=theme, config_path=config_path), out

    def rendered_tag(self, out):
        with open(out, encoding='utf-8') as f:
            return html_tag(f.read())

    def test_theme_dark_sets_html_attribute(self):
        r, out = self.render(theme='dark')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(out), '<html lang="ko" data-theme="dark">')

    def test_theme_light_sets_html_attribute(self):
        r, out = self.render(theme='light')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(out), '<html lang="ko" data-theme="light">')

    def test_theme_system_leaves_html_untouched(self):
        r, out = self.render(theme='system')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(out), '<html lang="ko">')

    def test_saved_theme_applies_without_flag(self):
        self.save_theme('dark')
        r, out = self.render(config_path=self.config)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(out), '<html lang="ko" data-theme="dark">')

    def test_flag_beats_saved_theme(self):
        self.save_theme('light')
        r, out = self.render(theme='dark', config_path=self.config)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(out), '<html lang="ko" data-theme="dark">')

    def test_saved_system_leaves_html_untouched(self):
        self.save_theme('system')
        r, out = self.render(config_path=self.config)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(out), '<html lang="ko">')

    def test_invalid_theme_flag_exits_1(self):
        r, out = self.render(theme='nope')
        self.assertEqual(r.returncode, 1)
        self.assertIn('nope', r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_extra_themes_set_html_attribute(self):
        for theme in EXTRA_THEMES:
            with self.subTest(theme=theme):
                r, out = self.render(theme=theme)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.rendered_tag(out), '<html lang="ko" data-theme="%s">' % theme)


class TemplateThemeTest(unittest.TestCase):
    def setUp(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            self.tpl = f.read()

    def block(self, theme):
        m = re.search(r':root\[data-theme="%s"\]\s*\{(.*?)\}' % theme, self.tpl, re.S)
        self.assertIsNotNone(m, ':root[data-theme="%s"] 블록을 찾지 못했다' % theme)
        return m.group(1)

    def test_extra_theme_blocks_exist_once(self):
        for theme in EXTRA_THEMES:
            with self.subTest(theme=theme):
                self.assertEqual(self.tpl.count(':root[data-theme="%s"]' % theme), 1)

    def test_theme_blocks_come_after_dark_blocks(self):
        last_dark = self.tpl.index(':root[data-theme="dark"]')
        for theme in EXTRA_THEMES:
            with self.subTest(theme=theme):
                self.assertGreater(self.tpl.index(':root[data-theme="%s"]' % theme), last_dark)

    def test_theme_blocks_define_every_token(self):
        for theme in EXTRA_THEMES:
            body = self.block(theme)
            for token in THEME_TOKENS:
                with self.subTest(theme=theme, token=token):
                    self.assertIn(token + ':', body)

    def test_css_rules_do_not_hardcode_state_colors(self):
        style = re.search(r'<style>(.*?)</style>', self.tpl, re.S).group(1)
        body = re.sub(r':root[^{]*\{[^}]*\}', '', style)
        for color in ('#059669', '#f97316', '#dc2626'):
            with self.subTest(color=color):
                self.assertNotIn(color, body)


class OpenScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-open-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = os.path.join(self.tmp, 'config', 'config.json')

    def write_file(self, name, text='<!doctype html><html></html>'):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def fake_orca_dir(self):
        d = os.path.join(self.tmp, 'bin')
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, 'orca')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(path, 0o755)
        return d

    def save_config(self, value):
        os.makedirs(os.path.dirname(self.config), exist_ok=True)
        with open(self.config, 'w', encoding='utf-8') as f:
            json.dump({'open': value}, f)
        return self.config

    def run_open(self, path, worktree_id=None, path_prefix=None, mode=None, config=None):
        env = dict(os.environ)
        env['PROGRESS_OPEN_DRY'] = '1'
        env['DEADHD_CONFIG'] = self.config if config is None else config
        env.pop('ORCA_WORKTREE_ID', None)
        env.pop('XDG_CONFIG_HOME', None)
        if worktree_id is not None:
            env['ORCA_WORKTREE_ID'] = worktree_id
        if path_prefix is not None:
            env['PATH'] = path_prefix + os.pathsep + env.get('PATH', '')
        cmd = ['bash', os.path.join(HERE, 'open.sh')]
        if mode is not None:
            cmd += ['--mode', mode]
        cmd.append(path)
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def test_dry_with_worktree_id_and_orca_opens_tab(self):
        page = self.write_file('page.html')
        r = self.run_open(page, worktree_id='wt-1', path_prefix=self.fake_orca_dir())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('opened: orca-tab', r.stdout)

    def test_dry_without_worktree_id_skips_orca(self):
        page = self.write_file('page.html')
        r = self.run_open(page, path_prefix=self.fake_orca_dir())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('orca', r.stdout.lower())
        self.assertTrue(
            'opened: browser' in r.stdout or 'opened: none' in r.stdout, r.stdout
        )

    def test_missing_file_exits_2(self):
        r = self.run_open(os.path.join(self.tmp, 'nope.html'))
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    def test_dry_url_encodes_space(self):
        page = self.write_file('a b.html')
        r = self.run_open(page, worktree_id='wt-1', path_prefix=self.fake_orca_dir())
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [l for l in r.stdout.splitlines() if l.startswith('dry: ')]
        self.assertTrue(lines, r.stdout)
        self.assertIn('%20', lines[0])

    def test_mode_browser_skips_orca(self):
        page = self.write_file('page.html')
        r = self.run_open(
            page, worktree_id='wt-1', path_prefix=self.fake_orca_dir(), mode='browser'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('orca', r.stdout.lower())
        self.assertIn('opened: browser', r.stdout)

    def test_mode_desktop_prints_path(self):
        page = self.write_file('page.html')
        r = self.run_open(page, worktree_id='wt-1', path_prefix=self.fake_orca_dir(), mode='desktop')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'opened: desktop ' + page)

    def test_mode_orca_without_worktree_id_uses_fake_orca(self):
        page = self.write_file('page.html')
        r = self.run_open(page, path_prefix=self.fake_orca_dir(), mode='orca')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('opened: orca-tab', r.stdout)

    def test_saved_desktop_applies_without_mode(self):
        page = self.write_file('page.html')
        self.save_config('desktop')
        r = self.run_open(page, worktree_id='wt-1', path_prefix=self.fake_orca_dir())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'opened: desktop ' + page)

    def test_mode_argument_beats_saved_config(self):
        page = self.write_file('page.html')
        self.save_config('desktop')
        r = self.run_open(
            page, worktree_id='wt-1', path_prefix=self.fake_orca_dir(), mode='browser'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('desktop', r.stdout)
        self.assertIn('opened: browser', r.stdout)

    def test_invalid_mode_exits_2(self):
        page = self.write_file('page.html')
        r = self.run_open(page, mode='nope')
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())


class ConfigScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-config-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'nested', 'config.json')

    def run_config(self, *args):
        env = dict(os.environ)
        env['DEADHD_CONFIG'] = self.path
        env.pop('XDG_CONFIG_HOME', None)
        return subprocess.run(
            [sys.executable, os.path.join(HERE, 'config.py'), *args],
            capture_output=True, text=True, env=env,
        )

    def test_get_reports_unset_when_file_missing(self):
        r = self.run_config('get', 'open')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'unset')

    def test_set_then_get_returns_value(self):
        r = self.run_config('set', 'open', 'orca')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('saved: open=orca', r.stdout)
        self.assertEqual(self.run_config('get', 'open').stdout.strip(), 'orca')

    def test_set_invalid_value_exits_2(self):
        r = self.run_config('set', 'open', 'nope')
        self.assertEqual(r.returncode, 2)
        self.assertIn('nope', r.stderr)
        self.assertFalse(os.path.exists(self.path))

    def test_set_preserves_other_keys(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'open': 'auto', 'keep': 'me'}, f)
        r = self.run_config('set', 'open', 'browser')
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.path, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data, {'open': 'browser', 'keep': 'me'})

    def test_unknown_saved_value_is_unset_with_warning(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'open': 'weird'}, f)
        r = self.run_config('get', 'open')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), 'unset')
        self.assertTrue(r.stderr.strip())

    def test_theme_get_reports_unset_when_file_missing(self):
        r = self.run_config('get', 'theme')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'unset')

    def test_theme_set_then_get_returns_value(self):
        r = self.run_config('set', 'theme', 'dark')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('saved: theme=dark', r.stdout)
        self.assertEqual(self.run_config('get', 'theme').stdout.strip(), 'dark')

    def test_theme_set_invalid_value_exits_2(self):
        r = self.run_config('set', 'theme', 'nope')
        self.assertEqual(r.returncode, 2)
        self.assertIn('nope', r.stderr)
        self.assertFalse(os.path.exists(self.path))

    def test_theme_set_accepts_extra_theme(self):
        r = self.run_config('set', 'theme', 'neon')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('saved: theme=neon', r.stdout)
        self.assertEqual(self.run_config('get', 'theme').stdout.strip(), 'neon')

    def test_theme_set_preserves_open_value(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'open': 'orca'}, f)
        r = self.run_config('set', 'theme', 'light')
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.path, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data, {'open': 'orca', 'theme': 'light'})

    def test_unknown_key_exits_2(self):
        self.assertEqual(self.run_config('get', 'nope').returncode, 2)
        self.assertEqual(self.run_config('set', 'nope', 'dark').returncode, 2)

    def test_path_prints_config_path(self):
        r = self.run_config('path')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), self.path)

    def test_usage_error_exits_2(self):
        self.assertEqual(self.run_config('get').returncode, 2)
        self.assertEqual(self.run_config().returncode, 2)


class ShareScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-share-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_file(self, name='page.html'):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('<!doctype html><html></html>')
        return path

    def make_orca(self, out, rc=0, log_path=None):
        d = os.path.join(self.tmp, 'bin')
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, 'orca')
        lines = ['#!/bin/sh']
        if log_path is not None:
            lines.append('printf "%%s\\n" "$*" >> %s' % shlex.quote(log_path))
        lines.append('printf "%%s\\n" %s' % shlex.quote(out))
        lines.append('exit %d' % rc)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        os.chmod(path, 0o755)
        return d

    def bare_path(self):
        d = os.path.join(self.tmp, 'bare-bin')
        os.makedirs(d, exist_ok=True)
        for tool in ('bash', 'python3'):
            link = os.path.join(d, tool)
            if not os.path.exists(link):
                os.symlink(shutil.which(tool), link)
        return d

    def run_share(self, args, prefix=None, path=None):
        env = dict(os.environ)
        if path is not None:
            env['PATH'] = path
        else:
            env['PATH'] = prefix + os.pathsep + env.get('PATH', '')
        return subprocess.run(
            ['bash', os.path.join(HERE, 'share.sh')] + list(args),
            capture_output=True, text=True, env=env,
        )

    def test_success_prints_share_url(self):
        page = self.write_file()
        d = self.make_orca('{"ok":true,"result":{"shareUrl":"https://example.com/a"}}')
        r = self.run_share([page], prefix=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'shared: https://example.com/a')

    def test_update_passes_update_arguments(self):
        page = self.write_file()
        log = os.path.join(self.tmp, 'args.log')
        d = self.make_orca(
            '{"ok":true,"result":{"shareUrl":"https://example.com/b"}}', log_path=log
        )
        r = self.run_share(['--update', page], prefix=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(log, encoding='utf-8') as f:
            recorded = f.read().strip()
        self.assertEqual(recorded, 'artifacts update %s --json' % page)

    def test_failure_json_falls_back_to_browser(self):
        page = self.write_file()
        d = self.make_orca('{"ok":false,"error":{"code":"unauthorized"}}', rc=1)
        r = self.run_share([page], prefix=d)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout.strip(), 'fallback: browser')
        self.assertIn('unauthorized', r.stderr)

    def test_missing_orca_falls_back_to_browser(self):
        page = self.write_file()
        r = self.run_share([page], path=self.bare_path())
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout.strip(), 'fallback: browser')
        self.assertIn('orca not found', r.stderr)

    def test_missing_file_exits_2(self):
        page = os.path.join(self.tmp, 'nope.html')
        r = self.run_share([page], prefix=self.make_orca('{"ok":true}'))
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())


class SkillDocTest(unittest.TestCase):
    def test_skill_md_has_no_personal_paths(self):
        # 검사 대상 문자열을 조각으로 만들어, 이 파일 자신이 저장소 grep 에 걸리지 않게 한다.
        needles = ('agent' + '-lanes', 'eli' + '5o', 'write' + '-like' + '-me')
        with open(os.path.join(HERE, 'SKILL.md'), encoding='utf-8') as f:
            text = f.read()
        for needle in needles:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, text)


if __name__ == '__main__':
    unittest.main()
