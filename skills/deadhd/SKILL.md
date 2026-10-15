---
name: deadhd
description: Show a live checklist page of what this session has done, is doing now, and has left, opened beside the terminal and kept updated while the task runs. Use when the user types /deadhd or $deadhd, or asks "지금 뭐 하고 있어", "진행 상황 띄워줘", "체크리스트로 보여줘", or asks "what are you doing now", "show progress", "show me a checklist".
argument-hint: "[setup] [hub [--clean]] [-h|-o|-c] [--open auto|orca|browser|desktop] [--view html|band|statusline] [--theme system|light|dark|neon|synthwave|matrix|nord|paper|sakura|ink] [--font default|pretendard|noto-sans|plex-sans|gothic-a1|nanum-gothic|noto-serif|nanum-myeongjo|hahmlet|gowun-batang|do-hyeon|black-han-sans] [off]"
---

# deadhd

`$ARGUMENTS`

A status page for the task running in this session. The reader glanced away for an hour and wants to know, in one look, what happened. The design is fixed in `template.html`; you write only the data.

`<skill-dir>` below is the directory that contains this SKILL.md. Everything the skill needs is in it; files outside it are optional and used only when present.

## Parse the arguments

- `off`: run `python3 <skill-dir>/state.py --off`, then stop updating the JSON for this session. It marks the session's state file: the band and the status line drop the checklist and show the `켜기` button, the open page's status band says updates are off, and the hub lists the session with the ended ones. `off: none` means there was nothing to turn off; when it exits 1 (no session id, as in Codex) just stop updating. Reply in one line and stop. The next `/deadhd` run that writes the JSON and renders turns it back on.
- `hub`: write the hub page with `python3 <skill-dir>/hub.py` and open it with `bash <skill-dir>/open.sh [--mode <mode>] <hub path printed by hub.py>`. Reply with where it opened and stop. Pass `--theme` and `--font` to hub.py as well when this run has them. The hub opens through `open.sh` like a session page, so it uses the same localhost server.
- `hub --clean`: run `python3 <skill-dir>/hub.py --clean` (with the same `--theme`/`--font`) instead; it deletes the state files of ended, off, and past sessions before writing the hub — their data and page files stay — and prints `cleaned: N` before `rendered:`. Open the hub the same way and say how many it removed.
- `-h` (default): open the page in a browser tab beside the terminal. Naming it also opens the page and keeps it updated under a `band` or `statusline` default (see Where it shows).
- `-o`: publish as an Orca artifact (a shareable web page) with the `orca` CLI. Without it, or when publishing fails, fall back to `-h` and say so.
- `-c`: publish as a Claude artifact with the `Artifact` tool. Without that tool, fall back to `-h` and say so.
- `setup`: read `<skill-dir>/references/setup.md` and follow it: ask for the default open location, the display, the theme, and the heading font, and save them. After saving, reply in one line and stop.
- `--open <mode>`: use this mode for this run only, instead of the saved default. Pass it to open.sh as `--mode <mode>`.
- `--view <value>`: draw in this view and record it as this session's view, instead of the one the state file or the saved default has. One of `html`, `band`, `statusline`. Pass it to render.py as `--view <value>`. The session keeps it until another `--view` changes it.
- `--theme <theme>`: render with this theme for this run only, instead of the saved one. One of the values listed in `argument-hint`. Pass it to render.py as `--theme <theme>`.
- `--font <preset>`: render with this heading font preset for this run only, instead of the saved one. One of the values listed in `argument-hint`. Pass it to render.py as `--font <preset>`.

## Where it shows

