#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: share.sh [--update] <file.html>" >&2
  exit 2
}

update=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --update)
      update=1
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "unknown option: $1" >&2
      usage
      ;;
    *)
      break
      ;;
  esac
done

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  usage
fi

file=$1
if [ ! -f "$file" ]; then
  echo "no such file: $file" >&2
  exit 2
fi

if ! command -v orca >/dev/null 2>&1; then
  echo "skip: orca-artifact orca not found" >&2
  echo "fallback: browser"
  exit 3
fi

action=share
if [ -n "$update" ]; then
  action=update
fi

share_raw=$(orca artifacts "$action" "$file" --json 2>&1) && share_rc=0 || share_rc=$?

share_parsed=$(SHARE_RAW="$share_raw" python3 <<'PY'
import json
import os

raw = os.environ.get("SHARE_RAW", "")


def dig(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, str):
                return v
        for v in obj.values():
            found = dig(v, key)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = dig(v, key)
            if found:
                return found
    return None


def load(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


data = load(raw)
if data is None:
    for line in raw.splitlines():
        data = load(line.strip())
        if data is not None:
            break

ok = False
url = ""
err = ""
if isinstance(data, dict):
    ok = data.get("ok") is True
    e = data.get("error")
    if isinstance(e, dict):
        err = str(e.get("code") or e.get("message") or "")
    elif isinstance(e, str):
        err = e
    if not err:
        m = data.get("message")
        if isinstance(m, str):
            err = m
    url = dig(data, "shareUrl") or ""
    if not url:
        alt = dig(data, "url")
        if alt and alt.startswith("http"):
            url = alt

stripped = raw.strip()
first = stripped.splitlines()[0] if stripped else ""

fields = ("ok=" + ("1" if ok else "0"), "url=" + url, "err=" + err, "first=" + first)
for field in fields:
    print(field.replace("\n", " ").replace("\r", " "))
PY
)

share_ok=""
share_url=""
share_err=""
share_first=""
while IFS= read -r line; do
  case "$line" in
    ok=*) share_ok=${line#ok=} ;;
    url=*) share_url=${line#url=} ;;
    err=*) share_err=${line#err=} ;;
    first=*) share_first=${line#first=} ;;
  esac
done <<< "$share_parsed"

reason="$share_err"
if [ -z "$reason" ]; then
  reason="$share_first"
fi
if [ -z "$reason" ]; then
  reason="no share URL"
fi

if [ "$share_rc" -ne 0 ] || [ "$share_ok" != "1" ] || [ -z "$share_url" ]; then
  echo "skip: orca-artifact $reason" >&2
  echo "fallback: browser"
  exit 3
fi

echo "shared: $share_url"
exit 0
