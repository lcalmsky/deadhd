#!/usr/bin/env python3
"""docs/demos 의 사례별 데이터를 테마별로 렌더해 테마 갤러리 docs/themes.png 를 만든다. Chrome 헤드리스 실행 파일이 필요하다."""
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RENDER = os.path.join(REPO, 'skills', 'deadhd', 'render.py')
GALLERY_OUT = os.path.join(HERE, 'themes.png')

CHROME = os.environ.get('CHROME') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

CASES = {
    'lanes-blocked': '2026-10-02T15:20:00+09:00',
    'parallel':      '2026-10-01T09:30:00+09:00',
    'overnight':     '2026-10-02T22:40:00+09:00',
    'done':          '2026-09-30T18:10:00+09:00',
}

# (테마 키, 표시 이름, 사례). COLS 열로 왼쪽에서 오른쪽, 위에서 아래 순서
PANELS = [
    ('dark', '오로라', 'lanes-blocked'), ('light', '라이트', 'parallel'),
    ('neon', '사이버펑크 네온', 'overnight'), ('synthwave', '신스웨이브 선셋', 'done'),
    ('matrix', '매트릭스 터미널', 'parallel'), ('nord', '노르드 아크틱', 'lanes-blocked'),
    ('paper', '페이퍼 노트북', 'done'), ('sakura', '사쿠라', 'overnight'),
    ('ink', '잉크', 'parallel'),
]

# --lang en 일 때 같은 자리에 쓰는 영어 표시 이름
PANEL_NAMES_EN = {
    'dark': 'Aurora', 'light': 'Light', 'neon': 'Cyberpunk Neon', 'synthwave': 'Synthwave Sunset',
    'matrix': 'Matrix Terminal', 'nord': 'Nord Arctic', 'paper': 'Paper Notebook', 'sakura': 'Sakura',
    'ink': 'Ink',
}

PANEL_W, PANEL_H = 1200, 1780
GALLERY_W, PAD, GAP, HEADER_H = 2100, 20, 20, 46
COLS = 3

# 브라우저 시계를 사례 시각으로 고정한다. 인자 없는 new Date() 와 Date.now 만 바꾸고
# 인자를 받는 호출은 그대로 둔다.
CLOCK = """<script>(function(){var R=Date,F=new R('%s').getTime();
function D(){var a=[].slice.call(arguments);var x=a.length===0?new R(F):new (Function.prototype.bind.apply(R,[null].concat(a)))();
return new.target?x:R.apply(null,a);}
D.prototype=R.prototype;D.now=function(){return F};D.parse=R.parse;D.UTC=R.UTC;window.Date=D;})();</script>"""


def die(msg):
    sys.stderr.write('capture_themes.py: ' + msg + '\n')
    sys.exit(1)


def chrome_shot(args, out_path, timeout=120):
    # 이전 결과가 남아 있으면 그것을 새 결과로 잘못 볼 수 있어 지우고 시작한다.
    if os.path.exists(out_path):
        os.remove(out_path)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    shot = False
    while time.time() < deadline:
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            # 파일이 다 쓰인 뒤에도 프로세스가 끝나지 않는 경우가 있어 크기가 멈추면 끝난 것으로 본다.
            size, settle = -1, time.time() + 5
            while time.time() < settle:
                time.sleep(0.3)
                current = os.path.getsize(out_path)
                if current == size:
                    break
                size = current
            shot = True
            break
        if proc.poll() is not None:
            shot = os.path.exists(out_path) and os.path.getsize(out_path) > 0
            break
        time.sleep(0.2)
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)
    if not shot:
        die('Chrome 이 %s 를 만들지 못했다' % out_path)


def chrome_args(ud_dir, window, extra):
    return [
        CHROME, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
        '--disable-crash-reporter', '--hide-scrollbars', '--force-device-scale-factor=1',
        '--virtual-time-budget=5000', '--user-data-dir=' + ud_dir, '--window-size=%d,%d' % window,
    ] + extra


def render_panel(case, theme, work_dir, demos_dir, session=None, now=None, extra_env=None):
    src = os.path.join(demos_dir, case + '.json')
    name = '%s.%s.html' % (case, theme) if session is None else '%s.%s.%s.html' % (case, theme, session)
    html = os.path.join(work_dir, name)
    fixed = now or CASES[case]
    # render.py 는 페이지 옆에 허브와 세션 상태도 쓴다. 캡처가 이 컴퓨터의 실제 허브·상태를
    # 덮지 않도록 작업 디렉터리 안 경로를 주고, 세션 id 는 상속하지 않는다.
    env = dict(os.environ, DEADHD_NOW=fixed, TZ='Asia/Seoul',
               DEADHD_HUB=os.path.join(work_dir, 'hub.html'),
               DEADHD_STATE_DIR=os.path.join(work_dir, 'state'))
    env.pop('CLAUDE_CODE_SESSION_ID', None)
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, RENDER, '--theme', theme]
    if session is not None:
        cmd += ['--session', session]
    result = subprocess.run(cmd + [src, html], capture_output=True, text=True, env=env)
    if result.returncode != 0:
        die('%s/%s 렌더 실패: %s' % (case, theme, (result.stderr or result.stdout).strip()))
    with open(html, encoding='utf-8') as f:
        page = f.read()
    page = page.replace('<head>', '<head>\n' + CLOCK % fixed, 1)
    with open(html, 'w', encoding='utf-8') as f:
        f.write(page)
    return html


