---
name: deadhd
description: Show a live checklist page of what this session has done, is doing now, and has left, opened beside the terminal and kept updated while the task runs. Use when the user types /deadhd or $deadhd, or asks "지금 뭐 하고 있어", "진행 상황 띄워줘", "체크리스트로 보여줘", or asks "what are you doing now", "show progress", "show me a checklist".
argument-hint: "[setup] [hub] [-h|-o|-c] [--open auto|orca|browser|desktop] [--theme system|light|dark|neon|synthwave|matrix|nord|paper|sakura|ink] [--font default|pretendard|noto-sans|plex-sans|gothic-a1|nanum-gothic|noto-serif|nanum-myeongjo|hahmlet|gowun-batang|do-hyeon|black-han-sans] [off]"
---

# deadhd

`$ARGUMENTS`

A status page for the task running in this session. The reader glanced away for an hour and wants to know, in one look, what happened. The design is fixed in `template.html`; you write only the data.

`<skill-dir>` below is the directory that contains this SKILL.md. Everything the skill needs is in it; files outside it are optional and used only when present.

## Parse the arguments

- `off`: stop updating the page (see Keep it updated). Reply in one line and stop.
- `hub`: write the hub page with `python3 <skill-dir>/hub.py` and open it with `bash <skill-dir>/open.sh [--mode <mode>] <hub path printed by hub.py>`. Reply with where it opened and stop. Pass `--theme` and `--font` to hub.py as well when this run has them. The hub opens through `open.sh` like a session page, so it uses the same localhost server.
- `-h` (default): open the page in a browser tab beside the terminal.
- `-o`: publish as an Orca artifact (a shareable web page) with the `orca` CLI. Without it, or when publishing fails, fall back to `-h` and say so.
- `-c`: publish as a Claude artifact with the `Artifact` tool. Without that tool, fall back to `-h` and say so.
- `setup`: ask for the default open location and save it (see Setup). After saving, reply in one line and stop.
- `--open <mode>`: use this mode for this run only, instead of the saved default. Pass it to open.sh as `--mode <mode>`.
- `--theme <theme>`: render with this theme for this run only, instead of the saved one. One of `system`, `light`, `dark`, `neon`, `synthwave`, `matrix`, `nord`, `paper`, `sakura`, `ink`. Pass it to render.py as `--theme <theme>`.
- `--font <preset>`: render with this heading font preset for this run only, instead of the saved one. One of `default`, `pretendard`, `noto-sans`, `plex-sans`, `gothic-a1`, `nanum-gothic`, `noto-serif`, `nanum-myeongjo`, `hahmlet`, `gowun-batang`, `do-hyeon`, `black-han-sans`. Pass it to render.py as `--font <preset>`.

## Setup

Ask once, then save the answers as the defaults. There are three questions: the default open location, the default theme, and the default heading font. Ask with the `AskUserQuestion` tool when it is available, otherwise ask in plain text; when the tool is available, put all three questions in a single call.

Open location, four choices:

- `auto` (recommended): an Orca tab when the session runs inside Orca, otherwise the system browser.
- `orca`: an Orca tab.
- `browser`: the system browser.
- `desktop`: print the path in chat; press it in the Claude desktop app to open the page in the in-app browser.

Theme, four choices:

- `system` (recommended): follow the operating system's light and dark setting.
- `dark`: always the dark theme.
- `light`: always the light theme.
- `more themes`: show the extra themes below and take the answer by name.

`AskUserQuestion` allows at most four choices, which is why `more themes` and `more fonts` are among them. When the user picks `more themes`, list these in plain text, one line each with its description, and take the theme name as the answer:

- `neon` — cyberpunk neon: near-black violet with cyan, magenta, and fluorescent yellow.
- `synthwave` — 80s sunset: deep violet under a pink-and-orange gradient.
- `matrix` — green terminal: monochrome green on black, every glyph monospaced.
- `nord` — calm arctic: muted northern palette, easy on the eyes over a long session.
- `paper` — warm paper, light: cream stock with a serif heading, reads like a document.
- `sakura` — cherry blossom, light: pink light theme with a handwritten heading.
- `ink` — monochrome: pure white on pure black; states are told apart by fill, outline, and hatching instead of color.

Heading font, four choices:

