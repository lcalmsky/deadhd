#!/usr/bin/env python3
"""docs/demos 의 진행 중 사례를 보기 모드(스트립·타임라인·타일)와 세로·가로 배치로 캡처해 docs/views.png 를 만든다. Chrome 헤드리스 실행 파일이 필요하다."""
import json
import math
import os
import shutil
import sys
import tempfile

from capture_themes import CASES, CHROME, HERE, chrome_args, chrome_shot, die, render_panel

CASE, THEME = 'parallel', 'dark'
VIEWS = {'a': ('스트립', 'Strip'), 'b': ('타임라인', 'Timeline'), 'c': ('타일', 'Tiles')}
# (보기, 배치, 창 크기). 세로는 세 보기를 한 줄에, 가로는 타임라인 하나를 전체 폭으로 둔다.
# 창 크기는 자동 배치가 창 비율로 그 배치를 고르게 맞춘다
SHOTS = [('a', 'port', (520, 820)), ('b', 'port', (520, 820)), ('c', 'port', (520, 820)), ('b', 'land', (1280, 540))]
ORIENT_NAMES = {'port': ('세로', 'Portrait'), 'land': ('가로', 'Landscape')}

GALLERY_W, PAD, GAP, HEADER_H = 900, 20, 20, 34


def seed_view(html, key, view):
    with open(html, encoding='utf-8') as f:
        page = f.read()
    seed = '<script>try{sessionStorage.setItem(%s,%s)}catch(e){}</script>' % (
        json.dumps(key, ensure_ascii=False), json.dumps(json.dumps({'v': view, 'o': 'auto', 'chip': 'done'})))
    page = page.replace('<head>', '<head>\n' + seed, 1)
    out = html.replace('.html', '.%s.html' % view)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(page)
    return out


def gallery_html(rows, lang):
    col_w = (GALLERY_W - 2 * PAD - 2 * GAP) // 3
    cells = ''.join(
        '<figure class="panel%s"><figcaption><b>%s</b><code>%s</code></figcaption>'
        '<img src="file://%s" alt=""></figure>' % (' wide' if orient == 'land' else '', name, sub, png)
        for orient, name, sub, png in rows
    )
    return """<!doctype html>
<html lang="%s"><head><meta charset="utf-8"><style>
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: #0d0d12; font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; }
.grid { display: grid; grid-template-columns: repeat(3, %dpx); gap: %dpx; padding: %dpx; align-items: start; }
.panel.wide { grid-column: 1 / -1; }
.panel { margin: 0; background: #1c1c22; border-radius: 12px; overflow: hidden; }
figcaption { height: %dpx; display: flex; align-items: baseline; gap: 10px; padding: 0 16px;
  border-bottom: 1px solid rgba(255,255,255,.06); }
figcaption b { color: #fff; font-size: 12px; font-weight: 700; }
figcaption code { color: #8a8f9e; font-size: 10px; font-family: ui-monospace, "SF Mono", monospace; }
img { display: block; width: 100%%; }
</style></head><body><div class="grid">%s</div></body></html>
""" % (lang, col_w, GAP, PAD, HEADER_H, cells), col_w


def main(argv):
    lang = 'ko'
    rest = argv[1:]
    if rest[:1] == ['--lang']:
        if len(rest) < 2:
            die('사용법: capture_views.py [--lang ko|en]')
        lang, rest = rest[1], rest[2:]
    if lang not in ('ko', 'en') or rest:
        die('사용법: capture_views.py [--lang ko|en]')
    if not os.path.exists(CHROME):
        die('Chrome 을 찾지 못했다: %s (환경 변수 CHROME 로 지정)' % CHROME)

    demos_dir = os.path.join(HERE, 'demos', 'en') if lang == 'en' else os.path.join(HERE, 'demos')
    out_png = os.path.join(HERE, 'views.en.png' if lang == 'en' else 'views.png')
    with open(os.path.join(demos_dir, CASE + '.json'), encoding='utf-8') as f:
        data = json.load(f)
    # template.html 의 KEY + ':view' 와 같아야 한다
    key = 'progress:%s:%s:view' % (data.get('key') or '', data.get('title') or '')

    work_dir = tempfile.mkdtemp(prefix='deadhd-views-')
    ud_root = tempfile.mkdtemp(prefix='deadhd-chrome-')
    try:
        base = render_panel(CASE, THEME, work_dir, demos_dir)
        rows = []
        for view, orient, window in SHOTS:
            html = seed_view(base, key, view)
            png = os.path.join(work_dir, '%s-%s.png' % (orient, view))
            chrome_shot(chrome_args(os.path.join(ud_root, 'ud-%s-%s' % (orient, view)), window,
                                    ['--screenshot=' + png, 'file://' + html]), png)
            name = VIEWS[view][1 if lang == 'en' else 0]
            sub = ORIENT_NAMES[orient][1 if lang == 'en' else 0]
            rows.append((orient, name, sub, png))
            print('view: %s %s' % (view, orient))

        html = os.path.join(work_dir, 'gallery.html')
        page, col_w = gallery_html(rows, lang)
        with open(html, 'w', encoding='utf-8') as f:
            f.write(page)
        port_h = max(w[1] / w[0] for _, o, w in SHOTS if o == 'port') * col_w
        land_h = max(w[1] / w[0] for _, o, w in SHOTS if o == 'land') * (GALLERY_W - 2 * PAD)
        total_h = 2 * PAD + GAP + 2 * HEADER_H + port_h + land_h
        tmp_png = out_png + '.tmp.png'
        chrome_shot(chrome_args(os.path.join(ud_root, 'ud-gallery'), (GALLERY_W, int(math.ceil(total_h)) + 6),
                                ['--screenshot=' + tmp_png, 'file://' + html]), tmp_png)
        os.replace(tmp_png, out_png)
        print('gallery: %s' % out_png)
    finally:
        shutil.rmtree(ud_root, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv)