def gallery_html(shots, card_w, lang):
    cells = ''.join(
        '<figure class="panel"><figcaption><b>%s</b><code>%s</code></figcaption>'
        '<img src="file://%s" alt=""></figure>' % (name, theme, png)
        for (theme, name, _case), png in shots
    )
    return """<!doctype html>
<html lang="%s"><head><meta charset="utf-8"><style>
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: #0d0d12; font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; }
.grid { display: grid; grid-template-columns: repeat(%d, %dpx); gap: %dpx; padding: %dpx; }
.panel { margin: 0; background: #1c1c22; border-radius: 12px; overflow: hidden; }
figcaption { height: %dpx; display: flex; align-items: baseline; gap: 10px; padding: 0 16px;
  border-bottom: 1px solid rgba(255,255,255,.06); }
figcaption b { color: #fff; font-size: 18px; font-weight: 700; }
figcaption code { color: #8a8f9e; font-size: 13px; font-family: ui-monospace, "SF Mono", monospace; }
img { display: block; width: 100%%; }
</style></head><body><div class="grid">%s</div></body></html>
""" % (lang, COLS, card_w, GAP, PAD, HEADER_H, cells)


def main(argv):
    lang = 'ko'
    rest = argv[1:]
    if rest[:1] == ['--lang']:
        if len(rest) < 2:
            die('사용법: capture_themes.py [--lang ko|en]')
        lang, rest = rest[1], rest[2:]
    if lang not in ('ko', 'en'):
        die('알 수 없는 언어: %s (ko/en 중 하나)' % lang)
    if rest:
        die('사용법: capture_themes.py [--lang ko|en]')
    if not os.path.exists(CHROME):
        die('Chrome 을 찾지 못했다: %s (환경 변수 CHROME 로 지정)' % CHROME)

    demos_dir = os.path.join(HERE, 'demos', 'en') if lang == 'en' else os.path.join(HERE, 'demos')
    gallery_out = os.path.join(HERE, 'themes.en.png') if lang == 'en' else GALLERY_OUT

    keep_dir = os.environ.get('DEADHD_PANEL_DIR')
    work_dir = keep_dir if keep_dir else tempfile.mkdtemp(prefix='deadhd-panels-')
    os.makedirs(work_dir, exist_ok=True)
    # Chrome 프로필은 결과물과 섞이지 않게 따로 두고 항상 지운다.
    ud_root = tempfile.mkdtemp(prefix='deadhd-chrome-')

    try:
        shots = []
        for i, (theme, name, case) in enumerate(PANELS):
            if lang == 'en':
                name = PANEL_NAMES_EN[theme]
            html = render_panel(case, theme, work_dir, demos_dir)
            png = os.path.join(work_dir, '%02d-%s-%s.png' % (i, theme, case))
            chrome_shot(chrome_args(os.path.join(ud_root, 'ud-%d' % i), (PANEL_W, PANEL_H),
                                    ['--screenshot=' + png, 'file://' + html]), png)
            print('panel: %s %s (%s)' % (theme, name, case))
            shots.append(((theme, name, case), png))

        card_w = (GALLERY_W - 2 * PAD - (COLS - 1) * GAP) // COLS
        rows = math.ceil(len(shots) / COLS)
        row_h = HEADER_H + PANEL_H * card_w / PANEL_W
        total_h = 2 * PAD + rows * row_h + (rows - 1) * GAP
        html = os.path.join(work_dir, 'gallery.html')
        with open(html, 'w', encoding='utf-8') as f:
            f.write(gallery_html(shots, card_w, lang))
        # 캡처가 실패해도 기존 갤러리를 잃지 않게 임시 파일에 찍고 옮긴다.
        tmp_png = gallery_out + '.tmp.png'
        chrome_shot(chrome_args(os.path.join(ud_root, 'ud-gallery'), (GALLERY_W, int(math.ceil(total_h)) + 6),
                                ['--screenshot=' + tmp_png, 'file://' + html]), tmp_png)
        os.replace(tmp_png, gallery_out)
        print('gallery: %s' % gallery_out)
        if keep_dir:
            print('panels: %s' % work_dir)
    finally:
        shutil.rmtree(ud_root, ignore_errors=True)
        if not keep_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv)
