#!/usr/bin/env python3
"""deadhd 기본 열기 위치·테마·글꼴 설정을 읽고 쓴다."""
import json
import os
import sys
import tempfile

ALLOWED = {
    'open': ('auto', 'orca', 'browser', 'desktop'),
    'view': ('html', 'band', 'statusline'),
    'theme': ('system', 'light', 'dark', 'neon', 'synthwave', 'matrix', 'nord', 'paper', 'sakura', 'ink'),
    'font': ('default', 'pretendard', 'noto-sans', 'plex-sans', 'gothic-a1', 'nanum-gothic', 'noto-serif', 'nanum-myeongjo', 'hahmlet', 'gowun-batang', 'do-hyeon', 'black-han-sans'),
}
KEYS = '|'.join(ALLOWED)


def config_path():
    override = os.environ.get('DEADHD_CONFIG')
    if override:
        return override
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'deadhd', 'config.json')


def read_config(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_value(key):
    value = read_config(config_path()).get(key)
    return value if value in ALLOWED.get(key, ()) else None


def cmd_get(key):
    if key not in ALLOWED:
        print('usage: config.py get <%s>' % KEYS, file=sys.stderr)
        return 2
    value = read_config(config_path()).get(key)
    if value not in ALLOWED[key]:
        if value is not None:
            print('warning: unknown %s value %r, treating as unset' % (key, value), file=sys.stderr)
        print('unset')
        return 0
    print(value)
    return 0


def cmd_set(key, value):
    if key not in ALLOWED:
        print('usage: config.py set <%s> <value>' % KEYS, file=sys.stderr)
        return 2
    allowed = ALLOWED[key]
    if value not in allowed:
        print('invalid value: %s (allowed: %s)' % (value, ', '.join(allowed)), file=sys.stderr)
        return 2
    path = config_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    data = read_config(path)
    data[key] = value
    fd, tmp = tempfile.mkstemp(dir=directory or '.', prefix='.config-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    print('saved: %s=%s %s' % (key, value, path))
    return 0


def main(argv):
    if len(argv) >= 1 and argv[0] == 'path':
        if len(argv) != 1:
            print('usage: config.py path', file=sys.stderr)
            return 2
        print(config_path())
        return 0
    if len(argv) >= 1 and argv[0] == 'get':
        if len(argv) != 2:
            print('usage: config.py get <%s>' % KEYS, file=sys.stderr)
            return 2
        return cmd_get(argv[1])
    if len(argv) >= 1 and argv[0] == 'set':
        if len(argv) != 3:
            print('usage: config.py set <%s> <value>' % KEYS, file=sys.stderr)
            return 2
        return cmd_set(argv[1], argv[2])
    print('usage: config.py get <%s> | set <%s> <value> | path' % (KEYS, KEYS), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
