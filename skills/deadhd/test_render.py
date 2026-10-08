#!/usr/bin/env python3
"""render.py 의 렌더 결과와 입력 검증을 확인한다."""
import json
import os
import pathlib
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, 'render.py')
STATE = os.path.join(HERE, 'state.py')
HUB = os.path.join(HERE, 'hub.py')
SERVE = os.path.join(HERE, 'serve.py')
TEMPLATE = os.path.join(HERE, 'template.html')
HUB_TEMPLATE = os.path.join(HERE, 'hub.html')
THEMES_CSS = os.path.join(HERE, 'themes.css')
EXAMPLE = os.path.join(HERE, 'example.json')
MISSING_CONFIG = os.path.join(tempfile.gettempdir(), 'deadhd-no-such-config', 'config.json')
# 테스트 렌더가 사용자의 실제 허브(/tmp/deadhd-hub.html)를 덮어쓰지 않게 임시 경로로 돌린다.
TEST_HUB = os.path.join(tempfile.gettempdir(), 'deadhd-test-hub.html')

EXTRA_THEMES = ('neon', 'synthwave', 'matrix', 'nord', 'paper', 'sakura', 'ink')
FONT_PRESETS = (
    'pretendard', 'noto-sans', 'plex-sans', 'gothic-a1', 'nanum-gothic', 'noto-serif',
    'nanum-myeongjo', 'hahmlet', 'gowun-batang', 'do-hyeon', 'black-han-sans',
)
THEME_TOKENS = (
    '--bg', '--bg-2', '--card', '--card-line', '--ink', '--ink-2', '--ink-3',
    '--done', '--done-2', '--done-deep', '--now', '--now-2', '--now-deep', '--now-hi',
    '--side', '--side-hi', '--left', '--blocked', '--blocked-2', '--blocked-deep',
    '--track', '--tip', '--count-end', '--scroll', '--scroll-hover',
    '--glow-a', '--glow-b', '--glow-c',
)


def run_render(data_path, out_path, theme=None, config_path=None, env_extra=None, session=None):
    env = dict(os.environ)
    env['DEADHD_CONFIG'] = config_path if config_path is not None else MISSING_CONFIG
    # 세션·이력·상태가 이 테스트를 실행한 세션에서 새어 들어오지 않게 한다.
    for key in ('XDG_CONFIG_HOME', 'CLAUDE_CODE_SESSION_ID', 'DEADHD_STATE_DIR', 'DEADHD_HISTORY'):
        env.pop(key, None)
    env['DEADHD_HUB'] = TEST_HUB
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, RENDER]
    if theme is not None:
        cmd += ['--theme', theme]
    if session is not None:
        cmd += ['--session', session]
    cmd += [data_path, out_path]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def run_state(payload, state_dir, env_extra=None, raw=None):
    env = dict(os.environ)
    env['DEADHD_CONFIG'] = MISSING_CONFIG
    env.pop('XDG_CONFIG_HOME', None)
    env['DEADHD_STATE_DIR'] = state_dir
    env['DEADHD_HUB'] = TEST_HUB
    if env_extra:
        env.update(env_extra)
    text = raw if raw is not None else json.dumps(payload, ensure_ascii=False)
    return subprocess.run([sys.executable, STATE], input=text, capture_output=True, text=True, env=env)


def load_valid_session_id():
    """state.py 를 import 하면 sys.path 와 __pycache__ 를 건드려야 해서 소스만 실행해 꺼낸다."""
    namespace = {'__name__': 'state_under_test', '__file__': STATE}
    with open(STATE, encoding='utf-8') as f:
        exec(compile(f.read(), STATE, 'exec'), namespace)
    return namespace['valid_session_id']


VALID_SESSION_ID = load_valid_session_id()


def load_example():
    with open(EXAMPLE, encoding='utf-8') as f:
        return json.load(f)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


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
  const classes = function () { return self._cls ? self._cls.split(' ').filter(Boolean) : []; };
  this.classList = {
    add: function (c) { if (!classes().includes(c)) self._cls = classes().concat(c).join(' '); },
    remove: function (c) { self._cls = classes().filter(x => x !== c).join(' '); },
    contains: function (c) { return classes().includes(c); },
    toggle: function (c, force) {
      const on = force === undefined ? !classes().includes(c) : !!force;
      if (on) this.add(c); else this.remove(c);
      return on;
    }
  };
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
El.prototype.addEventListener = function (type, fn) { (this._on || (this._on = {}))[type] = fn; };
El.prototype.click = function () { const fn = this._on && this._on.click; if (fn) fn(); };
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
  if (n.attrs && Object.keys(n.attrs).length) o.attrs = Object.assign({}, n.attrs);
  const style = {};
  for (const k in n.style) { if (typeof n.style[k] !== 'function') style[k] = n.style[k]; }
  if (Object.keys(style).length) o.style = style;
  if (n.children.length) o.kids = n.children.map(serialize);
  return o;
}

const probeSrc = "\n  globalThis.__linkProbe = { httpHref: httpHref, linkElInfo: function (h) { var n = linkEl(h, document.createTextNode('t'), 'lnk'); return { tag: n.tagName, href: n.href == null ? null : n.href }; }, fmtClock: function (t, v) { return fmtClock(t, v); }, fmtDur: fmtDur, compactRender: function (v, oe, chip) { vst.v = v; vst.oe = oe; vst.chip = chip; return RENDER[v](); }, i18nKeys: (function () { function flat(o, p) { var out = []; Object.keys(o).forEach(function (k) { var v = o[k], q = p ? p + '.' + k : k; if (v && typeof v === 'object') out = out.concat(flat(v, q)); else out.push(q); }); return out.sort(); } return { ko: flat(I18N.ko, ''), en: flat(I18N.en, '') }; })() };\n";
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
if (process.argv[6]) doc.getElementById('flow').clientWidth = Number(process.argv[6]);
const ss = {
  _m: {},
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(this._m, k) ? this._m[k] : null; },
  setItem: function (k, v) { this._m[k] = String(v); }
};
const seed = process.argv[7] ? JSON.parse(fs.readFileSync(process.argv[7], 'utf8')) : null;
if (seed) Object.assign(ss._m, seed);
const run = new Function('document', 'matchMedia', 'sessionStorage', code);
run(doc, function () { return { matches: false, addEventListener: function () {} }; }, ss);

const probe = globalThis.__linkProbe;
function info(h) { return probe.linkElInfo(h); }

const nodes = {};
for (const entry of doc._byId) {
  if (entry[0] === 'progress-data') continue;
  nodes[entry[0]] = serialize(entry[1]);
}

const cases = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], 'utf8')) : null;

// 클릭 한 번으로 상태가 store 에 남는지 보려면 핸들러를 실제로 불러야 한다.
function matchesClick(n, spec) {
  if (spec.cls && !(n.className || '').split(' ').includes(spec.cls)) return false;
  if (spec.text != null && textOf(n) !== spec.text) return false;
  if (spec.lane != null && (n.dataset || {}).lane !== spec.lane) return false;
  return true;
}
function clickSpec(spec) {
  const found = [];
  for (const entry of doc._byId) {
    if (entry[0] === 'progress-data') continue;
    (function walk(n) {
      if (matchesClick(n, spec)) found.push(n);
      for (const kid of n.children) walk(kid);
    })(entry[1]);
  }
  const node = found[spec.nth || 0];
  if (!node) throw new Error('클릭할 노드를 찾지 못했다: ' + JSON.stringify(spec));
  node.click();
}
for (const spec of (cases && cases.clicks) || []) clickSpec(spec);

const fmt = cases ? {
  clock: (cases.clock || []).map(c => probe.fmtClock(c[0], c[1])),
  dur: (cases.dur || []).map(m => probe.fmtDur(m))
} : null;

process.stdout.write(JSON.stringify({
  fmt: fmt,
  compact: cases && cases.compact ? probe.compactRender(cases.compact.v, cases.compact.oe, cases.compact.chip) : null,
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
    link_number: info(123),
    i18nKeys: probe.i18nKeys
  },
  nodes: nodes,
  storage: ss._m
}));
'''


def script_block(html):
    blocks = re.findall(r'<script>(.*?)</script>', html, re.S)
    assert len(blocks) == 1, '본문 script 블록이 정확히 하나가 아니다: %d개' % len(blocks)
    return blocks[0]


# 렌더된 허브 HTML 의 스크립트를 그대로 실행해 만든 DOM 을 꺼낸다.
HUB_HARNESS = r'''
const fs = require('fs');
const code = fs.readFileSync(process.argv[2], 'utf8');
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

function makeDocument(raw) {
  const byId = new Map();
  const doc = {
    createElement: function (t) { return new El(t); },
    createTextNode: function (t) { return textNode(t); },
    createDocumentFragment: function () { return new El('#fragment'); },
    getElementById: function (id) {
      if (!byId.has(id)) { const e = new El('div'); e.id = id; byId.set(id, e); }
      return byId.get(id);
    }
  };
  doc.getElementById('hub-data').textContent = raw;
  doc._byId = byId;
  return doc;
}

function serialize(n) {
  if (n.tag === '#text') return { t: '#text', text: n.text };
  const o = { t: n.tagName, text: textOf(n) };
  if (n.id) o.id = n.id;
  if (n.className) o.cls = n.className;
  if (n.href != null) o.href = n.href;
  if (n.hidden) o.hidden = true;
  if (n.attrs && Object.keys(n.attrs).length) o.attrs = Object.assign({}, n.attrs);
  const style = {};
  for (const k in n.style) { if (typeof n.style[k] !== 'function') style[k] = n.style[k]; }
  if (Object.keys(style).length) o.style = style;
  if (n.children.length) o.kids = n.children.map(serialize);
  return o;
}

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

const fixedNow = process.argv[4] || '';
if (fixedNow) fixClock(fixedNow);

const doc = makeDocument(rawData);
new Function('document', code)(doc);

