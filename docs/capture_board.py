#!/usr/bin/env python3
"""docs/demos/rolling.json 을 렌더해 레인 보드 그림 docs/board.png 를 만든다. Chrome 헤드리스 실행 파일이 필요하다."""
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time

from capture_themes import CHROME, HERE, chrome_args, chrome_shot, die, render_panel

CASE, THEME = 'rolling', 'dark'
# 보드의 정체 판정은 브라우저 시계로 돈다. 「지금」을 고정하지 않으면 찍는 시각에 따라 정체 레인이 달라진다.
NOW = '2026-10-07T14:30:00+09:00'
WIDTH = 1200
# 창 높이는 보드 섹션이 끝나는 지점이라 그때그때 다르다. 높이만 재는 창을 한 번 띄워 페이지가 알려 준 값을 쓴다.
MEASURE_H = 200
SIZE_MARK = 'deadhd-board-height:'
# capture_hub 과 같은 표본이다. 이 컴퓨터의 실제 기록을 읽지 않고 보정 계수 1.6 을 그대로 재현한다.
HISTORY_ROWS = ({'est': 10, 'actual': 16}, {'est': 20, 'actual': 32}, {'est': 30, 'actual': 48})

# 별 배경이 쓰는 난수와 애니메이션을 고정해, 두 번 찍어도 같은 그림이 나오게 한다.
# 카드 목록은 보드 아래라 그림에서 뺀다. 다 그린 뒤 페이지가 자기 높이를 stderr 로 알려 준다.
FIX = ("<script>(function(){"
       "var s=20261007;Math.random=function(){s=(s*1103515245+12345)%2147483648;return s/2147483648;};"
       "var css=document.createElement('style');"
       "css.textContent='*,*::before,*::after{animation:none !important;transition:none !important}'"
       "+'#cards,footer{display:none !important}';"
       "document.head.appendChild(css);"
       "window.addEventListener('load',function(){"
       "document.body.classList.add('no-entrance');"
       "console.log('" + SIZE_MARK + "'+document.documentElement.scrollHeight);});})();</script>")


def content_height(html):
    # Chrome 은 그림을 다 쓴 뒤에도 끝나지 않을 때가 있어, 값을 읽으면 바로 끝낸다.
    ud_dir = tempfile.mkdtemp(prefix='deadhd-board-measure-')
    args = chrome_args(ud_dir, (WIDTH, MEASURE_H),
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
                found = re.search(re.escape(SIZE_MARK.encode()) + rb'(\d+)', buf)
                if found:
                    return int(found.group(1))
            elif proc.poll() is not None:
                break
        return None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        shutil.rmtree(ud_dir, ignore_errors=True)


def main(argv):
    lang = 'ko'
    rest = argv[1:]
    if rest[:1] == ['--lang']:
        if len(rest) < 2:
            die('사용법: capture_board.py [--lang ko|en]')
        lang, rest = rest[1], rest[2:]
    if lang not in ('ko', 'en') or rest:
        die('사용법: capture_board.py [--lang ko|en]')
    if not os.path.exists(CHROME):
        die('Chrome 을 찾지 못했다: %s (환경 변수 CHROME 로 지정)' % CHROME)

    demos_dir = os.path.join(HERE, 'demos', 'en') if lang == 'en' else os.path.join(HERE, 'demos')
    out_png = os.path.join(HERE, 'board.en.png' if lang == 'en' else 'board.png')

    work_dir = tempfile.mkdtemp(prefix='deadhd-board-')
    ud_root = tempfile.mkdtemp(prefix='deadhd-chrome-')
    try:
        history = os.path.join(work_dir, 'history.jsonl')
        with open(history, 'w', encoding='utf-8') as f:
            for row in HISTORY_ROWS:
                f.write(json.dumps(row) + '\n')
        html = render_panel(CASE, THEME, work_dir, demos_dir, now=NOW,
                            extra_env={'DEADHD_HISTORY': history})
        with open(html, encoding='utf-8') as f:
            page = f.read()
        page = page.replace('<head>', '<head>\n' + FIX, 1)
        with open(html, 'w', encoding='utf-8') as f:
            f.write(page)

        height = content_height(html)
        if height is None:
            die('페이지가 자기 높이를 알려 주지 않았다: %s' % html)

        # 캡처가 실패해도 기존 그림을 잃지 않게 임시 파일에 찍고 옮긴다.
        tmp_png = out_png + '.tmp.png'
        chrome_shot(chrome_args(os.path.join(ud_root, 'ud-board'), (WIDTH, height),
                                ['--screenshot=' + tmp_png, 'file://' + html]), tmp_png)
        os.replace(tmp_png, out_png)
        print('board: %s (%dx%d)' % (out_png, WIDTH, height))
    finally:
        shutil.rmtree(ud_root, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv)
