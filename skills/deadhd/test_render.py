#!/usr/bin/env python3
"""render.py 의 렌더 결과와 입력 검증을 확인한다."""
import json
import os
import re
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


def run_render(data_path, out_path, theme=None, config_path=None):
    env = dict(os.environ)
    env['DEADHD_CONFIG'] = config_path if config_path is not None else MISSING_CONFIG
    env.pop('XDG_CONFIG_HOME', None)
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


if __name__ == '__main__':
    unittest.main()