`view` decides where the progress is drawn. It is the first of these that exists: the `--view` value on this run, the view the state file already records for this session, the Setup default, and `html` when there is none. `render.py` writes the choice into the state file, and the mod draws the view it reads there (the state file's, else the Setup default, else `html`), so a render without `--view` — the hooks' own re-render, the mod's `--page` — keeps this session's view instead of falling back to the default.

- `html`: the page, opened in a browser tab. This is the only view outside Claude Code.
- `band`: a one-line band above the prompt, in Claude Code. Nothing is opened; the page is rendered only when someone asks for it (`/deadhd-open`, the band's `열기` button).
- `statusline`: a hint line under the prompt, in Claude Code. Same as `band`, with more fields on the line.

`band` and `statusline` are drawn by the deadhd mod, a Claude Code plugin: `skills/deadhd/hooks/register.tsx`, loaded through the plugin's `hooks/hooks.json`. The mod reads the same state file the skill writes and needs no separate step, and it watches the session's own events (a turn's start and end, tool calls, compactions) so the session state — `● 작업 중 N분째`, `⌨️ 입력 대기 N분째`, `🔧 도구이름 N초 전`, `🗜 압축 N` — is drawn from the moment the session starts, before this skill has written anything. The saved `hud` value turns that watch off (see Setup): with `hud off` the line is drawn only once the state file is there. A session with no state file yet has no page to open, so the mod draws a `켜기` button where the band's `열기` button stands; pressing it sends the model a prompt to run this skill, and running the skill attaches the checklist fields to the same line. The view is `html` where the mod cannot run: Codex (`$deadhd`), any host that does not load Claude Code plugins, and surfaces that draw no band or hint line even inside Claude Code — the VS Code extension and `claude -p` name `CLAUDE_CODE_SESSION_ID` and still show nothing. Work as the `html` view there, and do not ask the display question outside Claude Code.

On a `band` or `statusline` view the skill does not call `open.sh`. Reply with one line saying the band (or the status line) is showing and that the page is opened with `/deadhd-open` or the band's `열기` button. A run that names `-h`, `-o`, `-c`, or `--view html` still opens the page and keeps it updated: on the first render pass `--page` to `render.py` so the HTML file exists (the view itself stays), then open or publish it as Deliver says. `--view html` also changes this session's view to `html` from then on.

## Setup

On an ordinary run that is not `-c`, `-o`, `--open`, `off`, or `setup`, run `python3 <skill-dir>/config.py get open`, `python3 <skill-dir>/config.py get view`, `python3 <skill-dir>/config.py get theme`, `python3 <skill-dir>/config.py get font`, and `python3 <skill-dir>/config.py get hud` first. When any of them prints `unset`, read `<skill-dir>/references/setup.md` and follow it to ask and save, then continue the original work.

Called with `setup`, read `<skill-dir>/references/setup.md` and follow it.

## Gather the facts

Build the list from this session's own record: the user's requests, tool results, files changed, commands run, test and build output, decisions the user made. Nothing else.

- An item is `done` only when a tool result in this session shows it done (a passing test, a written file, a merged PR). Work that was attempted but not verified is `now` or `blocked`, never `done`.
- If the context was compacted, use the summary and say so in `footer`.
- Group small steps into items a non-developer understands. Five to nine items in total is the target; one tool call is never an item.
- Collect the URL of every source you touch, not just its name: Jira issues and comments, PRs, commits, GitHub Actions runs (the `url` field of tool results, `gh run view --json url`), deploys, Slack thread permalinks, Notion and Confluence pages, Datadog dashboards, logs and traces, and web pages.

## Write the data

Write `/tmp/deadhd-<task-slug>.json`. `<skill-dir>/example.json` is a complete example; copy its shape.

| Field | Content |
|---|---|
| `key`, `keyHref` | Ticket key and its Jira link, when the task has one. Register the key in `links` as well, so every mention in the text is linked |
| `title` | The task as a formal noun phrase, e.g. `결제 웹훅 재시도 큐 도입과 스테이징 검증`. Not the user's request quoted |
| `goal` | One or two sentences under the title: why this task exists and what changes when it is done. Always fill it |
| `doneWhen` | The completion condition in one sentence, e.g. `결제 웹훅 재시도 큐가 staging 에 배포되고 실호출 검증을 통과한다.` |
| `lang` | `en` when the user writes in English, `ko` (or omitted) for Korean. The page's own labels follow it; write all other text in the same language |
| `updated` | Current time with timezone, e.g. `2026-09-30 14:30 KST` |
| `meta` | Identifiers shown as monospace chips: program id, target environment, branch. Each entry is a string, or `{"text": ..., "href": ...}` when the chip itself opens a link |
| `links` | Identifiers that appear in the text and have a URL: `{"SHOP-130": "https://...", "shop-api#4120": "https://..."}`. Every occurrence in the text below becomes a link, and a bare `http(s)://` URL is linked on its own |
| `lanes` | Lane names in order, e.g. `["server", "web"]`; an entry may also be `{"id": "srv", "label": "server"}`. This is the flow picture's lanes, not `board.lanes`, which holds subtask workers. Only when work runs on more than one track (repositories, a parallel branch). Omit for a single line |
| `items` | One per step, in flow order. Fields below |
| `board` | Subtask lanes, when four or more work units run in parallel. Fields in the `board` section below |
| `edges` | Only the connections the lane does not already draw: steps next to each other in one lane are joined automatically, so list a branch, a merge, or a cross-lane dependency here |
| `changes` | A plan change and its reason, when one happened |

Each item:

- `id`, `label` (short, for the flow picture), `sub` (one to three words under the node), `state`: `done`, `now` (exactly one while work is running), `side` (running in parallel), `left`, `blocked` (failed or waiting on the user).
- `lane`: the lane this step sits in — the index in `lanes`, or a lane's `id` or name; a name is matched against `id` first, then against the lane's name, and the first match wins; defaults to `0`. `col`: its column inside the lane; leave it out to take the next free column after the previous step in that lane.
- `title` and `body`: the card. `body` is one or two sentences: what and why for `now`, what happened for `done`, what stopped it for `blocked`.
- `ask`: only on a `blocked` item, the one thing the user has to do to unblock it, as one sentence addressed to them, e.g. `SHOP-209 에서 부분 환불 때 쿠폰을 복원할지 정해 주세요`. The band's second row and the blocked card show it apart from `body`. Leave it out when the step waits on nothing the user can do.
- `evidence`: file paths, PR, commit, test counts, Jira comments, each with an `icon` and an `href` when the identifier has a URL.
- `startedAt`, `doneAt`: when the step actually started and finished, ISO 8601 with a timezone offset, e.g. `2026-10-02T22:35:00+09:00`. Use a real time only: the output of `date -Iseconds` taken when you start or finish the step, or a timestamp that appeared in this session's tool results. Never invent one; leave the field out when you do not know.
- `estimate`: your estimate in minutes. On the `now` item it is the minutes left from now; on a `left` or `side` item it is how long that step will take. Leave it out when you have no basis for the number.
- `render.py` records each step's first estimate against its real duration (`startedAt` to `doneAt`) in `~/.config/deadhd/history.jsonl` and, once three or more steps are recorded, shows a calibrated completion time next to the raw one. Keep `estimate`, `startedAt`, and `doneAt` honest; never backfill them.
- Draw numbers instead of writing them. A pass count goes in `stats` as `ring`; a single large number goes in `stats` as `number`; an A-versus-B measurement or a risk ratio goes in `compare`. A sequence of sub-steps inside the current item goes in `substeps`; a sub-step with a URL carries its own `href`.

`render.py` computes the completion estimate from these fields and writes it into the page. Do not write a total or an end time into the data yourself. The line appears only when no item is `blocked` and every `now` and `left` item has an `estimate`; one missing estimate hides it.

### `board`

When four or more work units run in parallel, use `board`; read `<skill-dir>/references/board.md` and follow it for its fields.

Link rules:

- An identifier with a URL is always shown as a link. Card evidence carries `href`; an identifier inside a sentence (a Jira key, a PR number) goes in `links`, so it is linked wherever it appears; a meta chip that links somewhere is `{"text": ..., "href": ...}`.
- A source you read while investigating — Slack thread, Notion or Confluence page, dashboard, web page — gets its own `evidence` entry on that item, with an `icon` and `href`.
- Never invent a URL. Use one that appeared in this session's tool results, or one that follows deterministically from a confirmed base (Jira base plus key, GitHub repository plus PR number or commit). When the URL is not knowable, leave the identifier as plain text.

The `icon` on an evidence entry or a `stats` `number`:

| `icon` | Use for |
|---|---|
| `pr` | Pull request |
| `commit` | Commit |
| `test` | Test run or result |
| `ticket` | Jira issue or comment |
| `file` | File |
| `deploy` | Deployment |
| `check` | Verification or check result |
| `run` | CI run (GitHub Actions run) |
| `chat` | Messenger thread (Slack) |
| `doc` | Document page (Notion, Confluence) |
| `link` | Any other link |
| `chart` | Monitoring dashboard, logs, traces (Datadog) |

Writing rules for all text in the data:

- If `${XDG_CONFIG_HOME:-~/.config}/deadhd/writing-rules.md` exists, follow it. It is an optional user file (it may be a symlink to the user's own writing standard).
- Otherwise: titles, labels, `sub`, and captions are noun phrases, never questions or sentences. Use the field's established terms (측정한다, 검증한다) instead of casual paraphrases. Do not personify systems, documents, or metrics. Write in the user's language.

## Render

```bash
python3 <skill-dir>/render.py [--view html|band|statusline] [--page] [--theme system|light|dark|neon|synthwave|matrix|nord|paper|sakura|ink] [--font <preset>] /tmp/deadhd-<slug>.json /tmp/deadhd-<slug>.html
```

It applies the saved theme and font preset, and the `--theme` and `--font` values instead when this run has one. The view is the first of these that exists: `--view`, the view the state file records for this session, the saved one, and `html`. It validates the data and exits 1 with the reason when a field is wrong; fix the JSON and rerun. Reuse the same two paths for the rest of this conversation. Never edit the HTML by hand.

The `view` is written into the session's state file, and the mod draws whichever view it reads there. Under a `band` or `statusline` view render.py still refreshes the state summary and the hub, but leaves the HTML file alone until the page is opened once: `--page` writes it and records that, and every render after that writes it too. So run it after every change to the JSON exactly as before; only the HTML file is deferred. A render without `--view` keeps this session's view, so the flags the hooks and the mod pass never move a `band` or `statusline` session back to the default.

## Deliver

On the first render only:

- Under a `band` or `statusline` view with none of `-h`, `-o`, `-c`, or `--view html`, skip this section entirely and reply as Where it shows says.

- Under a `band` or `statusline` view with any of `-h`, `-o`, or `-c`, the first render must have carried `--page` so the HTML file exists; `open.sh` exits 2 on a file that is not there, and `share.sh` and the `Artifact` tool need one too. The flag only writes the file — the view stays `band` or `statusline` and the band keeps updating from the same renders.

- For `-o`, run `bash <skill-dir>/share.sh /tmp/deadhd-<slug>.html`. On `shared: <url>`, give the user the URL. On `fallback: browser`, run the `-h` step instead and say that publishing failed, with the `skip:` reason.

- Otherwise, for `-h` run `bash <skill-dir>/open.sh [--mode <mode>] /tmp/deadhd-<slug>.html`, where `<mode>` is the `--open` value when one was given. It takes the mode from `--mode`, else the saved default, else `auto`, and prints `opened: orca-tab|browser|desktop|none <path>`. On `none`, give the user the path to open. On `desktop`, write that absolute path as its own line in the reply and tell the user to press it in the Claude desktop app to open the page. `open.sh` starts a localhost static server (`serve.py`, port `DEADHD_PORT` or 47320) when it is not running and opens the page over http, so links between pages work inside Orca and other in-app browsers.
- For `-c`, publish the HTML file with the `Artifact` tool.

## Keep it updated

After the first render, update the JSON and rerun `render.py` whenever an item changes state (finished, started, blocked) until the task ends or the user says `/deadhd off` (see Parse the arguments: it runs `state.py --off`).

The plugin's hooks (`hooks/hooks.json`) keep a status band on the page fresh on their own: waiting for permission, waiting for input, last tool, background tasks, compactions. While the session waits for input the band also shows the end of your last response — its last line, stripped of markdown, up to 120 characters — and so does the hub tile, so put a question you need answered on the last line of the response and the user sees it there. `render.py` links the page to this session through `CLAUDE_CODE_SESSION_ID`; nothing to do for that. After a context compaction the session-start hook tells you the data file path; keep using it. A session turned off with `/deadhd off` gets no such note. A skill-folder or Orca install loads that same `hooks/hooks.json` through the folder's own manifest; only a session with no hooks at all — a host that does not load the plugin, such as Codex — shows no status band and is listed as `untracked` or `done`.

Under a `band` or `statusline` view the mod draws its own session state (a running turn, a wait, the last tool, compactions) from the session's events, and the checklist fields from the same state file, so the renders above are what keeps the checklist fresh. With `hud off` it draws the checklist fields alone. Nothing else to do for it.

Every render also rewrites the hub page (`/tmp/deadhd-hub.html`), which lists this machine's sessions; the page's `허브 ↗` button opens it. Each tile names the repository or worktree (and branch) the session runs in, read from the session's `cwd`.

- The open tab fetches the page again every 15 seconds and redraws only the data, so what the user expanded, scrolled, or focused stays put; a `file://` page reloads instead, and a shared copy (`-o`, `-c`) does not refresh. The completion effect plays on items that became `done`. If the fetch keeps failing, the page says so at the bottom instead of going quiet.
- When a step changes state, record its `startedAt` and `doneAt` and refresh the remaining `estimate` values. A lane in `board.lanes` is updated the same way: its `state`, `lastSignal`, and a new `log` line.
- The page, the hub and the band each show how long ago the data file was last written, and a session still working that has not written it for over 30 minutes is marked `stale` — so write the JSON on every step change rather than at the start only.
- Do not run the delivery or open script again.
- For a Claude artifact or an Orca artifact, republish only at the end of the task or when the user asks, not at every change. Republish an Orca artifact with `bash <skill-dir>/share.sh --update /tmp/deadhd-<slug>.html`.
- On the first render and when the task ends, reread the data once against the writing rules (the writing-rules file's procedure when it has one). Skip this on intermediate updates.
- An update is part of the work, not a report: do not mention it in chat.

## Reply

First render: where the page is, plus any fallback line — or, under a `band` or `statusline` view, the one line Where it shows describes. That one line must also carry the way to the page when the band does not show: say that the band (or the status line) is not drawn in some places and that `/deadhd -h` opens the page there. Write it in the session's language and tone — for Korean, the meaning of 「밴드(상태줄)가 보이지 않으면 `/deadhd -h` 로 페이지를 열 수 있어요」 — never leave it out. Do not paste the HTML or the JSON.