- `default` (recommended): the heading font the theme already uses.
- `pretendard`: clean sans, tight.
- `do-hyeon`: bold display sans, tight.
- `more fonts`: show the rest by name.

When the user picks `more fonts`, list these in plain text, one line each with its description, and take the font name as the answer:

- `noto-sans` — Noto Sans KR 900
- `plex-sans` — IBM Plex Sans KR 700
- `gothic-a1` — Gothic A1 900
- `nanum-gothic` — Nanum Gothic 800
- `noto-serif` — Noto Serif KR 900
- `nanum-myeongjo` — Nanum Myeongjo 800
- `hahmlet` — Hahmlet 900 serif
- `gowun-batang` — Gowun Batang 700 serif
- `black-han-sans` — Black Han Sans poster

Save the answers with `python3 <skill-dir>/config.py set open <value>`, `python3 <skill-dir>/config.py set theme <value>`, and `python3 <skill-dir>/config.py set font <value>`. Calling the skill with `setup` asks all three questions again.

- First run: on an ordinary run that is not `-c`, `-o`, `--open`, `off`, or `setup`, run `python3 <skill-dir>/config.py get open`, `python3 <skill-dir>/config.py get theme`, and `python3 <skill-dir>/config.py get font` first. Ask only for the ones that print `unset`, save them, then continue the original work.

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
| `lanes` | Only when work runs on more than one track (repositories, a parallel branch). Omit for a single line |
| `items` | One per step, in flow order. Fields below |
| `board` | Subtask lanes, when four or more work units run in parallel. Fields in the `board` section below |
| `edges` | Only the connections the lane does not already draw: steps next to each other in one lane are joined automatically, so list a branch, a merge, or a cross-lane dependency here |
| `changes` | A plan change and its reason, when one happened |

Each item:

- `id`, `label` (short, for the flow picture), `sub` (one to three words under the node), `state`: `done`, `now` (exactly one while work is running), `side` (running in parallel), `left`, `blocked` (failed or waiting on the user).
- `title` and `body`: the card. `body` is one or two sentences: what and why for `now`, what happened for `done`, what is needed for `blocked`.
- `evidence`: file paths, PR, commit, test counts, Jira comments, each with an `icon` and an `href` when the identifier has a URL.
- `startedAt`, `doneAt`: when the step actually started and finished, ISO 8601 with a timezone offset, e.g. `2026-10-02T22:35:00+09:00`. Use a real time only: the output of `date -Iseconds` taken when you start or finish the step, or a timestamp that appeared in this session's tool results. Never invent one; leave the field out when you do not know.
- `estimate`: your estimate in minutes. On the `now` item it is the minutes left from now; on a `left` or `side` item it is how long that step will take. Leave it out when you have no basis for the number.
- `render.py` records each step's first estimate against its real duration (`startedAt` to `doneAt`) in `~/.config/deadhd/history.jsonl` and, once three or more steps are recorded, shows a calibrated completion time next to the raw one. Keep `estimate`, `startedAt`, and `doneAt` honest; never backfill them.
- Draw numbers instead of writing them. A pass count goes in `stats` as `ring`; a single large number goes in `stats` as `number`; an A-versus-B measurement or a risk ratio goes in `compare`. A sequence of sub-steps inside the current item goes in `substeps`; a sub-step with a URL carries its own `href`.

`render.py` computes the completion estimate from these fields and writes it into the page. Do not write a total or an end time into the data yourself. The line appears only when no item is `blocked` and every `now` and `left` item has an `estimate`; one missing estimate hides it.

### `board`

Use `board` when four or more work units run at once: an epic's subtasks, several delegated workers (a DeepSeek lane, a subagent, this leader session). Keep `items` short as the program-level steps — planning, subtask progress, audit — and put the subtasks in `board.lanes`. A page without `board` draws only the flow, exactly as before.

