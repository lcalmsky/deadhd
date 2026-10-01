---
name: deadhd
description: Show a live checklist page of what this session has done, is doing now, and has left, opened beside the terminal and kept updated while the task runs. Use when the user types /deadhd or $deadhd, or asks "지금 뭐 하고 있어", "진행 상황 띄워줘", "체크리스트로 보여줘".
argument-hint: "[setup] [-h|-o|-c] [--open auto|orca|browser|desktop] [--theme system|light|dark] [off]"
---

# deadhd

`$ARGUMENTS`

A status page for the task running in this session. The reader glanced away for an hour and wants to know, in one look, what happened. The design is fixed in `template.html`; you write only the data.

`<skill-dir>` below is the directory that contains this SKILL.md. Everything the skill needs is in it; files outside it are optional and used only when present.

## Parse the arguments

- `off`: stop updating the page (see Keep it updated). Reply in one line and stop.
- `-h` (default): open the page in a browser tab beside the terminal.
- `-o`: publish as an Orca artifact. Needs the eli5o delivery script (see Deliver); without it, fall back to `-h` and say so.
- `-c`: publish as a Claude artifact with the `Artifact` tool. Without that tool, fall back to `-h` and say so.
- `setup`: ask for the default open location and save it (see Setup). After saving, reply in one line and stop.
- `--open <mode>`: use this mode for this run only, instead of the saved default. Pass it to open.sh as `--mode <mode>`.
- `--theme <theme>`: render with this theme for this run only, instead of the saved one. Pass it to render.py as `--theme <theme>`.

## Setup

Ask once, then save the answers as the defaults. There are two questions: the default open location and the default theme. Ask with the `AskUserQuestion` tool when it is available, otherwise ask in plain text; when the tool is available, put both questions in a single call.

Open location, four choices:

- `auto` (recommended): an Orca tab when the session runs inside Orca, otherwise the system browser.
- `orca`: an Orca tab.
- `browser`: the system browser.
- `desktop`: print the path in chat; press it in the Claude desktop app to open the page in the in-app browser.

Theme, three choices:

- `system` (recommended): follow the operating system's light and dark setting.
- `light`: always the light theme.
- `dark`: always the dark theme.

Save the answers with `python3 <skill-dir>/config.py set open <value>` and `python3 <skill-dir>/config.py set theme <value>`. Calling the skill with `setup` asks both questions again.

- First run: on an ordinary run that is not `-c`, `-o`, `--open`, `off`, or `setup`, run `python3 <skill-dir>/config.py get open` and `python3 <skill-dir>/config.py get theme` first. Ask only for the ones that print `unset`, save them, then continue the original work.

## Gather the facts

Build the list from this session's own record: the user's requests, tool results, files changed, commands run, test and build output, decisions the user made. Nothing else.

- An item is `done` only when a tool result in this session shows it done (a passing test, a written file, a merged PR). Work that was attempted but not verified is `now` or `blocked`, never `done`.
- If the context was compacted, use the summary and say so in `footer`.
- Group small steps into items a non-developer understands. Five to nine items in total is the target; one tool call is never an item.

## Write the data

Write `/tmp/deadhd-<task-slug>.json`. `<skill-dir>/example.json` is a complete example; copy its shape.

| Field | Content |
|---|---|
| `key`, `keyHref` | Ticket key and its Jira link, when the task has one |
| `title` | The task as a formal noun phrase, e.g. `결제 웹훅 재시도 큐 도입과 스테이징 검증`. Not the user's request quoted |
| `goal` | One or two sentences under the title: why this task exists and what changes when it is done. Always fill it |
| `doneWhen` | The completion condition in one sentence, e.g. `결제 웹훅 재시도 큐가 staging 에 배포되고 실호출 검증을 통과한다.` |
| `updated` | Current time with timezone, e.g. `2026-09-30 14:30 KST` |
| `meta` | Identifiers shown as monospace chips: program id, target environment, branch |
| `lanes` | Only when work runs on more than one track (repositories, a parallel branch). Omit for a single line |
| `items` | One per step, in flow order. Fields below |
| `edges` | Only when the flow is not a straight line per lane: a branch, a merge, a cross-repository dependency |
| `changes` | A plan change and its reason, when one happened |

Each item:

- `id`, `label` (short, for the flow picture), `sub` (one to three words under the node), `state`: `done`, `now` (exactly one while work is running), `side` (running in parallel), `left`, `blocked` (failed or waiting on the user).
- `title` and `body`: the card. `body` is one or two sentences: what and why for `now`, what happened for `done`, what is needed for `blocked`.
- `evidence`: file paths, PR, commit, test counts, Jira comments, each with an `icon` and `href` when a link exists. Jira keys and PR numbers always get `href`.
- Draw numbers instead of writing them. A pass count goes in `stats` as `ring`; a single large number goes in `stats` as `number`; an A-versus-B measurement or a risk ratio goes in `compare`. A sequence of sub-steps inside the current item goes in `substeps`.

Writing rules for all text in the data:

- If `~/.agent-lanes/write-like-me/SKILL.md` exists, follow its Rules.
- Otherwise: titles, labels, `sub`, and captions are noun phrases, never questions or sentences. Use the field's established terms (측정한다, 검증한다) instead of casual paraphrases. Do not personify systems, documents, or metrics. Write in the user's language.

## Render

```bash
python3 <skill-dir>/render.py [--theme system|light|dark] /tmp/deadhd-<slug>.json /tmp/deadhd-<slug>.html
```

It applies the saved theme on its own, and the `--theme` value instead when this run has one. It validates the data and exits 1 with the reason when a field is wrong; fix the JSON and rerun. Reuse the same two paths for the rest of this conversation. Never edit the HTML by hand.

## Deliver

On the first render only:

- For `-o`, if `~/.agent-lanes/eli5o/scripts/deliver.sh` exists, run it and handle its output and fallbacks exactly as `~/.agent-lanes/eli5o/SKILL.md` does, including the `-c` / `fallback: claude-artifact` step:

  ```bash
  ~/.agent-lanes/eli5o/scripts/deliver.sh -o --label "deadhd <task, a few words>" /tmp/deadhd-<slug>.html
  ```

- Otherwise, for `-h` run `bash <skill-dir>/open.sh [--mode <mode>] /tmp/deadhd-<slug>.html`, where `<mode>` is the `--open` value when one was given. It takes the mode from `--mode`, else the saved default, else `auto`, and prints `opened: orca-tab|browser|desktop|none <path>`. On `none`, give the user the path to open. On `desktop`, write that absolute path as its own line in the reply and tell the user to press it in the Claude desktop app to open the page.
- For `-c`, publish the HTML file with the `Artifact` tool.

## Keep it updated

After the first render, update the JSON and rerun `render.py` whenever an item changes state (finished, started, blocked) until the task ends or the user says `/deadhd off`.

- The open tab reloads itself every 15 seconds and plays the completion effect on items that became `done`.
- Do not run the delivery or open script again.
- For a Claude artifact or an Orca artifact, republish only at the end of the task or when the user asks, not at every change.
- On the first render and when the task ends, reread the data once against the writing rules (the write-like-me Procedure when that file exists). Skip this on intermediate updates.
- An update is part of the work, not a report: do not mention it in chat.

## Reply

First render: where the page is, plus any fallback line. Do not paste the HTML or the JSON.
