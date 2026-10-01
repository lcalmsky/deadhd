#!/usr/bin/env bash
set -euo pipefail

mode_arg=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode)
      if [ "$#" -lt 2 ]; then
        echo "usage: open.sh [--mode auto|orca|browser|desktop] <file.html>" >&2
        exit 2
      fi
      mode_arg=$2
      shift 2
      ;;
    --mode=*)
      mode_arg=${1#--mode=}
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "unknown option: $1" >&2
      echo "usage: open.sh [--mode auto|orca|browser|desktop] <file.html>" >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [ "$#" -lt 1 ] || [ -z "$1" ]; then
  echo "usage: open.sh [--mode auto|orca|browser|desktop] <file.html>" >&2
  exit 2
fi

script_dir=$(cd "$(dirname "$0")" && pwd)

mode=
if [ -n "$mode_arg" ]; then
  mode=$mode_arg
else
  saved=$(python3 "$script_dir/config.py" get open 2>/dev/null || true)
  if [ -n "$saved" ] && [ "$saved" != "unset" ]; then
    mode=$saved
  fi
fi
mode=${mode:-auto}

case "$mode" in
  auto|orca|browser|desktop) ;;
  *)
    echo "invalid mode: $mode (allowed: auto, orca, browser, desktop)" >&2
    exit 2
    ;;
esac

file=$1
if [ ! -f "$file" ]; then
  echo "no such file: $file" >&2
  exit 2
fi

abs=$(cd "$(dirname "$file")" && pwd)/$(basename "$file")
url=$(python3 -c 'import sys, urllib.parse; print("file://" + urllib.parse.quote(sys.argv[1]))' "$abs")
dry=${PROGRESS_OPEN_DRY:-}

open_orca_tab() {
  if [ -n "$dry" ]; then
    echo "dry: orca tab create --url $url --json"
    echo "opened: orca-tab $abs"
    return 0
  fi
  if orca tab create --url "$url" --json >/dev/null 2>&1; then
    echo "opened: orca-tab $abs"
    return 0
  fi
  echo "skip: orca-tab orca tab create 실패" >&2
  return 1
}

open_browser() {
  if command -v open >/dev/null 2>&1 && [ "$(uname)" = "Darwin" ]; then
    if [ -n "$dry" ]; then
      echo "dry: open $abs"
      echo "opened: browser $abs"
      return 0
    fi
    if open "$abs"; then
      echo "opened: browser $abs"
      return 0
    fi
    echo "skip: browser open 실패" >&2
  fi

  if command -v xdg-open >/dev/null 2>&1; then
    if [ -n "$dry" ]; then
      echo "dry: xdg-open $abs"
      echo "opened: browser $abs"
      return 0
    fi
    if xdg-open "$abs"; then
      echo "opened: browser $abs"
      return 0
    fi
    echo "skip: browser xdg-open 실패" >&2
  fi

  echo "opened: none $abs"
  return 0
}

if [ "$mode" = "desktop" ]; then
  echo "opened: desktop $abs"
  exit 0
fi

if [ "$mode" = "orca" ]; then
  if command -v orca >/dev/null 2>&1; then
    open_orca_tab && exit 0
  else
    echo "skip: orca-tab orca 명령 없음" >&2
  fi
  open_browser
  exit 0
fi

if [ "$mode" = "browser" ]; then
  open_browser
  exit 0
fi

# auto
if [ -n "${ORCA_WORKTREE_ID:-}" ] && command -v orca >/dev/null 2>&1; then
  open_orca_tab && exit 0
fi

open_browser
exit 0