- `stages`: the stage names in order, e.g. `["분석", "설계", "구현", "검증", "배포", "회귀", "보고"]`. Optional. Without it every lane shows its `stage` string in one column. Values must not repeat.
- `lanes`: one entry per work unit, in the order they should read. At least one.
  - `id`: the ticket key or work-unit id, unique in the board. `label`: a short noun phrase.
  - `state`: `done` (finished), `now` (a worker is on it), `waiting` (held by `dependsOn`), `left` (not started), `blocked` (failed or waiting on the user). Any number of lanes may be `now`.
  - `stage`: the stage it is in now. When `stages` is present it must be one of them; leave it out for a lane that has not started.
  - `worker`: who runs it, e.g. `deepseek:impl-205`, `subagent:sonnet`, `leader`. A lane without it is grouped under `Unassigned`.
  - `dependsOn`: the ids of the lanes this one waits for. The row shows them as `↳ … waiting`.
  - `startedAt`, `doneAt`: same rule as on an item — a real time only, never invented.
  - `lastSignal`: the last time a tool result in this session showed that worker's output: a result file update, a completion notice, a log line. Never invent it, and refresh it every time you look. The page prints it as `N ago` and turns the lane `stalled` once the silence passes `stallAfter`.
  - `stallAfter`: minutes of silence before a `now` lane counts as stalled. Defaults to 15. The page decides this in the browser, so a lane you stopped updating still shows up as stalled.
  - `estimate`: minutes left, as on a `now` item.
  - `note`: a few words under the current stage dot, e.g. `code-reviewer`.
  - `body`: the text the row expands to, one or two sentences.
  - `evidence`: chips, as on an item. `log`: the lane's own transitions, `{"at": …, "text": …}` each; the page shows the eight newest of all lanes together.

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
python3 <skill-dir>/render.py [--theme system|light|dark|neon|synthwave|matrix|nord|paper|sakura|ink] [--font <preset>] /tmp/deadhd-<slug>.json /tmp/deadhd-<slug>.html
```

It applies the saved theme and the saved font preset, and the `--theme` and `--font` values instead when this run has one. It validates the data and exits 1 with the reason when a field is wrong; fix the JSON and rerun. Reuse the same two paths for the rest of this conversation. Never edit the HTML by hand.

## Deliver

On the first render only:

- For `-o`, run `bash <skill-dir>/share.sh /tmp/deadhd-<slug>.html`. On `shared: <url>`, give the user the URL. On `fallback: browser`, run the `-h` step instead and say that publishing failed, with the `skip:` reason.

- Otherwise, for `-h` run `bash <skill-dir>/open.sh [--mode <mode>] /tmp/deadhd-<slug>.html`, where `<mode>` is the `--open` value when one was given. It takes the mode from `--mode`, else the saved default, else `auto`, and prints `opened: orca-tab|browser|desktop|none <path>`. On `none`, give the user the path to open. On `desktop`, write that absolute path as its own line in the reply and tell the user to press it in the Claude desktop app to open the page. `open.sh` starts a localhost static server (`serve.py`, port `DEADHD_PORT` or 47320) when it is not running and opens the page over http, so links between pages work inside Orca and other in-app browsers.
- For `-c`, publish the HTML file with the `Artifact` tool.

## Keep it updated

After the first render, update the JSON and rerun `render.py` whenever an item changes state (finished, started, blocked) until the task ends or the user says `/deadhd off`.

The plugin's hooks (`hooks/hooks.json`) keep a status band on the page fresh on their own: waiting for permission, waiting for input, last tool, background tasks, compactions. `render.py` links the page to this session through `CLAUDE_CODE_SESSION_ID`; nothing to do for that. After a context compaction the session-start hook tells you the data file path; keep using it. Without the plugin's hooks (skill-folder or Orca installs) no status band is shown and the hub lists the session as `untracked` or `done`; the README shows how to add the hooks to `~/.claude/settings.json`.

Every render also rewrites the hub page (`/tmp/deadhd-hub.html`), which lists this machine's sessions; the page's `허브 ↗` button opens it.

- The open tab reloads itself every 15 seconds and plays the completion effect on items that became `done`.
- When a step changes state, record its `startedAt` and `doneAt` and refresh the remaining `estimate` values. A lane in `board.lanes` is updated the same way: its `state`, `lastSignal`, and a new `log` line.
- Do not run the delivery or open script again.
- For a Claude artifact or an Orca artifact, republish only at the end of the task or when the user asks, not at every change. Republish an Orca artifact with `bash <skill-dir>/share.sh --update /tmp/deadhd-<slug>.html`.
- On the first render and when the task ends, reread the data once against the writing rules (the writing-rules file's procedure when it has one). Skip this on intermediate updates.
- An update is part of the work, not a report: do not mention it in chat.

## Reply

First render: where the page is, plus any fallback line. Do not paste the HTML or the JSON.