const nodes = {};
for (const entry of doc._byId) {
  if (entry[0] === 'hub-data') continue;
  nodes[entry[0]] = serialize(entry[1]);
}
process.stdout.write(JSON.stringify({ nodes }));
'''


def hub_data_block(html):
    m = re.search(r'<script id="hub-data" type="application/json">(.*?)</script>', html, re.S)
    assert m is not None, '허브 데이터 script 블록을 찾지 못했다'
    return m.group(1)


def run_hub(state_dir, hub_path=None, theme=None, font=None, out=None, env_extra=None):
    env = dict(os.environ)
    env['DEADHD_CONFIG'] = MISSING_CONFIG
    env.pop('XDG_CONFIG_HOME', None)
    env['DEADHD_STATE_DIR'] = state_dir
    env['DEADHD_HUB'] = hub_path if hub_path is not None else TEST_HUB
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, HUB]
    if theme is not None:
        cmd += ['--theme', theme]
    if font is not None:
        cmd += ['--font', font]
    if out is not None:
        cmd.append(out)
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def run_hub_harness(html, fixed_now=None):
    with tempfile.TemporaryDirectory(prefix='progress-hub-') as d:
        for name, text in (('harness.js', HUB_HARNESS), ('script.js', script_block(html)),
                           ('data.txt', hub_data_block(html))):
            with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
                f.write(text)
        env = dict(os.environ, TZ='Asia/Seoul')
        cmd = [NODE, os.path.join(d, 'harness.js'), os.path.join(d, 'script.js'),
               os.path.join(d, 'data.txt'), fixed_now or '']
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=d, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def run_linkify_harness(html, cases=None, fixed_now=None, flow_width=None, storage=None):
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
        storage_path = ''
        if storage is not None:
            storage_path = os.path.join(d, 'storage.json')
            with open(storage_path, 'w', encoding='utf-8') as f:
                json.dump(storage, f, ensure_ascii=False)
        # fmtClock 은 로컬 날짜를 보므로 실행 시차를 고정해 기대값을 결정적으로 만든다.
        if cases is not None or fixed_now is not None:
            env['TZ'] = 'Asia/Seoul'
        cmd += [cases_path, fixed_now or '', str(flow_width or ''), storage_path]
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
        r = run_render(path, out, env_extra={'DEADHD_NOW': now} if now else {})
        if r.returncode != 0:
            return r, None
        with open(out, encoding='utf-8') as f:
            return r, parse_block(data_block(f.read()))

    def render_file(self, path):
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            return parse_block(data_block(f.read()))

    def render_with_mtime(self, items, mtime):
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'title': 'T', 'items': items}, f, ensure_ascii=False)
        os.utime(path, (mtime, mtime))
        return path, self.render_file(path)

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

    def test_eta_baseline_is_the_data_file_mtime(self):
        mtime = 1759500000
        _, parsed = self.render_with_mtime(
            [mini_item('a', 'now', estimate=30), mini_item('b', 'left', estimate=15)], mtime
        )
        base = datetime.fromtimestamp(mtime).astimezone()
        self.assertEqual(parsed['dataAt'], base.isoformat(timespec='seconds'))
        self.assertEqual(parsed['eta'], (base + timedelta(minutes=45)).isoformat(timespec='seconds'))

    def test_eta_does_not_move_when_only_the_render_time_changes(self):
        path, first = self.render_with_mtime([mini_item('a', 'now', estimate=30)], 1759500000)
        time.sleep(1.05)
        second = self.render_file(path)
        self.assertNotEqual(second['renderedAt'], first['renderedAt'])
        self.assertEqual(second['dataAt'], first['dataAt'])
        self.assertEqual(second['eta'], first['eta'])


class TemplateTimeFormatTest(unittest.TestCase):
    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-fmt-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cases(self, cases, extra=None):
        data = {'title': 'T', 'items': [mini_item('a', 'done')]}
        if extra:
            data.update(extra)
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
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

    def test_fmt_en(self):
        stamp = '2026-10-03T01:00:00+09:00'
        cases = {
            'clock': [
                ['2026-10-03T03:52:00+09:00', stamp],
                ['2026-10-04T03:52:00+09:00', stamp],
                ['2026-10-05T04:57:00+09:00', stamp],
                ['2026-09-07T04:57:00+09:00', stamp],
            ],
            'dur': [59, 60, 70, 1439, 1440, 1560],
        }
        fmt = self.run_cases(cases, extra={'lang': 'en'})
        self.assertEqual(fmt['clock'], ['03:52', 'Tomorrow 03:52', '10/05 04:57', '9/07 04:57'])
        self.assertEqual(fmt['dur'], ['59m', '1h', '1h 10m', '23h 59m', '1d', '1d 2h'])


class TemplateDomStateTest(unittest.TestCase):
    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-dom-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def render_dom(self, items, extra=None, now=FIXED_NOW, view=FIXED_NOW, flow_width=None):
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
            return run_linkify_harness(f.read(), fixed_now=view, flow_width=flow_width)

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

    def test_past_node_when_gets_suffix_and_class(self):
        result = self.render_dom(
            [mini_item('a', 'now', startedAt='2026-10-03T09:00:00+09:00', estimate=30)],
            view='2026-10-03T11:00:00+09:00'
        )
        cls, text = self.when_text(result, 'a')
        self.assertEqual(text, '~10:30 (지남)')
        self.assertIn('when-past', cls.split())
        self.assertIn('when-now', cls.split())

    def test_lane_band_height_follows_time_rows(self):
        with_time = [
            mini_item('a', 'done', lane=0, startedAt='2026-10-03T09:00:00+09:00', doneAt='2026-10-03T10:00:00+09:00'),
            mini_item('b', 'left', lane=1, estimate=30),
        ]
        bands = self.find(self.render_dom(with_time, {'lanes': ['L1', 'L2']}), 'lane-band')
        self.assertEqual([b['style']['height'] for b in bands], ['190px', '190px'])

        without_time = [mini_item('a', 'done', lane=0), mini_item('b', 'left', lane=1)]
        bands = self.find(self.render_dom(without_time, {'lanes': ['L1', 'L2']}), 'lane-band')
        self.assertEqual([b['style']['height'] for b in bands], ['156px', '156px'])

        no_label_time = [
            mini_item('a', 'done', startedAt='2026-10-03T09:00:00+09:00', doneAt='2026-10-03T10:00:00+09:00'),
            mini_item('b', 'left', estimate=30),
        ]
        bands = self.find(self.render_dom(no_label_time), 'lane-band')
        self.assertEqual([b['style']['height'] for b in bands], ['176px'])

        no_label = [mini_item('a', 'done'), mini_item('b', 'left')]
        bands = self.find(self.render_dom(no_label), 'lane-band')
        self.assertEqual([b['style']['height'] for b in bands], ['142px'])

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

    def test_lane_label_pushes_nodes_down(self):
        item = [mini_item('a', 'left', lane=0)]
        labeled = self.by_id(self.render_dom(item, {'lanes': ['L1']}), 'a')['style']['top']
        plain = self.by_id(self.render_dom(item), 'a')['style']['top']
        self.assertEqual(labeled, '76px')
        self.assertEqual(plain, '62px')
        self.assertEqual(int(labeled[:-2]) - int(plain[:-2]), 14)

    def test_edges_keep_lane_auto_connections(self):
        items = [
            mini_item('a', 'done', lane=0),
            mini_item('b', 'left', lane=0),
            mini_item('c', 'left', lane=0),
            mini_item('d', 'left', lane=1),
        ]
        result = self.render_dom(items, {'lanes': ['L1', 'L2'], 'edges': [['a', 'd']]})
        self.assertEqual(len(self.find(result, 'edge')), 3)

    def test_edges_duplicate_auto_pair_drawn_once(self):
        items = [
            mini_item('a', 'done', lane=0),
            mini_item('b', 'left', lane=0),
            mini_item('c', 'left', lane=0),
        ]
        result = self.render_dom(items, {'edges': [['a', 'b']]})
        self.assertEqual(len(self.find(result, 'edge')), 2)

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

    def test_single_lane_gets_band_without_label(self):
        result = self.render_dom([mini_item('a', 'done'), mini_item('b', 'now')])
        bands = self.find(result, 'lane-band')
        self.assertEqual([(b.get('cls') or '').split() for b in bands], [['lane-band', 'live']])
        self.assertEqual(self.find(result, 'lane-label'), [])

    def test_unnamed_lane_band_has_no_label(self):
        items = [mini_item('a', 'done', lane=0), mini_item('b', 'left', lane=1)]
        result = self.render_dom(items, {'lanes': ['L1']})
        self.assertEqual(len(self.find(result, 'lane-band')), 2)
        self.assertEqual([n['text'] for n in self.find(result, 'lane-label')], ['L1'])

    def test_edge_between_waiting_steps_is_left(self):
        items = [mini_item('a', 'now'), mini_item('b', 'left'), mini_item('c', 'left')]
        result = self.render_dom(items, {'edges': [['a', 'b'], ['b', 'c']]})
        classes = [(e.get('cls') or '').split() for e in self.find(result, 'edge')]
        self.assertEqual(classes, [['edge', 'left'], ['edge', 'left']])

    def test_edge_across_two_columns_turns_at_gap_before_destination(self):
        items = [mini_item('a', 'done', lane=0, col=3), mini_item('b', 'left', lane=1, col=5)]
        result = self.render_dom(items, {'edges': [['a', 'b']]})
        edges = self.find(result, 'edge')
        self.assertEqual(len(edges), 1)
        d = edges[0]['attrs']['d']
        self.assertRegex(d, r'^M[\d.]+ [\d.]+ L[\d.]+ [\d.]+ C')
        ctrl = re.search(r'C([\d.]+) [\d.]+, ([\d.]+)', d)
        self.assertIsNotNone(ctrl)
        self.assertEqual(ctrl.group(1), ctrl.group(2))
        dest_x = 75 + 5 * 150
        self.assertAlmostEqual(float(ctrl.group(1)), dest_x - 75, delta=1)

    def test_edge_across_two_columns_with_middle_node_keeps_s_curve(self):
        items = [
            mini_item('a', 'done', lane=0, col=3),
            mini_item('c', 'left', lane=0, col=4),
            mini_item('b', 'left', lane=1, col=5),
        ]
        result = self.render_dom(items, {'edges': [['a', 'b']]})
        curved = [e for e in self.find(result, 'edge') if 'C' in e['attrs']['d']]
        self.assertEqual(len(curved), 1)
        self.assertNotIn('L', curved[0]['attrs']['d'])

    def test_edge_across_one_column_keeps_s_curve(self):
        items = [mini_item('a', 'done', lane=0, col=3), mini_item('b', 'left', lane=1, col=4)]
        result = self.render_dom(items, {'edges': [['a', 'b']]})
        edges = self.find(result, 'edge')
        self.assertEqual(len(edges), 1)
        self.assertIn('C', edges[0]['attrs']['d'])
        self.assertNotIn('L', edges[0]['attrs']['d'])

    def test_same_lane_edge_stays_straight(self):
        items = [mini_item('a', 'done', lane=0, col=3), mini_item('b', 'left', lane=0, col=4)]
        result = self.render_dom(items)
        edges = self.find(result, 'edge')
        self.assertEqual(len(edges), 1)
        self.assertIn('L', edges[0]['attrs']['d'])
        self.assertNotIn('C', edges[0]['attrs']['d'])

    def test_column_width_falls_back_without_layout(self):
        result = self.render_dom([mini_item('a', 'now'), mini_item('b', 'left')])
        self.assertEqual(self.by_id(result, 'a')['style']['width'], '134px')

    def test_column_width_fits_flow_card(self):
        seven = [mini_item(c, 'left') for c in 'abcdefg']
        cases = [
            (1006, [mini_item('a', 'now'), mini_item('b', 'left')], '134px'),
            (1006, seven, '123px'),
            (600, seven, '102px'),
        ]
        for width, items, expected in cases:
            with self.subTest(width=width, cols=len(items)):
                result = self.render_dom(items, flow_width=width)
                self.assertEqual(self.by_id(result, 'a')['style']['width'], expected)

    def test_now_node_has_orbit(self):
        result = self.render_dom([mini_item('a', 'now')])
        fnode = self.by_id(result, 'a')
        circle = next(k for k in fnode['kids'] if 'node' in (k.get('cls') or '').split())
        self.assertEqual(
            [k.get('cls') for k in circle.get('kids', []) if 'orbit' in (k.get('cls') or '').split()],
            ['orbit'],
        )

    def test_english_labels(self):
        result = self.render_dom([mini_item('a', 'done')], extra={'lang': 'en'})
        self.assertEqual(result['nodes']['eyebrowText']['text'], 'All steps done')
        self.assertEqual(result['nodes']['countLabel']['text'], 'done')
        self.assertEqual([s['text'] for s in result['nodes']['tally']['kids']], ['Done 1'])
        self.assertIn('✓Completed', [n['text'] for n in self.find(result, 'done')])

    def test_english_eta_overdue(self):
        result = self.render_dom(
            [mini_item('a', 'now', estimate=30)], extra={'lang': 'en'}, view='2026-10-03T11:00:00+09:00'
        )
        self.assertEqual([n['text'] for n in self.find(result, 'eta')], ['ETA 10:30 (overdue)'])


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
        self.assertNotIn('__THEME_CSS__', html)
        self.assertIn('SHOP-128 진행 상황', html)

    def test_input_data_file_is_left_untouched(self):
        path = self.write_data(load_example())
        with open(path, 'rb') as f:
            before = f.read()
        r = run_render(path, self.out())
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_render_leaves_no_bytecode_in_skill_dir(self):
        skill = os.path.join(self.tmp, 'skill')
        os.mkdir(skill)
        for name in ('render.py', 'state.py', 'config.py', 'hub.py', 'serve.py',
                     'template.html', 'hub.html', 'themes.css'):
            shutil.copy(os.path.join(HERE, name), skill)
        env = dict(os.environ)
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        for key in ('CLAUDE_CODE_SESSION_ID', 'DEADHD_STATE_DIR', 'DEADHD_HISTORY'):
            env.pop(key, None)
        env['DEADHD_CONFIG'] = MISSING_CONFIG
        env['DEADHD_HUB'] = os.path.join(self.tmp, 'hub.html')
        r = subprocess.run([sys.executable, os.path.join(skill, 'render.py'), EXAMPLE, self.out()],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(skill, '__pycache__')))

    def test_render_survives_a_missing_hub_module(self):
        skill = os.path.join(self.tmp, 'skill-no-hub')
        os.mkdir(skill)
        for name in ('render.py', 'state.py', 'config.py', 'serve.py',
                     'template.html', 'hub.html', 'themes.css'):
            shutil.copy(os.path.join(HERE, name), skill)
        env = dict(os.environ)
        for key in ('CLAUDE_CODE_SESSION_ID', 'DEADHD_STATE_DIR', 'DEADHD_HISTORY'):
            env.pop(key, None)
        env['DEADHD_CONFIG'] = MISSING_CONFIG
        hub = os.path.join(self.tmp, 'hub.html')
        env['DEADHD_HUB'] = hub
        out = self.out()
        r = subprocess.run([sys.executable, os.path.join(skill, 'render.py'), EXAMPLE, out],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        self.assertIn('SHOP-128 진행 상황', html)
        self.assertNotIn('hubHref', parse_block(data_block(html)))
        self.assertFalse(os.path.exists(hub))

    def test_refresh_meta_present(self):
        out = self.out()
        self.assertEqual(run_render(EXAMPLE, out).returncode, 0)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        self.assertIn('<meta http-equiv="refresh" content="15">', html)

    def test_star_button_links_to_repo(self):
        out = self.out()
        self.assertEqual(run_render(EXAMPLE, out).returncode, 0)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        self.assertIn('class="star-btn" href="https://github.com/lcalmsky/deadhd" target="_blank" rel="noopener"', html)

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
        self.assertEqual(tpl.count('__THEME_CSS__'), 1)


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

    def test_theme_ink_sets_html_attribute(self):
        r, out = self.render(theme='ink')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(out), '<html lang="ko" data-theme="ink">')

    def test_extra_themes_set_html_attribute(self):
        for theme in EXTRA_THEMES:
            with self.subTest(theme=theme):
                r, out = self.render(theme=theme)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.rendered_tag(out), '<html lang="ko" data-theme="%s">' % theme)


class RenderFontTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-font-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = os.path.join(self.tmp, 'config.json')
        self.out = os.path.join(self.tmp, 'out.html')

    def save_font(self, value):
        with open(self.config, 'w', encoding='utf-8') as f:
            json.dump({'font': value}, f)

    def run_render(self, argv, config_path=None):
        env = dict(os.environ)
        env['DEADHD_CONFIG'] = config_path if config_path is not None else MISSING_CONFIG
        for key in ('XDG_CONFIG_HOME', 'CLAUDE_CODE_SESSION_ID', 'DEADHD_STATE_DIR', 'DEADHD_HISTORY'):
            env.pop(key, None)
        env['DEADHD_HUB'] = TEST_HUB
        return subprocess.run([sys.executable, RENDER, *argv], capture_output=True, text=True, env=env)

    def render(self, *flags, config_path=None):
        return self.run_render([*flags, EXAMPLE, self.out], config_path=config_path)

    def rendered_tag(self):
        with open(self.out, encoding='utf-8') as f:
            return html_tag(f.read())

    def test_font_flag_sets_html_attribute(self):
        r = self.render('--font', 'do-hyeon')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(), '<html lang="ko" data-font="do-hyeon">')

    def test_theme_and_font_flags_in_either_order(self):
        orders = (
            ('--theme', 'dark', '--font', 'pretendard'),
            ('--font', 'pretendard', '--theme', 'dark'),
        )
        for flags in orders:
            with self.subTest(flags=flags):
                r = self.render(*flags)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.rendered_tag(), '<html lang="ko" data-theme="dark" data-font="pretendard">')

    def test_font_default_leaves_html_untouched(self):
        r = self.render('--font', 'default')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(), '<html lang="ko">')

    def test_invalid_font_flag_exits_1(self):
        r = self.render('--font', 'nope')
        self.assertEqual(r.returncode, 1)
        self.assertIn('nope', r.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_saved_font_applies_without_flag(self):
        self.save_font('hahmlet')
        r = self.render(config_path=self.config)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(), '<html lang="ko" data-font="hahmlet">')

    def test_flag_beats_saved_font(self):
        self.save_font('hahmlet')
        r = self.render('--font', 'do-hyeon', config_path=self.config)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rendered_tag(), '<html lang="ko" data-font="do-hyeon">')

    def test_font_flag_without_value_exits_1(self):
        r = self.run_render(['--font'])
        self.assertEqual(r.returncode, 1)


class LangTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-lang-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def render(self, data, theme=None):
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        return run_render(path, out, theme=theme), out

    def read(self, out):
        with open(out, encoding='utf-8') as f:
            return f.read()

    def test_lang_en_switches_html_and_title(self):
        data = load_example()
        data['lang'] = 'en'
        r, out = self.render(data)
        self.assertEqual(r.returncode, 0, r.stderr)
        html = self.read(out)
        self.assertEqual(html_tag(html), '<html lang="en">')
        self.assertIn('<title>SHOP-128 Progress</title>', html)

    def test_lang_en_with_theme_sets_both_attributes(self):
        data = load_example()
        data['lang'] = 'en'
        r, out = self.render(data, theme='dark')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(html_tag(self.read(out)), '<html lang="en" data-theme="dark">')

    def test_bad_lang_exits_1(self):
        for value in ('fr', 7):
            with self.subTest(value=value):
                data = load_example()
                data['lang'] = value
                r, out = self.render(data)
                self.assertEqual(r.returncode, 1)
                self.assertIn('lang', r.stderr)
                self.assertFalse(os.path.exists(out))


class TemplateI18NTest(unittest.TestCase):
    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-i18n-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_ko_en_key_sets_match(self):
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'title': 'T', 'items': [mini_item('a', 'done')]}, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            keys = run_linkify_harness(f.read())['probe']['i18nKeys']
        self.assertEqual(keys['ko'], keys['en'])


COMPACT_KEYS = (
    'viewNav', 'viewFull', 'viewStrip', 'viewTimeline', 'viewTile',
    'orientAuto', 'orientAutoTitle', 'orientLand', 'orientPort',
    'remainingTime', 'nowRemaining', 'statesLabel', 'stepListLabel',
)


class CompactViewTest(unittest.TestCase):
    """보기 전환 툴바와 컴팩트 자리가 렌더 결과에 들어가는지 확인한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-compact-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def render(self):
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(load_example(), f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            return f.read()

    def test_view_toolbar_and_compact_slot_in_output(self):
        html = self.render()
        self.assertIn('<div class="viewbar" role="toolbar"', html)
        self.assertIn('id="views"', html)
        self.assertIn('<div id="compact" hidden></div>', html)
        for view in ('full', 'a', 'b', 'c'):
            with self.subTest(view=view):
                self.assertIn('data-v="%s"' % view, html)
        for orient in ('auto', 'land', 'port'):
            with self.subTest(orient=orient):
                self.assertIn('data-o="%s"' % orient, html)

    def test_toolbar_sits_between_background_and_main(self):
        html = self.render()
        self.assertLess(html.index('class="stars"'), html.index('class="viewbar"'))
        self.assertLess(html.index('id="compact"'), html.index('<main>'))

    def test_viewbar_sits_in_content_width_with_star_button(self):
        html = self.render()
        viewbar = re.search(r'\.viewbar \{[^}]*\}', html).group(0)
        star = re.search(r'\.star-btn \{[^}]*\}', html).group(0)
        self.assertNotIn('position: fixed', viewbar)
        self.assertNotIn('position: fixed', star)
        self.assertLess(html.index('class="viewbar"'), html.index('class="star-btn"'))
        self.assertLess(html.index('class="star-btn"'), html.index('id="compact"'))
        port = re.search(r'\.viewbar\[data-o="port"\] \{[^}]*\}', html).group(0)
        land = re.search(r'\.viewbar\[data-o="land"\] \{[^}]*\}', html).group(0)
        self.assertIn('max-width: 520px', port)
        self.assertIn('max-width: 1100px', land)


class TemplateCompactTest(unittest.TestCase):
    """템플릿 스크립트가 툴바 문구를 언어에 맞추고 보기 하나를 그리는지 확인한다."""

    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-compact-dom-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def harness(self, data, cases=None):
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            return run_linkify_harness(f.read(), cases)

    def compact(self, data, view, oe='port', chip='done'):
        return self.harness(data, {'compact': {'v': view, 'oe': oe, 'chip': chip}})['compact']

    def test_toolbar_labels_follow_language(self):
        cases = {
            'ko': (['원본', '스트립', '타임라인', '타일'], ['자동', '가로', '세로'], '보기'),
            'en': (['Original', 'Strip', 'Timeline', 'Tiles'], ['Auto', 'Landscape', 'Portrait'], 'View'),
        }
        for lang, (views, orients, nav) in cases.items():
            with self.subTest(lang=lang):
                data = {'title': 'T', 'items': [mini_item('a', 'done')]}
                if lang == 'en':
                    data['lang'] = 'en'
                nodes = self.harness(data)['nodes']
                self.assertEqual([nodes[k]['text'] for k in ('v-full', 'v-a', 'v-b', 'v-c')], views)
                self.assertEqual([nodes[k]['text'] for k in ('o-auto', 'o-land', 'o-port')], orients)
                self.assertEqual(nodes['viewbar']['attrs']['aria-label'], nav)

    def test_original_view_is_selected_by_default(self):
        nodes = self.harness({'title': 'T', 'items': [mini_item('a', 'done')]})['nodes']
        self.assertEqual(
            {k: nodes[k]['attrs']['aria-pressed'] for k in ('v-full', 'v-a', 'v-b', 'v-c')},
            {'v-full': 'true', 'v-a': 'false', 'v-b': 'false', 'v-c': 'false'},
        )
        self.assertEqual(nodes['o-auto']['attrs']['aria-pressed'], 'true')

    def test_viewbar_has_no_orientation_in_original_view(self):
        nodes = self.harness({'title': 'T', 'items': [mini_item('a', 'done')]})['nodes']
        self.assertNotIn('o', nodes['viewbar'].get('data', {}))

    def test_each_view_renders_its_layout(self):
        data = {'title': 'T', 'items': [
            mini_item('a', 'done'),
            mini_item('b', 'now', estimate=30),
            mini_item('c', 'left', estimate=15),
            mini_item('d', 'side', estimate=60),
        ]}
        for view, marker in (('a', 'class="ca-strip"'), ('b', 'class="cb-tl"'), ('c', 'class="cc-tiles"')):
            with self.subTest(view=view):
                self.assertIn(marker, self.compact(data, view))

    def test_compact_view_escapes_data(self):
        data = {'title': 'T', 'items': [{
            'id': 'a', 'label': '<img src=x onerror=alert(1)>', 'state': 'now', 'estimate': 30,
            'title': 'T<b>i</b>', 'body': '</script><b>x</b>',
            'substeps': [{'label': '<i>s</i>', 'state': 'done'}],
            'evidence': [{'text': '<u>e</u>'}],
        }]}
        html = self.compact(data, 'a')
        for raw in ('</script>', '<img', '<b>x<', '<i>s<', '<u>e<', '<b>i<'):
            with self.subTest(raw=raw):
                self.assertNotIn(raw, html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertIn('&lt;/script&gt;&lt;b&gt;x&lt;/b&gt;', html)

    def test_compact_keys_are_translated(self):
        keys = self.harness({'title': 'T', 'items': [mini_item('a', 'done')]})['probe']['i18nKeys']
        self.assertEqual(keys['ko'], keys['en'])
        for key in COMPACT_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, keys['ko'])


class TemplateThemeTest(unittest.TestCase):
    def setUp(self):
        with open(THEMES_CSS, encoding='utf-8') as f:
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
        body = re.sub(r':root[^{]*\{[^}]*\}', '', self.tpl)
        for color in ('#059669', '#f97316', '#dc2626'):
            with self.subTest(color=color):
                self.assertNotIn(color, body)

    def test_rendered_page_carries_variable_block(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-theme-css-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(EXAMPLE, out, theme='dark')
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        self.assertIn(':root[data-theme="dark"]', html)
        self.assertIn('--bg: #07080d', html)

    def test_ink_overrides_and_tally_classes_exist(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            tpl = f.read()
        self.assertIn('[data-theme="ink"] .fnode.blocked .node {', tpl)
        self.assertIn('.tally i.done { background: var(--done); }', tpl)
        self.assertIn('dot.className = k;', tpl)
        self.assertNotIn('dot.style.background', tpl)


class TemplateFontTest(unittest.TestCase):
    def setUp(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            self.tpl = f.read()
        with open(THEMES_CSS, encoding='utf-8') as f:
            self.css = f.read()

    def test_preset_rules_exist_once_with_heading_vars(self):
        for preset in FONT_PRESETS:
            with self.subTest(preset=preset):
                rule = '[data-font="%s"] body {' % preset
                self.assertEqual(self.css.count(rule), 1)
                body = self.css.split(rule, 1)[1].split('}', 1)[0]
                for var in ('--f-head', '--head-w', '--head-ls'):
                    self.assertIn(var, body)

    def test_google_fonts_link_lists_new_families(self):
        m = re.search(r'<link href="https://fonts\.googleapis\.com/css2\?[^"]*"', self.tpl)
        self.assertIsNotNone(m, 'Google Fonts 링크를 찾지 못했다')
        link = m.group(0)
        for family in ('Noto+Sans+KR', 'Noto+Serif+KR', 'IBM+Plex+Sans+KR', 'Gothic+A1',
                       'Nanum+Gothic', 'Nanum+Myeongjo', 'Hahmlet'):
            with self.subTest(family=family):
                self.assertIn(family, link)

    def test_pretendard_link_present(self):
        self.assertIn('pretendardvariable.css', self.tpl)

    def test_presets_come_after_ink_theme_line(self):
        self.assertGreater(
            self.css.index('[data-font="pretendard"] body {'),
            self.css.index('[data-theme="ink"] body {'),
        )


class ServeScriptTest(unittest.TestCase):
    """serve.py 가 규칙에 맞는 파일만 127.0.0.1 로 제공하는지 확인한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-serve-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.port = free_port()
        self.env = dict(os.environ)
        self.env['DEADHD_SERVE_ROOT'] = self.tmp
        self.env['DEADHD_PORT'] = str(self.port)
        self.env['DEADHD_CONFIG'] = MISSING_CONFIG
        self.env.pop('XDG_CONFIG_HOME', None)
        self.addCleanup(self.stop_server)
        self.write('deadhd-page.html', '<!doctype html><html><body>hi</body></html>')

    def write(self, name, text='<!doctype html><html></html>'):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def serve(self, *args):
        return subprocess.run([sys.executable, SERVE] + list(args),
                              capture_output=True, text=True, env=self.env)

    def stop_server(self):
        self.serve('--stop')
        self.wait_down()

    def fetch(self, path, host=None, method='GET', data=None, headers=None):
        request = urllib.request.Request(
            'http://127.0.0.1:%d%s' % (self.port, path), method=method, data=data)
        if host is not None:
            request.add_header('Host', host)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=3) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            try:
                return e.code, dict(e.headers), e.read()
            finally:
                e.close()

    def wait_down(self, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.fetch('/healthz')
            except Exception:
                return True
            time.sleep(0.05)
        return False

    def daemon_count(self):
        r = subprocess.run(['pgrep', '-f', SERVE + ' --daemon'],
                           capture_output=True, text=True)
        if r.returncode not in (0, 1):
            return None
        return len(r.stdout.split())

    def test_serves_a_rule_file_without_caching(self):
        r = self.serve('--ensure')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'base: http://127.0.0.1:%d/' % self.port)
        status, headers, body = self.fetch('/deadhd-page.html')
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Content-Type'), 'text/html; charset=utf-8')
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertIn(b'hi', body)

    def test_other_names_are_not_found(self):
        self.write('other.html')
        self.assertEqual(self.serve('--ensure').returncode, 0)
        self.assertEqual(self.fetch('/other.html')[0], 404)
        self.assertEqual(self.fetch('/deadhd-missing.html')[0], 404)

    def test_parent_traversal_is_not_found(self):
        os.makedirs(os.path.join(self.tmp, 'sub'), exist_ok=True)
        self.write(os.path.join('sub', 'deadhd-page.html'))
        self.assertEqual(self.serve('--ensure').returncode, 0)
        self.assertEqual(self.fetch('/../deadhd-page.html')[0], 404)
        self.assertEqual(self.fetch('/sub/deadhd-page.html')[0], 404)

    def test_symlink_outside_the_root_is_not_found(self):
        outside = tempfile.mkdtemp(prefix='progress-serve-outside-')
        self.addCleanup(shutil.rmtree, outside, True)
        secret = os.path.join(outside, 'deadhd-secret.html')
        with open(secret, 'w', encoding='utf-8') as f:
            f.write('<!doctype html><html><body>secret</body></html>')
        os.symlink(secret, os.path.join(self.tmp, 'deadhd-link.html'))
        self.assertEqual(self.serve('--ensure').returncode, 0)
        status, _, body = self.fetch('/deadhd-link.html')
        self.assertEqual(status, 404)
        self.assertNotIn(b'secret', body)
        self.assertEqual(self.serve('--url', os.path.join(self.tmp, 'deadhd-link.html')).returncode, 2)

    def test_foreign_host_is_forbidden(self):
        self.assertEqual(self.serve('--ensure').returncode, 0)
        self.assertEqual(self.fetch('/deadhd-page.html', host='evil.test')[0], 403)
        self.assertEqual(self.fetch('/healthz', host='evil.test')[0], 403)
        self.assertEqual(self.fetch('/deadhd-page.html', host='127.0.0.1')[0], 200)
        self.assertEqual(self.fetch('/deadhd-page.html', host='localhost:%d' % self.port)[0], 200)

    def test_healthz_answers_ok(self):
        self.assertEqual(self.serve('--ensure').returncode, 0)
        status, _, body = self.fetch('/healthz')
        self.assertEqual(status, 200)
        self.assertEqual(body.strip(), b'ok')

    def test_post_outside_quit_is_method_not_allowed(self):
        self.assertEqual(self.serve('--ensure').returncode, 0)
        self.assertEqual(self.fetch('/deadhd-page.html', method='POST', data=b'')[0], 405)

    def test_quit_stops_the_server(self):
        self.assertEqual(self.serve('--ensure').returncode, 0)
        self.assertEqual(self.fetch('/quit', method='POST', data=b'',
                                     headers={'X-Deadhd': 'stop'})[0], 200)
        self.assertTrue(self.wait_down(), '서버가 /quit 뒤에도 살아 있다')
        self.assertEqual(self.serve('--stop').stdout.strip(), 'stopped: none')

    def test_quit_without_the_stop_header_is_forbidden(self):
        self.assertEqual(self.serve('--ensure').returncode, 0)
        self.assertEqual(self.fetch('/quit', method='POST', data=b'')[0], 403)
        self.assertEqual(self.fetch('/healthz')[0], 200)
        self.assertEqual(self.fetch('/quit', method='POST', data=b'',
                                     headers={'X-Deadhd': 'nope'})[0], 403)
        self.assertEqual(self.fetch('/healthz')[0], 200)
        self.assertEqual(self.fetch('/quit', method='POST', data=b'',
                                     headers={'X-Deadhd': 'stop'})[0], 200)
        self.assertTrue(self.wait_down(), '서버가 /quit 뒤에도 살아 있다')

    def test_ensure_does_not_start_a_second_server(self):
        before = self.daemon_count()
        first = self.serve('--ensure')
        self.assertEqual(first.returncode, 0, first.stderr)
        started = self.daemon_count()
        second = self.serve('--ensure')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip(), 'base: http://127.0.0.1:%d/' % self.port)
        if before is not None and started is not None:
            self.assertEqual(started, before + 1)
            self.assertEqual(self.daemon_count(), started)

    def test_stop_without_a_server_says_none(self):
        self.assertEqual(self.serve('--stop').stdout.strip(), 'stopped: none')

    def test_url_prints_the_address_of_a_rule_file(self):
        page = os.path.join(self.tmp, 'deadhd-page.html')
        r = self.serve('--url', page)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'http://127.0.0.1:%d/deadhd-page.html' % self.port)

    def test_url_rejects_paths_outside_the_rule(self):
        cases = (self.write('other.html'), os.path.join(self.tmp, 'sub', 'deadhd-page.html'))
        for path in cases:
            with self.subTest(path=path):
                r = self.serve('--url', path)
                self.assertEqual(r.returncode, 2)
                self.assertFalse(r.stdout.strip())

    def test_daemon_on_a_busy_port_exits_zero(self):
        self.assertEqual(self.serve('--ensure').returncode, 0)
        r = self.serve('--daemon')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, '')


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

    def serve_env(self):
        root = os.path.join(self.tmp, 'serve')
        os.makedirs(root, exist_ok=True)
        port = free_port()
        env = {'DEADHD_SERVE_ROOT': root, 'DEADHD_PORT': str(port)}
        stop_env = dict(os.environ)
        stop_env.update(env)
        self.addCleanup(subprocess.run, [sys.executable, SERVE, '--stop'],
                        capture_output=True, text=True, env=stop_env)
        return root, port, env

    def run_open(self, path, worktree_id=None, path_prefix=None, mode=None, config=None,
                 dry=True, env_extra=None):
        env = dict(os.environ)
        env['DEADHD_CONFIG'] = self.config if config is None else config
        env.pop('ORCA_WORKTREE_ID', None)
        env.pop('XDG_CONFIG_HOME', None)
        env.pop('PROGRESS_OPEN_DRY', None)
        if dry:
            env['PROGRESS_OPEN_DRY'] = '1'
        if worktree_id is not None:
            env['ORCA_WORKTREE_ID'] = worktree_id
        if path_prefix is not None:
            env['PATH'] = path_prefix + os.pathsep + env.get('PATH', '')
        if env_extra:
            env.update(env_extra)
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

    def test_orca_opens_the_page_over_http(self):
        root, port, env = self.serve_env()
        page = os.path.join(root, 'deadhd-x.html')
        with open(page, 'w', encoding='utf-8') as f:
            f.write('<!doctype html><html></html>')
        r = self.run_open(page, mode='orca', dry=False, path_prefix=self.fake_orca_dir(),
                          env_extra=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            'opened: orca-tab ' + page,
            'url: http://127.0.0.1:%d/deadhd-x.html' % port,
        ])

    def test_desktop_prints_the_http_url(self):
        root, port, env = self.serve_env()
        page = os.path.join(root, 'deadhd-x.html')
        with open(page, 'w', encoding='utf-8') as f:
            f.write('<!doctype html><html></html>')
        r = self.run_open(page, mode='desktop', dry=False, env_extra=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            'opened: desktop ' + page,
            'url: http://127.0.0.1:%d/deadhd-x.html' % port,
        ])

    def test_page_outside_the_serving_rule_keeps_the_file_url(self):
        page = self.write_file('page.html')
        _, _, env = self.serve_env()
        r = self.run_open(page, mode='desktop', dry=False, env_extra=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('skip: serve', r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            'opened: desktop ' + page,
            'url: file://' + page,
        ])


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

    def test_font_set_then_get_returns_value(self):
        r = self.run_config('set', 'font', 'pretendard')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('saved: font=pretendard', r.stdout)
        self.assertEqual(self.run_config('get', 'font').stdout.strip(), 'pretendard')

    def test_font_set_invalid_value_exits_2(self):
        r = self.run_config('set', 'font', 'nope')
        self.assertEqual(r.returncode, 2)
        self.assertIn('nope', r.stderr)
        self.assertFalse(os.path.exists(self.path))

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


class StateScriptTest(unittest.TestCase):
    """state.py 가 훅 이벤트를 상태 파일과 재렌더로 옮기는지 확인한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-state-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state_dir = os.path.join(self.tmp, 'state')
        os.makedirs(self.state_dir)
        self.data = os.path.join(self.tmp, 'data.json')
        with open(self.data, 'w', encoding='utf-8') as f:
            json.dump(load_example(), f, ensure_ascii=False)
        self.out = os.path.join(self.tmp, 'out.html')

    def render_session(self, session='s1'):
        r = run_render(self.data, self.out, session=session,
                       env_extra={'DEADHD_STATE_DIR': self.state_dir})
        self.assertEqual(r.returncode, 0, r.stderr)

    def event(self, payload, raw=None, session='s1'):
        if raw is None:
            payload = dict(payload, session_id=session)
        return run_state(payload, self.state_dir, raw=raw)

    def read_state(self, session='s1'):
        with open(os.path.join(self.state_dir, session + '.json'), encoding='utf-8') as f:
            return json.load(f)

    def out_payload(self):
        with open(self.out, encoding='utf-8') as f:
            return parse_block(data_block(f.read()))

    def test_missing_state_file_writes_nothing(self):
        r = self.event({'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                        'message': 'm'}, session='ghost')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(os.listdir(self.state_dir), [])

    def test_permission_prompt_marks_waiting_and_rerenders(self):
        self.render_session()
        before = os.stat(self.out).st_mtime_ns
        r = self.event({'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                        'message': 'Claude needs your permission to use Bash'})
        self.assertEqual(r.returncode, 0)
        state = self.read_state()
        self.assertEqual(state['status'], 'waiting_permission')
        self.assertEqual(state['message'], 'Claude needs your permission to use Bash')
        self.assertEqual(self.out_payload()['live']['status'], 'waiting_permission')
        self.assertGreater(os.stat(self.out).st_mtime_ns, before)

    def test_idle_prompt_clears_message(self):
        self.render_session()
        self.event({'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
                    'message': 'x'})
        self.event({'hook_event_name': 'Notification', 'notification_type': 'idle_prompt',
                    'message': 'x'})
        state = self.read_state()
        self.assertEqual(state['status'], 'idle')
        self.assertIsNone(state['message'])

    def test_post_tool_use_updates_state_but_skips_recent_render(self):
        self.render_session()
        first = self.event({'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                            'tool_input': {}, 'tool_response': {}, 'duration_ms': 1200})
        self.assertEqual(first.returncode, 0)
        state = self.read_state()
        self.assertEqual(state['status'], 'working')
        self.assertEqual(state['lastTool']['name'], 'Bash')
        self.assertEqual(state['lastTool']['durationMs'], 1200)

        rendered = os.stat(self.out).st_mtime_ns
        second = self.event({'hook_event_name': 'PostToolUse', 'tool_name': 'Read', 'tool_input': {}})
        self.assertEqual(second.returncode, 0)
        self.assertEqual(os.stat(self.out).st_mtime_ns, rendered)
        self.assertEqual(self.read_state()['lastTool']['name'], 'Read')
        self.assertIsNone(self.read_state()['lastTool']['durationMs'])

    def test_stop_records_idle_and_background_tasks(self):
        self.render_session()
        r = self.event({'hook_event_name': 'Stop', 'last_assistant_message': 'done',
                        'background_tasks': [{'id': 't1', 'type': 'shell', 'status': 'running',
                                              'description': 'pytest -q'}]})
        self.assertEqual(r.returncode, 0)
        state = self.read_state()
        self.assertEqual(state['status'], 'idle')
        self.assertEqual(state['backgroundTasks'], [{'type': 'shell', 'description': 'pytest -q'}])

    def test_stop_without_tasks_clears_them(self):
        self.render_session()
        self.event({'hook_event_name': 'Stop',
                    'background_tasks': [{'type': 'shell', 'description': 'x'}]})
        self.event({'hook_event_name': 'Stop'})
        self.assertEqual(self.read_state()['backgroundTasks'], [])

    def test_compact_counts_and_returns_context(self):
        self.render_session()
        r = self.event({'hook_event_name': 'SessionStart', 'source': 'compact'})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.read_state()['compactions']['count'], 1)
        note = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(note['hookEventName'], 'SessionStart')
        self.assertIn(self.data, note['additionalContext'])
        self.assertIn(self.out, note['additionalContext'])

    def test_session_start_without_compact_is_ignored(self):
        self.render_session()
        r = self.event({'hook_event_name': 'SessionStart', 'source': 'startup'})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, '')
        self.assertEqual(self.read_state()['compactions']['count'], 0)

    def test_session_end_marks_ended(self):
        self.render_session()
        r = self.event({'hook_event_name': 'SessionEnd', 'reason': 'exit'})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.read_state()['status'], 'ended')

    def test_broken_stdin_exits_zero(self):
        self.render_session()
        r = self.event(None, raw='{not json')
        self.assertEqual(r.returncode, 0)
        r = self.event(None, raw='')
        self.assertEqual(r.returncode, 0)

    def test_stale_state_files_are_dropped(self):
        self.render_session()
        other = os.path.join(self.state_dir, 'old.json')
        with open(other, 'w', encoding='utf-8') as f:
            f.write('{}')
        old = time.time() - 8 * 24 * 3600
        os.utime(other, (old, old))
        self.event({'hook_event_name': 'UserPromptSubmit', 'prompt': 'hi'})
        self.assertFalse(os.path.exists(other))
        self.assertTrue(os.path.exists(os.path.join(self.state_dir, 's1.json')))

    def test_parent_traversal_id_is_ignored(self):
        outside = os.path.join(self.tmp, 'esc.json')
        with open(outside, 'w', encoding='utf-8') as f:
            f.write('{"x": 1}')
        self.render_session()
        r = run_state({'session_id': '../esc', 'hook_event_name': 'Stop'}, self.state_dir)
        self.assertEqual(r.returncode, 0)
        with open(outside, encoding='utf-8') as f:
            self.assertEqual(f.read(), '{"x": 1}')
        self.assertEqual(sorted(os.listdir(self.state_dir)), ['s1.json'])


class HubTest(unittest.TestCase):
    """hub.py 가 상태 파일을 버킷으로 나눠 허브 페이지를 쓰는지 확인한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-hub-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state_dir = os.path.join(self.tmp, 'state')
        os.makedirs(self.state_dir)
        self.hub = os.path.join(self.tmp, 'hub.html')

    def write_state(self, session, status, since, updated, lang='ko', out=None,
                    hooked=True, all_done=False):
        state = {
            'sessionId': session,
            'out': out or os.path.join(self.tmp, session + '.html'),
            'status': status,
            'since': since,
            'updatedAt': updated,
            'message': None,
            'lastTool': None,
            'backgroundTasks': [],
            'compactions': {'count': 0, 'lastAt': None},
            'cwd': '/tmp',
            'summary': {
                'title': session + ' 제목', 'key': session.upper(), 'keyHref': None, 'lang': lang,
                'updated': None, 'counts': {'done': 1, 'now': 0, 'side': 0, 'left': 1, 'blocked': 0},
                'total': 2, 'states': ['done', 'left'], 'nowLabel': None,
                'eta': None, 'etaCalibrated': None, 'renderedAt': updated,
                'hooked': hooked, 'allDone': all_done,
            },
        }
        with open(os.path.join(self.state_dir, session + '.json'), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)

    def write_raw(self, session, text):
        with open(os.path.join(self.state_dir, session + '.json'), 'w', encoding='utf-8') as f:
            f.write(text)

    def run_hub(self, **kwargs):
        extra = {'DEADHD_NOW': FIXED_NOW}
        extra.update(kwargs.pop('env_extra', {}) or {})
        return run_hub(self.state_dir, self.hub, env_extra=extra, **kwargs)

    def page(self, **kwargs):
        r = self.run_hub(**kwargs)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'rendered: ' + self.hub)
        with open(self.hub, encoding='utf-8') as f:
            return f.read()

    def sessions(self, **kwargs):
        return parse_block(hub_data_block(self.page(**kwargs)))['sessions']

    def test_sessions_are_bucketed_and_sorted(self):
        self.write_state('a', 'idle', '2026-10-03T09:50:00+09:00', FIXED_NOW)
        self.write_state('b', 'waiting_permission', '2026-10-03T09:40:00+09:00', FIXED_NOW)
        self.write_state('c', 'working', '2026-10-03T09:30:00+09:00', FIXED_NOW)
        self.write_state('d', 'ended', '2026-10-03T09:20:00+09:00', FIXED_NOW)
        self.write_state('e', 'idle', '2026-10-03T09:10:00+09:00', '2026-10-01T10:00:00+09:00')
        self.write_raw('f', '{}')
        self.write_raw('g', '{not json')

        sessions = self.sessions()
        self.assertEqual([s['sessionId'] for s in sessions], ['b', 'a', 'c', 'd', 'e'])
        self.assertEqual([s['bucket'] for s in sessions], ['wait', 'idle', 'working', 'ended', 'stale'])
        self.assertEqual(sessions[0]['href'], 'file://' + os.path.join(self.tmp, 'b.html'))

    def test_servable_page_becomes_an_http_href(self):
        root = os.path.join(self.tmp, 'serve')
        os.makedirs(root)
        port = free_port()
        self.write_state('a', 'idle', '2026-10-03T09:50:00+09:00', FIXED_NOW,
                         out=os.path.join(root, 'deadhd-a.html'))
        sessions = self.sessions(env_extra={'DEADHD_SERVE_ROOT': root, 'DEADHD_PORT': str(port)})
        self.assertEqual(sessions[0]['href'], 'http://127.0.0.1:%d/deadhd-a.html' % port)

    def test_page_outside_the_serve_root_keeps_the_file_url(self):
        out = os.path.join(self.tmp, 'deadhd-a.html')
        self.write_state('a', 'idle', '2026-10-03T09:50:00+09:00', FIXED_NOW, out=out)
        self.assertEqual(self.sessions(env_extra={'DEADHD_PORT': str(free_port())})[0]['href'],
                         'file://' + out)

    def test_recently_moved_tool_is_stalled(self):
        self.write_state('a', 'working', '2026-10-03T09:00:00+09:00', FIXED_NOW)
        path = os.path.join(self.state_dir, 'a.json')
        with open(path, encoding='utf-8') as f:
            state = json.load(f)
        state['lastTool'] = {'name': 'Bash', 'at': '2026-10-03T09:49:00+09:00', 'durationMs': None}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        self.assertEqual([s['bucket'] for s in self.sessions()], ['stall'])

    def test_missing_state_dir_writes_empty_page(self):
        shutil.rmtree(self.state_dir)
        html = self.page()
        self.assertEqual(parse_block(hub_data_block(html))['sessions'], [])
        self.assertIn('<title>deadhd 허브</title>', html)

    def test_all_english_sessions_switch_page_language(self):
        self.write_state('a', 'idle', '2026-10-03T09:50:00+09:00', FIXED_NOW, lang='en')
        self.write_state('b', 'idle', '2026-10-03T09:40:00+09:00', FIXED_NOW, lang='en')
        html = self.page()
        self.assertEqual(html_tag(html), '<html lang="en">')
        self.assertIn('<title>deadhd hub</title>', html)

        self.write_state('b', 'idle', '2026-10-03T09:40:00+09:00', FIXED_NOW)
        self.assertEqual(html_tag(self.page()), '<html lang="ko">')

    def test_theme_and_font_flags_set_html_attributes(self):
        self.write_state('a', 'idle', '2026-10-03T09:50:00+09:00', FIXED_NOW)
        html = self.page(theme='ink', font='do-hyeon')
        self.assertEqual(html_tag(html), '<html lang="ko" data-theme="ink" data-font="do-hyeon">')
        self.assertIn(':root[data-theme="ink"]', html)

    def test_output_path_argument_beats_default(self):
        out = os.path.join(self.tmp, 'other.html')
        r = run_hub(self.state_dir, self.hub, out=out, env_extra={'DEADHD_NOW': FIXED_NOW})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'rendered: ' + out)
        self.assertTrue(os.path.exists(out))
        self.assertFalse(os.path.exists(self.hub))

    def test_unhooked_finished_session_buckets_as_done(self):
        self.write_state('a', 'working', '2026-10-03T09:50:00+09:00', FIXED_NOW,
                         hooked=False, all_done=True)
        self.assertEqual([s['bucket'] for s in self.sessions()], ['done'])

    def test_unhooked_unfinished_session_buckets_as_untracked(self):
        self.write_state('a', 'working', '2026-10-03T09:50:00+09:00', FIXED_NOW, hooked=False)
        self.assertEqual([s['bucket'] for s in self.sessions()], ['untracked'])

    def test_old_untracked_and_done_sessions_are_stale(self):
        old = '2026-08-29T10:00:00+09:00'
        self.write_state('u', 'working', '2026-08-29T09:50:00+09:00', old, hooked=False)
        self.write_state('d', 'working', '2026-08-29T09:40:00+09:00', old,
                         hooked=False, all_done=True)
        self.assertEqual([s['bucket'] for s in self.sessions()], ['stale', 'stale'])

    def test_hooked_finished_session_buckets_as_done_regardless_of_status(self):
        self.write_state('a', 'working', '2026-10-03T09:50:00+09:00', FIXED_NOW, all_done=True)
        self.assertEqual([s['bucket'] for s in self.sessions()], ['done'])

    def test_untracked_and_done_sort_before_ended(self):
        self.write_state('u', 'working', '2026-10-03T09:50:00+09:00', FIXED_NOW, hooked=False)
        self.write_state('d', 'working', '2026-10-03T09:40:00+09:00', FIXED_NOW,
                         hooked=False, all_done=True)
        self.write_state('e', 'ended', '2026-10-03T09:30:00+09:00', FIXED_NOW)
        self.assertEqual([s['bucket'] for s in self.sessions()], ['untracked', 'done', 'ended'])

    def test_unknown_theme_exits_1(self):
        r = self.run_hub(theme='nope')
        self.assertEqual(r.returncode, 1)
        self.assertIn('nope', r.stderr)


class HubPageTest(unittest.TestCase):
    """허브 템플릿이 세션을 타일과 접힌 목록으로 그리는지 확인한다."""

    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-hub-dom-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state_dir = os.path.join(self.tmp, 'state')
        os.makedirs(self.state_dir)
        self.hub = os.path.join(self.tmp, 'hub.html')

    def write_state(self, session, status, since, title, lang='ko', tool_at=None,
                    key_href='https://x.test/SHOP-1', hooked=True, all_done=False):
        state = {
            'sessionId': session,
            'out': os.path.join(self.tmp, session + '.html'),
            'status': status,
            'since': since,
            'updatedAt': FIXED_NOW,
            'message': 'Bash 권한' if status == 'waiting_permission' else None,
            'lastTool': {'name': 'Bash', 'at': tool_at, 'durationMs': None} if tool_at else None,
            'backgroundTasks': [],
            'compactions': {'count': 0, 'lastAt': None},
            'cwd': '/tmp',
            'summary': {
                'title': title, 'key': 'SHOP-1', 'keyHref': key_href, 'lang': lang,
                'updated': None, 'counts': {'done': 3, 'now': 1, 'side': 0, 'left': 1, 'blocked': 0},
                'total': 5, 'states': ['done', 'done', 'done', 'now', 'left'], 'nowLabel': '배포 검증',
                'eta': '2026-10-03T10:30:00+09:00', 'etaCalibrated': '2026-10-03T10:48:00+09:00',
                'renderedAt': FIXED_NOW, 'hooked': hooked, 'allDone': all_done,
            },
        }
        with open(os.path.join(self.state_dir, session + '.json'), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)

    def dom(self, theme=None, font=None):
        r = run_hub(self.state_dir, self.hub, theme=theme, font=font,
                    env_extra={'DEADHD_NOW': FIXED_NOW})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.hub, encoding='utf-8') as f:
            return run_hub_harness(f.read(), fixed_now=FIXED_NOW)['nodes']

    def tiles(self, nodes, grid):
        return [n for n in iter_nodes(nodes[grid]) if 'tile' in (n.get('cls') or '').split()]

    def texts(self, node, cls):
        return [n['text'] for n in iter_nodes(node) if cls in (n.get('cls') or '').split()]

    def test_wait_tile_shows_badge_and_eta(self):
        self.write_state('w', 'waiting_permission', '2026-10-03T09:48:00+09:00', '상담 봇 검색 근거 등급 도입')
        nodes = self.dom()
        tile = self.tiles(nodes, 'waitGrid')[0]
        self.assertEqual(tile['href'], 'file://' + os.path.join(self.tmp, 'w.html'))
        self.assertEqual(self.texts(tile, 'badge'), ['권한 승인 대기 · 12분째'])
        self.assertEqual(self.texts(tile, 'tile-count'), ['3/5'])
        self.assertEqual(self.texts(tile, 'tile-now'), ['지금 · 배포 검증'])
        self.assertEqual(self.texts(tile, 'raw'), ['10:30'])
        self.assertEqual(self.texts(tile, 'tile-sub'), ['Bash 권한'])
        self.assertEqual(self.texts(tile, 'tile-key'), ['SHOP-1'])
        self.assertEqual([n['cls'] for n in iter_nodes(tile) if 'dot' in (n.get('cls') or '').split()],
                         ['dot done', 'dot done', 'dot done', 'dot now', 'dot left'])

    def test_tiles_are_ordered_wait_idle_working_and_ended_folds(self):
        self.write_state('i', 'idle', '2026-10-03T09:50:00+09:00', '입력 대기 세션')
        self.write_state('w', 'waiting_permission', '2026-10-03T09:40:00+09:00', '기다리는 세션')
        self.write_state('k', 'working', '2026-10-03T09:30:00+09:00', '작업 중 세션')
        self.write_state('e', 'ended', '2026-10-03T09:20:00+09:00', '끝난 세션')
        nodes = self.dom()
        self.assertEqual(self.texts(nodes['waitGrid'], 'tile-title'),
                         ['기다리는 세션', '입력 대기 세션'])
        self.assertEqual(self.texts(nodes['workGrid'], 'tile-title'), ['작업 중 세션'])
        self.assertEqual(self.texts(nodes['endedList'], 'e-title'), ['끝난 세션'])
        self.assertNotIn('hidden', nodes['sec-ended'])
        self.assertNotIn('hidden', nodes['sec-wait'])
        self.assertEqual(nodes['h1']['text'], '세션 4 · 나를 기다리는 세션 2')
        self.assertIn('승인 대기 1', nodes['sub']['text'])
        self.assertIn('입력 대기 1', nodes['sub']['text'])
        self.assertIn('작업 중 1', nodes['sub']['text'])
        self.assertIn('종료 1', nodes['sub']['text'])

    def test_done_and_untracked_tiles(self):
        self.write_state('d', 'working', '2026-10-03T09:50:00+09:00', '완료 세션',
                         hooked=False, all_done=True)
        self.write_state('u', 'working', '2026-10-03T09:40:00+09:00', '훅 없는 세션', hooked=False)
        nodes = self.dom()
        self.assertEqual(nodes['doneHead']['text'], '완료된 세션')
        self.assertNotIn('hidden', nodes['sec-done'])
        self.assertEqual(self.texts(self.tiles(nodes, 'doneGrid')[0], 'badge'), ['완료 · 갱신 10:00'])
        self.assertEqual(self.texts(self.tiles(nodes, 'workGrid')[0], 'badge'),
                         ['훅 없음 · 갱신 10:00'])
        self.assertIn('완료 1', nodes['sub']['text'])
        self.assertIn('훅 없음 1', nodes['sub']['text'])
        self.assertEqual(nodes['h1']['text'], '세션 2 · 나를 기다리는 세션 0')

    def test_sections_without_sessions_are_hidden(self):
        self.write_state('k', 'working', '2026-10-03T09:30:00+09:00', '작업 중 세션')
        nodes = self.dom()
        self.assertEqual(nodes['sec-wait']['hidden'], True)
        self.assertEqual(nodes['sec-done']['hidden'], True)
        self.assertEqual(nodes['sec-ended']['hidden'], True)
        self.assertNotIn('hidden', nodes['sec-working'])

    def test_empty_page_shows_the_sentence(self):
        nodes = self.dom()
        self.assertIn('아직 세션이 없다', nodes['empty']['text'])
        self.assertNotIn('hidden', nodes['empty'])
        self.assertEqual(nodes['h1']['text'], '세션 0 · 나를 기다리는 세션 0')

    def test_english_labels(self):
        self.write_state('w', 'waiting_permission', '2026-10-03T09:48:00+09:00', 'Waiting session', lang='en')
        nodes = self.dom()
        self.assertEqual(nodes['eyebrowText']['text'], 'deadhd hub')
        self.assertEqual(self.texts(self.tiles(nodes, 'waitGrid')[0], 'badge'),
                         ['Waiting for permission · for 12m'])
        self.assertEqual(nodes['waitHead']['text'], 'Waiting for you')

    def test_working_tile_shows_the_last_tool(self):
        self.write_state('k', 'working', '2026-10-03T09:30:00+09:00', '작업 중 세션',
                         tool_at='2026-10-03T09:58:00+09:00')
        nodes = self.dom()
        tile = self.tiles(nodes, 'workGrid')[0]
        self.assertEqual(self.texts(tile, 'badge'), ['작업 중 · 2분 전'])
        self.assertEqual(self.texts(tile, 'tile-sub'), ['Bash'])

    def test_stalled_working_waits_in_the_first_section(self):
        self.write_state('k', 'working', '2026-10-03T09:00:00+09:00', '멈춘 세션',
                         tool_at='2026-10-03T09:49:00+09:00')
        nodes = self.dom()
        self.assertEqual(self.texts(nodes['waitGrid'], 'badge'), ['신호 없음 · 11분째'])
        self.assertIn('hidden', nodes['sec-working'])

    def test_ink_theme_marks_the_wait_tile(self):
        self.write_state('w', 'waiting_permission', '2026-10-03T09:48:00+09:00', '기다리는 세션')
        nodes = self.dom(theme='ink')
        self.assertEqual(self.tiles(nodes, 'waitGrid')[0]['cls'], 'tile tile-wait')

    def key_links(self, tile):
        chip = [k for k in tile.get('kids', ()) if 'tile-key' in (k.get('cls') or '').split()][0]
        return [k for k in chip.get('kids', ()) if k['t'] == 'A']

    def test_http_key_href_becomes_a_link(self):
        self.write_state('w', 'waiting_permission', '2026-10-03T09:48:00+09:00', '기다리는 세션')
        nodes = self.dom()
        self.assertEqual([l['href'] for l in self.key_links(self.tiles(nodes, 'waitGrid')[0])],
                         ['https://x.test/SHOP-1'])

    def test_key_href_outside_http_stays_a_plain_chip(self):
        self.write_state('w', 'waiting_permission', '2026-10-03T09:48:00+09:00', '기다리는 세션',
                         key_href='javascript:alert(1)')
        nodes = self.dom()
        tile = self.tiles(nodes, 'waitGrid')[0]
        self.assertEqual(self.texts(tile, 'tile-key'), ['SHOP-1'])
        self.assertEqual(self.key_links(tile), [])

    def test_tile_opens_in_the_same_tab(self):
        self.write_state('w', 'waiting_permission', '2026-10-03T09:48:00+09:00', '기다리는 세션')
        nodes = self.dom()
        tile = self.tiles(nodes, 'waitGrid')[0]
        self.assertNotIn('target', tile.get('attrs') or {})
        self.assertNotIn('rel', tile.get('attrs') or {})


class SessionIdValidationTest(unittest.TestCase):
    """state.valid_session_id 가 경로를 벗어나는 값을 막는지 확인한다."""

    def test_valid_ids(self):
        for value in ('abc-123_x.y', '20684f98-14a3-46ef-a83d-c281d90ea44b'):
            with self.subTest(value=value):
                self.assertTrue(VALID_SESSION_ID(value))

    def test_invalid_ids(self):
        for value in ('', '.', '..', 'a/b', 'a' * 129, None, 7):
            with self.subTest(value=repr(value)):
                self.assertFalse(VALID_SESSION_ID(value))


class RenderSessionTest(unittest.TestCase):
    """render.py 가 세션 id 로 상태 파일을 만들고 payload 에 live 를 넣는지 확인한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-session-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state_dir = os.path.join(self.tmp, 'state')
        self.data = os.path.join(self.tmp, 'data.json')
        with open(self.data, 'w', encoding='utf-8') as f:
            json.dump(load_example(), f, ensure_ascii=False)
        self.out = os.path.join(self.tmp, 'out.html')

    def render(self, session=None, env_extra=None):
        extra = {'DEADHD_STATE_DIR': self.state_dir}
        if env_extra:
            extra.update(env_extra)
        return run_render(self.data, self.out, session=session, env_extra=extra)

    def payload(self):
        with open(self.out, encoding='utf-8') as f:
            return parse_block(data_block(f.read()))

    def seed_state(self, session, **extra):
        """훅이 이미 돈 세션처럼 상태 파일을 미리 둔다."""
        os.makedirs(self.state_dir, exist_ok=True)
        state = {'hooked': True}
        state.update(extra)
        with open(os.path.join(self.state_dir, session + '.json'), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)

    def read_state(self, session='abc'):
        with open(os.path.join(self.state_dir, session + '.json'), encoding='utf-8') as f:
            return json.load(f)

    def test_session_flag_creates_absolute_state(self):
        self.seed_state('abc')
        self.assertEqual(self.render(session='abc').returncode, 0)
        with open(os.path.join(self.state_dir, 'abc.json'), encoding='utf-8') as f:
            state = json.load(f)
        self.assertEqual(state['sessionId'], 'abc')
        self.assertEqual(state['data'], os.path.abspath(self.data))
        self.assertEqual(state['out'], os.path.abspath(self.out))
        self.assertTrue(os.path.isabs(state['data']))
        self.assertTrue(os.path.isabs(state['out']))
        self.assertEqual(self.payload()['live']['status'], 'working')

    def test_without_session_payload_has_no_live(self):
        self.assertEqual(self.render().returncode, 0)
        self.assertNotIn('live', self.payload())
        self.assertFalse(os.path.isdir(self.state_dir))

    def test_env_var_links_session(self):
        self.seed_state('env-1')
        self.assertEqual(self.render(env_extra={'CLAUDE_CODE_SESSION_ID': 'env-1'}).returncode, 0)
        with open(os.path.join(self.state_dir, 'env-1.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['sessionId'], 'env-1')
        self.assertEqual(self.payload()['live']['status'], 'working')

    def test_unhooked_render_has_no_live_band(self):
        self.assertEqual(self.render(session='abc').returncode, 0)
        self.assertNotIn('live', self.payload())
        self.assertFalse(self.read_state().get('hooked'))

    def test_hooked_render_keeps_the_live_band(self):
        self.seed_state('abc', status='working', since=FIXED_NOW)
        self.assertEqual(self.render(session='abc').returncode, 0)
        self.assertEqual(self.payload()['live']['status'], 'working')
        self.assertTrue(self.read_state()['hooked'])

    def test_hook_event_turns_the_live_band_on(self):
        self.assertEqual(self.render(session='abc').returncode, 0)
        self.assertNotIn('live', self.payload())
        r = run_state({'session_id': 'abc', 'hook_event_name': 'UserPromptSubmit', 'prompt': 'hi'},
                      self.state_dir)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.payload()['live']['status'], 'working')
        self.assertTrue(self.read_state()['hooked'])
        self.assertTrue(self.read_state()['summary']['hooked'])

    def test_state_carries_summary_for_the_hub(self):
        self.assertEqual(self.render(session='abc').returncode, 0)
        with open(os.path.join(self.state_dir, 'abc.json'), encoding='utf-8') as f:
            summary = json.load(f)['summary']
        example = load_example()
        states = [it['state'] for it in example['items']]
        self.assertEqual(summary['title'], example['title'])
        self.assertEqual(summary['key'], example['key'])
        self.assertEqual(summary['total'], len(example['items']))
        self.assertEqual(summary['states'], states)
        self.assertEqual(summary['counts']['done'], states.count('done'))
        self.assertEqual(summary['nowLabel'], example['items'][states.index('now')]['label'])
        self.assertEqual(summary['renderedAt'], self.payload()['renderedAt'])
        self.assertIn('eta', summary)
        self.assertFalse(summary['hooked'])
        self.assertFalse(summary['allDone'])

    def test_payload_has_hub_href(self):
        hub = os.path.join(self.tmp, 'hub.html')
        self.assertEqual(self.render(env_extra={'DEADHD_HUB': hub}).returncode, 0)
        self.assertEqual(self.payload()['hubHref'], 'file://' + hub)

    def test_payload_links_a_servable_hub_over_http(self):
        root = os.path.join(self.tmp, 'serve')
        os.makedirs(root)
        hub = os.path.join(root, 'deadhd-hub.html')
        port = free_port()
        r = self.render(env_extra={'DEADHD_HUB': hub, 'DEADHD_SERVE_ROOT': root,
                                   'DEADHD_PORT': str(port)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.payload()['hubHref'],
                         'http://127.0.0.1:%d/deadhd-hub.html' % port)

    def test_payload_keeps_the_file_url_outside_the_serving_rule(self):
        hub = os.path.join(self.tmp, 'x', 'other.html')
        r = self.render(env_extra={'DEADHD_HUB': hub, 'DEADHD_PORT': str(free_port())})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.payload()['hubHref'], 'file://' + hub)

    def test_render_writes_the_hub(self):
        hub = os.path.join(self.tmp, 'hub.html')
        self.assertEqual(self.render(session='abc', env_extra={'DEADHD_HUB': hub}).returncode, 0)
        with open(hub, encoding='utf-8') as f:
            data = parse_block(hub_data_block(f.read()))
        self.assertEqual([s['sessionId'] for s in data['sessions']], ['abc'])
        self.assertEqual(data['sessions'][0]['summary']['title'], load_example()['title'])

    def test_render_without_session_still_writes_the_hub(self):
        hub = os.path.join(self.tmp, 'hub.html')
        self.assertEqual(self.render(env_extra={'DEADHD_HUB': hub}).returncode, 0)
        self.assertTrue(os.path.exists(hub))

    def test_parent_traversal_session_dies(self):
        cases = (
            {'session': '../esc'},
            {'env_extra': {'CLAUDE_CODE_SESSION_ID': '../esc'}},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                r = self.render(**kwargs)
                self.assertEqual(r.returncode, 1)
                self.assertIn('세션 id', r.stderr)
                self.assertFalse(os.path.exists(os.path.join(self.tmp, 'esc.json')))
                self.assertFalse(os.path.exists(self.out))


class CalibrationTest(unittest.TestCase):
    """예상 대비 실제 이력이 보정 계수와 완료 예상으로 이어지는지 확인한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-cal-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.history = os.path.join(self.tmp, 'history.jsonl')
        self.state_dir = os.path.join(self.tmp, 'state')
        self.out = os.path.join(self.tmp, 'out.html')

    def write_data(self, items, name='data.json'):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'title': 'T', 'items': items}, f, ensure_ascii=False)
        return path

    def write_history(self, rows, broken=False):
        with open(self.history, 'w', encoding='utf-8') as f:
            if broken:
                f.write('not json\n')
                f.write('\n')
            for row in rows:
                f.write(json.dumps(row) + '\n')

    def entries(self):
        if not os.path.exists(self.history):
            return []
        with open(self.history, encoding='utf-8') as f:
            return [json.loads(line) for line in f if line.strip()]

    def render(self, path, session=None):
        env = {'DEADHD_HISTORY': self.history, 'DEADHD_NOW': FIXED_NOW,
               'DEADHD_STATE_DIR': self.state_dir}
        r = run_render(path, self.out, session=session, env_extra=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.out, encoding='utf-8') as f:
            return parse_block(data_block(f.read()))

    def test_factor_needs_three_samples(self):
        items = [mini_item('a', 'now', estimate=30)]
        cases = ([], [{'est': 10, 'actual': 16}],
                 [{'est': 10, 'actual': 16}, {'est': 20, 'actual': 32}])
        for rows in cases:
            with self.subTest(samples=len(rows)):
                self.write_history(rows)
                payload = self.render(self.write_data(items))
                self.assertNotIn('etaCalibrated', payload)
                self.assertNotIn('calibration', payload)
                self.assertEqual(payload['eta'], '2026-10-03T10:30:00+09:00')

    def test_factor_and_calibrated_eta(self):
        self.write_history([
            {'est': 10, 'actual': 16},
            {'est': 20, 'actual': 32},
            {'est': 30, 'actual': 48},
        ])
        payload = self.render(self.write_data([mini_item('a', 'now', estimate=30)]))
        self.assertEqual(payload['calibration'], {'factor': 1.6, 'samples': 3})
        self.assertEqual(payload['eta'], '2026-10-03T10:30:00+09:00')
        self.assertEqual(payload['etaCalibrated'], '2026-10-03T10:48:00+09:00')

    def test_broken_history_lines_are_skipped(self):
        self.write_history([
            {'est': 10, 'actual': 16},
            {'est': 20, 'actual': 32},
            {'est': 30, 'actual': 48},
        ], broken=True)
        payload = self.render(self.write_data([mini_item('a', 'now', estimate=10)]))
        self.assertEqual(payload['calibration'], {'factor': 1.6, 'samples': 3})

    def test_factor_is_clamped(self):
        self.write_history([{'est': 1, 'actual': 10}] * 3)
        payload = self.render(self.write_data([mini_item('a', 'now', estimate=100)]))
        self.assertEqual(payload['calibration']['factor'], 5.0)
        self.assertEqual(payload['etaCalibrated'], '2026-10-03T18:20:00+09:00')

    def test_blocked_step_hides_calibrated_eta(self):
        self.write_history([{'est': 10, 'actual': 16}] * 3)
        items = [mini_item('a', 'now', estimate=30), mini_item('b', 'blocked')]
        payload = self.render(self.write_data(items))
        self.assertNotIn('eta', payload)
        self.assertNotIn('etaCalibrated', payload)

    def test_ledger_records_first_estimate_once(self):
        path = self.write_data([mini_item('a', 'now', estimate=10)])
        self.render(path, session='cal')
        with open(os.path.join(self.state_dir, 'cal.json'), encoding='utf-8') as f:
            ledger = json.load(f)['estimates']
        self.assertEqual(ledger['a']['est'], 10)
        self.assertFalse(ledger['a']['recorded'])

    def test_done_step_appends_history_once(self):
        path = self.write_data([mini_item('a', 'now', estimate=10)])
        self.render(path, session='cal')
        done = [mini_item('a', 'done', estimate=10,
                          startedAt='2026-10-03T09:00:00+09:00',
                          doneAt='2026-10-03T10:00:00+09:00')]
        self.write_data(done)
        self.render(path, session='cal')
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['item'], 'a')
        self.assertEqual(entries[0]['est'], 10)
        self.assertEqual(entries[0]['actual'], 60.0)
        self.assertEqual(entries[0]['session'], 'cal')

        self.render(path, session='cal')
        self.assertEqual(len(self.entries()), 1)

    def test_zero_length_step_is_not_recorded(self):
        path = self.write_data([mini_item('a', 'now', estimate=10)])
        self.render(path, session='cal')
        same = [mini_item('a', 'done', estimate=10,
                          startedAt='2026-10-03T10:00:00+09:00',
                          doneAt='2026-10-03T10:00:00+09:00')]
        self.render(self.write_data(same, 'data2.json'), session='cal')
        self.assertEqual(self.entries(), [])


class LiveBandTest(unittest.TestCase):
    """템플릿 스크립트가 live 상태를 띠로 그리는지 확인한다."""

    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-live-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state_dir = os.path.join(self.tmp, 'state')
        self.data = os.path.join(self.tmp, 'data.json')
        with open(self.data, 'w', encoding='utf-8') as f:
            json.dump(load_example(), f, ensure_ascii=False)
        self.out = os.path.join(self.tmp, 'out.html')

    def harness(self):
        with open(self.out, encoding='utf-8') as f:
            return run_linkify_harness(f.read(), fixed_now=FIXED_NOW)

    def band(self):
        return self.harness()['nodes']['status']

    def render_with_state(self, state, lang=None):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(os.path.join(self.state_dir, 's1.json'), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        data = load_example()
        if lang is not None:
            data['lang'] = lang
        with open(self.data, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        r = run_render(self.data, self.out, session='s1', env_extra={
            'DEADHD_STATE_DIR': self.state_dir,
            'DEADHD_HISTORY': os.path.join(self.tmp, 'history.jsonl'),
        })
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.harness()

    def band_with_state(self, state, lang=None):
        return self.render_with_state(state, lang)['nodes']['status']

    def texts(self, node, cls):
        return [n['text'] for n in iter_nodes(node) if cls in (n.get('cls') or '').split()]

    def test_unhooked_session_has_no_band(self):
        result = self.render_with_state({})
        self.assertNotIn('status', result['nodes'])

    def test_working_band(self):
        node = self.band_with_state({'hooked': True})
        self.assertIn('status-working', node['cls'])
        self.assertEqual(self.texts(node, 'status-title'), ['작업 중'])

    def test_permission_band_carries_message(self):
        self.assertEqual(run_render(self.data, self.out, session='s1',
                                    env_extra={'DEADHD_STATE_DIR': self.state_dir}).returncode, 0)
        r = run_state({'session_id': 's1', 'hook_event_name': 'Notification',
                       'notification_type': 'permission_prompt', 'message': 'Bash 권한'}, self.state_dir)
        self.assertEqual(r.returncode, 0)
        node = self.band()
        self.assertIn('status-waiting_permission', node['cls'])
        self.assertTrue(self.texts(node, 'status-title')[0].startswith('권한 승인 대기 · '))
        self.assertEqual(self.texts(node, 'status-what'), ['Bash 권한'])

    def test_stalled_working_band(self):
        node = self.band_with_state({
            'hooked': True,
            'status': 'working',
            'since': '2026-10-03T09:00:00+09:00',
            'lastTool': {'name': 'Bash', 'at': '2026-10-03T09:49:00+09:00', 'durationMs': 1200},
        })
        self.assertIn('status-stall', node['cls'].split())
        self.assertEqual(self.texts(node, 'status-title'), ['신호 없음 · 11분째'])

    def test_idle_band(self):
        node = self.band_with_state({'hooked': True, 'status': 'idle',
                                     'since': '2026-10-03T09:48:00+09:00'})
        self.assertIn('status-idle', node['cls'].split())
        self.assertEqual(self.texts(node, 'status-title'), ['입력 대기 · 12분째'])

    def test_ended_band(self):
        node = self.band_with_state({'hooked': True, 'status': 'ended',
                                     'since': '2026-10-03T09:30:00+09:00'})
        self.assertIn('status-ended', node['cls'].split())
        self.assertTrue(self.texts(node, 'status-title')[0].startswith('세션 종료 '))

    def test_english_permission_band(self):
        node = self.band_with_state(
            {'hooked': True, 'status': 'waiting_permission',
             'since': '2026-10-03T09:48:00+09:00', 'message': 'Bash'},
            lang='en')
        self.assertIn('status-waiting_permission', node['cls'].split())
        self.assertEqual(self.texts(node, 'status-title'), ['Waiting for permission · for 12m'])

    def test_status_band_and_live_lane_band_are_different_elements(self):
        # 띠가 .live 클래스를 쓰면 흐름도의 .lane-band.live 밴드에 규칙이 번져 레인 이름표가
        # 첫 노드와 겹친다. 두 요소가 클래스도 이름도 따로인지 확인한다.
        result = self.render_with_state({'hooked': True, 'status': 'waiting_permission',
                                         'since': '2026-10-03T09:48:00+09:00', 'message': 'Bash'})
        bands = [k for k in result['nodes']['canvas']['kids']
                 if 'lane-band' in (k.get('cls') or '').split()]
        self.assertTrue(bands, '레인 밴드를 찾지 못했다')
        self.assertIn('live', bands[0]['cls'].split())
        status = result['nodes']['status']
        self.assertIn('status-waiting_permission', status['cls'].split())
        self.assertNotIn(status, bands)
        self.assertNotIn('status-waiting_permission', bands[0]['cls'].split())


class EtaCalibrationDisplayTest(unittest.TestCase):
    """템플릿 스크립트가 보정 완료 예상을 원본 보기와 컴팩트 보기에 쓰는지 확인한다."""

    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-eta-cal-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.history = os.path.join(self.tmp, 'history.jsonl')

    def write_history(self, est, actual):
        with open(self.history, 'w', encoding='utf-8') as f:
            for _ in range(3):
                f.write(json.dumps({'est': est, 'actual': actual}) + '\n')

    def render(self, lang=None):
        data = {'title': 'T', 'items': [mini_item('a', 'now', estimate=30)]}
        if lang is not None:
            data['lang'] = lang
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out, env_extra={'DEADHD_HISTORY': self.history, 'DEADHD_NOW': FIXED_NOW})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            return f.read()

    def harness(self, html, cases=None):
        return run_linkify_harness(html, cases, fixed_now=FIXED_NOW)

    def find(self, result, cls):
        found = []
        for tree in result['nodes'].values():
            for node in iter_nodes(tree):
                if cls in (node.get('cls') or '').split():
                    found.append(node)
        return found

    def test_eta_line_shows_raw_and_calibrated(self):
        self.write_history(10, 16)
        result = self.harness(self.render())
        eta = self.find(result, 'eta')
        self.assertEqual(len(eta), 1)
        raw = self.find(result, 'raw')
        self.assertEqual([n['t'] for n in raw], ['S'])
        self.assertEqual([n['text'] for n in raw], ['10:30'])
        self.assertEqual([n['text'] for n in eta[0]['kids'] if n['t'] == 'B'], ['10:48'])
        self.assertEqual([n['text'] for n in self.find(result, 'cal-note')],
                         ['예측이 1.6배 느림 · 완료 3단계 기준'])

    def test_english_slow_note(self):
        self.write_history(10, 16)
        result = self.harness(self.render(lang='en'))
        self.assertEqual([n['text'] for n in self.find(result, 'cal-note')],
                         ['Estimates run 1.6× slow · from 3 done steps'])

    def test_fast_factor_note(self):
        self.write_history(10, 8)
        cases = (
            (None, '예측이 0.8배 빠름 · 완료 3단계 기준'),
            ('en', 'Estimates run 0.8× fast · from 3 done steps'),
        )
        for lang, expected in cases:
            with self.subTest(lang=lang):
                result = self.harness(self.render(lang=lang))
                self.assertEqual([n['text'] for n in self.find(result, 'cal-note')], [expected])

    def test_compact_views_use_calibrated_eta(self):
        self.write_history(10, 16)
        html = self.render()
        for view in ('a', 'b', 'c'):
            with self.subTest(view=view):
                out = self.harness(html, {'compact': {'v': view, 'oe': 'port', 'chip': 'done'}})['compact']
                self.assertIn('10:48', out)
                self.assertNotIn('10:30', out)


class TemplateLiveStaticTest(unittest.TestCase):
    def test_template_has_live_slot_and_styles(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            html = f.read()
        self.assertIn('<section class="status" id="status" hidden aria-live="polite"></section>', html)
        self.assertIn('.status-waiting_permission', html)
        self.assertIn('.cal-note', html)

    def test_template_css_has_no_live_class_selector(self):
        # .live 로 시작하는 선택자가 남으면 흐름도의 .lane-band.live 밴드가 띠 스타일을 받는다.
        with open(TEMPLATE, encoding='utf-8') as f:
            html = f.read()
        css = '\n'.join(re.findall(r'<style>(.*?)</style>', html, re.S))
        self.assertNotEqual(css, '', '<style> 블록을 찾지 못했다')
        m = re.search(r'(^|[\s,}])\.live\b', css)
        self.assertIsNone(m, '입력 대기 띠가 .live 클래스를 쓴다: %r' % (m.group(0) if m else ''))


class HubButtonTest(unittest.TestCase):
    """세션 페이지의 허브 버튼이 payload 의 hubHref 로 열리는지 확인한다."""

    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-hub-btn-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_hub_button_points_at_the_hub_page(self):
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(EXAMPLE, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            nodes = run_linkify_harness(f.read())['nodes']
        self.assertEqual(nodes['hubBtn']['href'], pathlib.Path(TEST_HUB).as_uri())
        self.assertEqual(nodes['hubBtn']['text'], '허브 ↗')

    def test_template_has_hub_button_slot(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            html = f.read()
        tag = re.search(r'<a class="hub-btn" id="hubBtn"[^>]*>', html)
        self.assertIsNotNone(tag)
        self.assertNotIn('target=', tag.group(0))
        self.assertNotIn('rel=', tag.group(0))


class HooksJsonTest(unittest.TestCase):
    def test_hooks_file_points_at_state_script(self):
        root = os.path.dirname(os.path.dirname(HERE))
        with open(os.path.join(root, 'hooks', 'hooks.json'), encoding='utf-8') as f:
            hooks = json.load(f)['hooks']
        self.assertEqual(sorted(hooks), sorted([
            'Notification', 'UserPromptSubmit', 'PostToolUse',
            'Stop', 'SessionStart', 'SessionEnd']))
        self.assertEqual(hooks['Notification'][0]['matcher'], 'permission_prompt|idle_prompt')
        self.assertEqual(hooks['SessionStart'][0]['matcher'], 'compact')
        for event, groups in hooks.items():
            with self.subTest(event=event):
                for group in groups:
                    for hook in group['hooks']:
                        self.assertEqual(hook['type'], 'command')
                        self.assertIn('${CLAUDE_PLUGIN_ROOT}/', hook['command'])
                        rel = hook['command'].split('${CLAUDE_PLUGIN_ROOT}/')[1].rstrip('"')
                        self.assertTrue(os.path.exists(os.path.join(root, rel)), rel)


BOARD_STAGES = ['분석', '설계', '구현', '검증']
# board_data 의 제목은 'T', key 는 없다. 템플릿의 KEY 는 'progress:' + key + ':' + title 이다.
BOARD_STATE_KEY = 'progress::T:board'
DEMO_EPIC = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'docs', 'demos', 'epic.json')


def board_lane(lid, state, **extra):
    lane = {'id': lid, 'label': lid + ' 작업', 'state': state}
    lane.update(extra)
    return lane


def board_data(board):
    data = {'title': 'T', 'items': [mini_item('a', 'done')]}
    if board is not None:
        data['board'] = board
    return data


class BoardValidateTest(unittest.TestCase):
    """board 필드의 검증 규칙을 확인한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='progress-board-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.count = 0

    def render(self, data):
        self.count += 1
        path = os.path.join(self.tmp, 'data%d.json' % self.count)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out%d.html' % self.count)
        return run_render(path, out), out

    def rejected(self, board, needle):
        r, out = self.render(board_data(board))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn(needle, r.stderr)
        self.assertFalse(os.path.exists(out))

    def test_valid_board_renders(self):
        board = {
            'stages': BOARD_STAGES,
            'lanes': [
                board_lane('l1', 'done', stage='검증', worker='deepseek', note='n', body='끝났다',
                           startedAt='2026-10-03T09:00:00+09:00', doneAt='2026-10-03T09:40:00+09:00',
                           lastSignal='2026-10-03T09:40:00+09:00', estimate=30, stallAfter=10,
                           evidence=[{'text': 'x', 'href': 'https://x.test/a'}],
                           log=[{'at': '2026-10-03T09:40:00+09:00', 'text': '완료'}]),
                board_lane('l2', 'now', stage='구현', dependsOn=['l1']),
                board_lane('l3', 'waiting'),
                board_lane('l4', 'left'),
                board_lane('l5', 'blocked'),
            ],
        }
        r, out = self.render(board_data(board))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            html = f.read()
        parsed = parse_block(data_block(html))
        self.assertEqual(parsed['board']['lanes'][0]['id'], 'l1')

    def test_board_without_stages_allows_any_stage(self):
        board = {'lanes': [board_lane('l1', 'now', stage='임의 단계')]}
        self.assertEqual(self.render(board_data(board))[0].returncode, 0)

    def test_board_must_be_an_object(self):
        self.rejected(['nope'], 'board 가 객체가 아니다')

    def test_lanes_must_be_a_non_empty_array(self):
        self.rejected({'lanes': []}, 'board.lanes')
        self.rejected({'stages': BOARD_STAGES}, 'board.lanes')

    def test_stages_must_be_non_empty_unique_strings(self):
        lanes = [board_lane('l1', 'now')]
        self.rejected({'stages': [], 'lanes': lanes}, 'board.stages')
        self.rejected({'stages': ['a', 'a'], 'lanes': lanes}, 'board.stages 에 중복')
        self.rejected({'stages': [1], 'lanes': lanes}, 'board.stages')

    def test_lane_id_and_label_are_required(self):
        self.rejected({'lanes': [board_lane('', 'now')]}, 'id 가 비어 있지 않은 문자열이 아니다')
        self.rejected({'lanes': [{'id': 'l1', 'state': 'now'}]}, 'label 이 문자열이 아니다')

    def test_duplicate_lane_id_is_rejected(self):
        board = {'lanes': [board_lane('l1', 'now'), board_lane('l1', 'left')]}
        self.rejected(board, '중복')

    def test_unknown_lane_state_is_rejected(self):
        self.rejected({'lanes': [board_lane('l1', 'side')]}, 'state')

    def test_stage_outside_stages_is_rejected(self):
        board = {'stages': BOARD_STAGES, 'lanes': [board_lane('l1', 'now', stage='배포')]}
        self.rejected(board, 'stage')

    def test_unknown_depends_on_is_rejected(self):
        board = {'lanes': [board_lane('l1', 'now', dependsOn=['nope'])]}
        self.rejected(board, 'dependsOn')
        self.rejected({'lanes': [board_lane('l1', 'now', dependsOn='l1')]}, 'dependsOn')

    def test_bad_timestamps_are_rejected(self):
        self.rejected({'lanes': [board_lane('l1', 'now', lastSignal='2026-10-03T09:00:00')]}, 'lastSignal')
        self.rejected({'lanes': [board_lane('l1', 'now', startedAt='어제')]}, 'startedAt')
        self.rejected(
            {'lanes': [board_lane('l1', 'done', startedAt='2026-10-03T09:00:00+09:00',
                                  doneAt='2026-10-03T08:00:00+09:00')]},
            '앞선다')
        self.rejected({'lanes': [board_lane('l1', 'now', log=[{'at': '2026-10-03T09:00:00'}])]}, 'log[0].at')

    def test_log_entry_needs_text(self):
        self.rejected({'lanes': [board_lane('l1', 'now', log=[{'at': '2026-10-03T09:00:00+09:00'}])]}, 'log[0].text')
        self.rejected({'lanes': [board_lane('l1', 'now', log='메모')]}, 'log 가 배열이 아니다')

    def test_stall_after_must_be_positive_number(self):
        self.rejected({'lanes': [board_lane('l1', 'now', stallAfter=0)]}, 'stallAfter')
        self.rejected({'lanes': [board_lane('l1', 'now', stallAfter=-5)]}, 'stallAfter')
        self.rejected({'lanes': [board_lane('l1', 'now', stallAfter='15')]}, 'stallAfter')

    def test_estimate_rule_matches_items(self):
        self.rejected({'lanes': [board_lane('l1', 'now', estimate=0)]}, 'estimate')
        self.rejected({'lanes': [board_lane('l1', 'now', estimate='30')]}, 'estimate')

    def test_evidence_href_must_be_http(self):
        board = {'lanes': [board_lane('l1', 'now', evidence=[{'text': 'x', 'href': 'ftp://x.test/a'}])]}
        self.rejected(board, 'evidence')

    def test_optional_text_fields_must_be_strings(self):
        self.rejected({'lanes': [board_lane('l1', 'now', worker=3)]}, 'worker')
        self.rejected({'lanes': [board_lane('l1', 'now', note=None, body=5)]}, 'body')

    def test_board_without_board_field_still_renders(self):
        r, out = self.render(board_data(None))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            parsed = parse_block(data_block(f.read()))
        self.assertNotIn('board', parsed)


class BoardDomTest(unittest.TestCase):
    """board 가 있을 때만 보드 섹션이 만들어지고 정체가 드러나는지 확인한다."""

    def setUp(self):
        if NODE is None:
            self.skipTest('node 가 없어 템플릿 스크립트를 실행할 수 없다')
        self.tmp = tempfile.mkdtemp(prefix='progress-board-dom-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def render_dom(self, data, now=FIXED_NOW, view=FIXED_NOW, storage=None, clicks=None):
        path = os.path.join(self.tmp, 'data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        out = os.path.join(self.tmp, 'out.html')
        r = run_render(path, out, env_extra={'DEADHD_NOW': now, 'DEADHD_PORT': '47410'})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding='utf-8') as f:
            cases = {'clicks': clicks} if clicks else None
            return run_linkify_harness(f.read(), cases=cases, fixed_now=view, storage=storage)

    def find(self, result, cls):
        found = []
        for tree in result['nodes'].values():
            for node in iter_nodes(tree):
                if cls in (node.get('cls') or '').split():
                    found.append(node)
        return found

    def lane_node(self, result, lid):
        for node in iter_nodes(result['nodes']['board']):
            if (node.get('data') or {}).get('lane') == lid:
                return node
        self.fail('레인 행을 찾지 못했다: ' + lid)

    def lane_detail(self, result, lid):
        for node in iter_nodes(result['nodes']['board']):
            kids = node.get('kids', [])
            for i, kid in enumerate(kids):
                if (kid.get('data') or {}).get('lane') == lid:
                    return kids[i + 1]
        self.fail('레인 상세를 찾지 못했다: ' + lid)

    def board_storage(self, state):
        return {BOARD_STATE_KEY: json.dumps(state, ensure_ascii=False)}

    def saved_board_state(self, result):
        return json.loads(result['storage'][BOARD_STATE_KEY])

    def test_board_absent_leaves_no_section(self):
        result = self.render_dom({'title': 'T', 'items': [mini_item('a', 'done')]})
        self.assertNotIn('board', result['nodes'])

    def test_board_section_is_built_from_data(self):
        board = {
            'stages': BOARD_STAGES,
            'lanes': [
                board_lane('l1', 'done', stage='검증', worker='deepseek'),
                board_lane('l2', 'now', stage='구현', worker='leader', note='검토 중'),
                board_lane('l3', 'blocked', stage='설계'),
            ],
        }
        result = self.render_dom(board_data(board))
        self.assertIn('board', result['nodes'])
        rows = self.find(result, 'bd-row')
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]['text'], '작업 · 작업자분석설계구현검증마지막 신호')
        self.assertEqual(
            [n['text'] for n in self.find(result, 'bd-grp')],
            ['▾주의 필요1', '▾진행 중1', '▾완료1'],
        )
        cells = self.lane_node(result, 'l2')
        self.assertEqual([c.get('cls') for c in cells['kids'] if 'bd-cell' in (c.get('cls') or '').split()],
                         ['bd-cell done', 'bd-cell done', 'bd-cell now', 'bd-cell pending'])

    def test_stalled_lane_is_marked_and_active_lane_is_not(self):
        board = {
            'stages': BOARD_STAGES,
            'lanes': [
                board_lane('stale', 'now', stage='구현', lastSignal='2026-10-03T09:30:00+09:00'),
                board_lane('live', 'now', stage='구현', lastSignal='2026-10-03T09:55:00+09:00'),
            ],
        }
        result = self.render_dom(board_data(board))
        stale = self.lane_node(result, 'stale')
        self.assertIn('bd-cell stall', [k.get('cls') for k in stale['kids']])
        self.assertEqual([n['text'] for n in iter_nodes(stale) if 'bd-ago' in (n.get('cls') or '').split()],
                         ['30분 전'])
        self.assertEqual([n.get('cls') for n in iter_nodes(stale) if 'bd-ago' in (n.get('cls') or '').split()],
                         ['bd-ago stall'])
        live = self.lane_node(result, 'live')
        self.assertIn('bd-cell now', [k.get('cls') for k in live['kids']])
        self.assertEqual([n.get('cls') for n in iter_nodes(live) if 'bd-ago' in (n.get('cls') or '').split()],
                         ['bd-ago'])
        tags = [n['text'] for n in self.find(result, 'bd-tag')]
        self.assertEqual(tags, ['정체 30분'])

    def test_lane_without_signal_says_so(self):
        board = {'stages': BOARD_STAGES, 'lanes': [board_lane('l1', 'now', stage='구현', stallAfter=5)]}
        result = self.render_dom(board_data(board))
        self.assertEqual([n['text'] for n in self.find(result, 'bd-ago')], ['신호 기록 없음'])
        self.assertIn('bd-ago none', [n['cls'] for n in self.find(result, 'bd-ago')])

    def test_started_at_is_the_fallback_signal(self):
        board = {'stages': BOARD_STAGES,
                 'lanes': [board_lane('l1', 'now', stage='구현', startedAt='2026-10-03T09:00:00+09:00')]}
        result = self.render_dom(board_data(board))
        self.assertEqual([n['text'] for n in self.find(result, 'bd-ago')], ['1시간 전'])
        self.assertIn('bd-cell stall', [n['cls'] for n in self.find(result, 'bd-cell')])

    def test_done_group_starts_collapsed(self):
        board = {'stages': BOARD_STAGES,
                 'lanes': [board_lane('l1', 'done', stage='검증'), board_lane('l2', 'now', stage='구현')]}
        result = self.render_dom(board_data(board))
        closed = [n for n in self.find(result, 'bd-grp') if 'closed' in (n.get('cls') or '').split()]
        self.assertEqual([n['text'] for n in closed], ['▾완료1'])

    def test_stage_missing_shows_one_text_cell(self):
        board = {'lanes': [board_lane('l1', 'now', stage='배포'), board_lane('l2', 'left')]}
        result = self.render_dom(board_data(board))
        header = [n['text'] for n in self.find(result, 'bd-st')]
        self.assertEqual(header, ['단계'])
        self.assertEqual([n['text'] for n in self.find(result, 'bd-cell-text')], ['배포', '—'])

    def test_worker_timeline_groups_bars(self):
        board = {
            'lanes': [
                board_lane('l1', 'done', worker='deepseek',
                           startedAt='2026-10-03T09:00:00+09:00', doneAt='2026-10-03T09:30:00+09:00'),
                board_lane('l2', 'now', worker='deepseek', startedAt='2026-10-03T09:40:00+09:00',
                           lastSignal='2026-10-03T09:55:00+09:00'),
                board_lane('l3', 'left'),
            ],
        }
        result = self.render_dom(board_data(board))
        names = [n['text'] for n in self.find(result, 'bd-tl-nm')]
        self.assertEqual(names, ['deepseek2개 레인'])
        bars = self.find(result, 'bd-bar')
        self.assertEqual([b['text'] for b in bars], ['l1', 'l2'])
        self.assertEqual([b.get('cls') for b in bars], ['bd-bar done', 'bd-bar now'])

    def test_english_labels(self):
        board = {'stages': BOARD_STAGES, 'lanes': [board_lane('l1', 'now', stage='구현')]}
        data = board_data(board)
        data['lang'] = 'en'
        result = self.render_dom(data)
        self.assertEqual(self.lane_node(result, 'l1')['kids'][0]['text'], 'l1l1 작업Unassigned')
        self.assertEqual(self.find(result, 'bd-wk')[0]['text'], 'Unassigned')
        self.assertEqual([n['text'] for n in self.find(result, 'bd-grp')], ['▾In progress1'])

    def test_demo_epic_has_exactly_one_stalled_lane(self):
        with open(DEMO_EPIC, encoding='utf-8') as f:
            data = json.load(f)
        # 데모의 now 는 14:30 이다. 그 시각으로 볼 때 정체는 SHOP-208 하나뿐이어야 한다.
        result = self.render_dom(data, view='2026-10-07T14:30:00+09:00')
        stalled = [n for n in self.find(result, 'bd-ago') if 'stall' in (n.get('cls') or '').split()]
        self.assertEqual([n['text'] for n in stalled], ['18분 전'])
        active = self.lane_node(result, 'SHOP-205')
        self.assertIn('bd-cell now', [k.get('cls') for k in active['kids']])
        self.assertEqual([n['text'] for n in self.find(result, 'bd-tag')], ['정체 18분', '막힘'])

    def test_saved_board_state_is_applied(self):
        board = {'stages': BOARD_STAGES,
                 'lanes': [board_lane('l1', 'done', stage='검증'), board_lane('l2', 'now', stage='구현')]}
        result = self.render_dom(
            board_data(board),
            storage=self.board_storage({'tab': 'time', 'open': ['l2'], 'closed': {'finished': False}}),
        )
        self.assertEqual([n['attrs'].get('aria-selected') for n in self.find(result, 'bd-tab')],
                         ['false', 'true'])
        self.assertIn('open', (self.lane_detail(result, 'l2').get('cls') or '').split())
        self.assertNotIn('open', (self.lane_detail(result, 'l1').get('cls') or '').split())
        self.assertEqual([n.get('cls') for n in self.find(result, 'bd-grp')],
                         ['bd-grp active', 'bd-grp finished'])

    def test_stale_saved_lane_id_is_ignored(self):
        board = {'stages': BOARD_STAGES, 'lanes': [board_lane('l1', 'now', stage='구현')]}
        result = self.render_dom(board_data(board), storage=self.board_storage({'open': ['gone']}))
        self.assertNotIn('open', (self.lane_detail(result, 'l1').get('cls') or '').split())
        self.assertEqual([n['text'] for n in self.find(result, 'bd-grp')], ['▾진행 중1'])

    def test_board_interactions_are_saved(self):
        board = {'stages': BOARD_STAGES,
                 'lanes': [board_lane('l1', 'done', stage='검증'), board_lane('l2', 'now', stage='구현')]}
        result = self.render_dom(board_data(board), clicks=[
            {'cls': 'bd-tab', 'nth': 1},
            {'cls': 'bd-row', 'lane': 'l2'},
            {'cls': 'bd-grp', 'nth': 0},
        ])
        self.assertEqual(self.saved_board_state(result),
                         {'tab': 'time', 'open': ['l2'], 'closed': {'active': True}})

    def test_done_time_is_not_a_signal(self):
        board = {'stages': BOARD_STAGES, 'lanes': [board_lane(
            'l1', 'now', stage='구현',
            startedAt='2026-10-03T09:00:00+09:00', doneAt='2026-10-03T09:58:00+09:00')]}
        result = self.render_dom(board_data(board))
        self.assertEqual([n['text'] for n in self.find(result, 'bd-ago')], ['1시간 전'])
        self.assertIn('bd-ago stall', [n.get('cls') for n in self.find(result, 'bd-ago')])


if __name__ == '__main__':
    unittest.main()
