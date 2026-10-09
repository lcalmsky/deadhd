<h1 align="center"><img src="docs/logo.png" alt="deadhd" width="420"></h1>

<p align="center"><a href="README.md">한국어</a> · <b>English</b></p>

<p align="center"><b>dead + ADHD</b><br>A Claude Code progress skill for beating ADHD</p>

<p align="center"><i>A Claude Code skill that shows a live checklist page of what each session has done, is doing now, and has left.</i></p>

When you run several Claude Code sessions at once, it is easy to lose track of how far a session got while you were looking at another one. deadhd opens the session's progress as a checklist page, so you can see it at a glance without scrolling back through the terminal log. From 1.8.0 the hooks track session state, and from 1.9.0 the hub shows every session side by side.

![A progress page in the in-app browser beside the terminal, switching workspaces](docs/hero.webp)

## Use cases

Built for using Claude Code in a terminal app with an in-app browser, such as [Orca](https://onorca.dev), and keeping the progress page open in a panel beside the terminal. Typing `/deadhd` in the working session opens a page that lays out completed, in-progress, and remaining steps as a flow diagram and cards, and the page keeps updating while the work runs. When you leave a long task running and come back, you can check progress from one page instead of scrolling back through the terminal log.

Inside Orca it opens by default (`auto`) in a tab beside the terminal. Outside Orca you can open it in the system browser or the Claude desktop app's in-app browser. Choose the open location in [Settings](#settings).

When work runs long, a status band appears at the top of the page telling you what the session is waiting for, and the plugin hooks keep it fresh. With several sessions open, the hub page gathers this machine's sessions onto one page.

## At a glance

- **Progress page** — completed, in-progress, and remaining steps as a flow diagram and cards, each with its supporting file paths, PRs, commits, and test pass counts.
- **Status band** — session state such as waiting for permission, waiting for input, the last tool, and compactions, shown as a band at the top of the page. The plugin hooks keep it fresh.
- **Calibrated ETA** — each finished step's first estimate and actual duration accumulate in a history, and from three records on a calibrated completion time is shown alongside.
- **Hub** — this machine's sessions gathered on one page and sorted by state.
- **Ten themes and twelve font presets** — pick the theme and the heading font you want.
- **Four view modes** — switch the same progress between Original, Strip, Timeline, and Tiles.
- **Three display views** — in Claude Code you can also watch the same progress as a band above the prompt or a line under it, without opening a page.

![A session page with a status band](docs/live.en.png)

![Hub](docs/hub.en.png)

## Themes

Nine themes in a 3×3 gallery. You can see a multi-lane flow, blocked work, a completion estimate that crosses midnight, and a state where every step is done. The monochrome `ink` theme — pure white on pure black — has been added, and `system` is left out of the gallery because it follows the operating system's setting. Pick a default theme with `/deadhd setup`, or change it for one run with `/deadhd --theme <theme>`.

![deadhd theme gallery](docs/themes.en.png)

## View modes

The buttons at the top left of the page switch the same progress between four views. Where the page is narrow, such as the Claude artifact panel or a split Orca tab, the compact views are easier to read at a glance.

| View | Layout |
|---|---|
| Original | The default page with the flow diagram and a card for every step |
| Strip | Shrinks the step flow to one row of dots and expands only the card for the step in progress. The other steps are folded into done, parallel, and left groups |
| Timeline | Stacks the steps one per row, each with its finish time or estimate. The step in progress is shown as a card |
| Tiles | Leads with numbers (steps done, time left on the current step, expected completion) and shows each step's state as a segmented bar |

Picking a compact view shows the `Auto`, `Landscape`, and `Portrait` buttons. `Auto` uses the landscape layout when the tab is wider than 5:4 and at least 760px wide, and the portrait layout otherwise, and it re-lays out as soon as you resize the tab. The chosen view and layout survive the 15-second auto-refresh and work in every theme and in the English UI.

The browser draws a view from the data already in the page when you press its button. The model still writes the same data, so the views add no token cost.

![deadhd view modes](docs/views.en.png)

## Display views

The same progress can be shown three ways. This is a separate setting from the page's view modes, and in Claude Code it is drawn in the terminal without opening a page.

| Display | Where | Layout |
|---|---|---|
| `band` | One line above the prompt | Steps done, a progress bar, the step in progress with its elapsed time, and the blocked and left counts. A second row appears when a step is stuck or the session waits, and no browser tab is opened — the lightest of the three (default) |
| `statusline` | One line under the prompt | More fields than the band: the ticket key and title, the next step, the estimate, the last update, background tasks, and compactions, all on one line |
| `html` | The browser page | The progress page as before |

Pick one in `/deadhd setup`, or change it for one run with `/deadhd --view <value>`. The value recorded in the session's state file beats the saved setting, so one run with `--view band` keeps that session on the band.

The band and the status line are drawn by the deadhd plugin's mod (`skills/deadhd/hooks/register.tsx`), which reads the same state file the skill writes. They are **Claude Code only**; outside Claude Code (Codex `$deadhd`, say) the skill does not ask and works as `html`. `/deadhd-band` folds or opens the band, `/deadhd-statusline` the status line, and a command that does not match the current view answers in one line with how to switch. The page opens with `/deadhd-open` or the band's `Open` button.

Under `band` and `statusline` the page file is not written straight away. The state summary and the hub are rewritten on every update; the page is written when it is first opened (`/deadhd-open`, the `Open` button) and from then on with every update. A session with no page yet shows its display name (`band`/`status line`) in the hub instead of a link.

## Lane board

When four or more work units run in parallel — an epic's subtasks, for instance — filling the data's `board` adds a task × stage table below the page. Each lane shows its stage, worker, last signal, time left, and ticket transitions on one row, with a summary of how many are done, running, stalled, blocked, waiting, or left. The browser measures how long a lane has been quiet past its `stallAfter` (15 minutes by default), so a lane you stop updating still shows up as stalled in the attention band. A harness session that splits work across a DeepSeek lane, a subagent, and the leader session uses the same format as a plain session that hands work to a default subagent. A session without `board` still draws only the flow, exactly as before.

![Lane board](docs/board.en.png)

## How it works

- The done mark is attached only to steps confirmed by the session's own run results. Only steps with a result — a passing test, a written file, a merged PR — are classified as `done`; steps that were attempted but not verified are shown as `now` or `blocked`.
- Each step shows its supporting evidence: file paths, PRs, commits, test pass counts.
- The page design is fixed in `template.html`, and the model writes only the JSON data. `render.py` validates the data and generates the HTML.
- The theme and font CSS lives in `themes.css`, so the session page and the hub share the same file.
- When the user talks in English, the page's fixed labels (`done`, `In progress`, `Remaining`, and so on) are shown in English too. This is set by the data's `lang` field; without it the page is Korean.
- When per-step start and finish times and remaining-time estimates are present, the expected completion time appears under the progress bar. It is anchored to the last time the data file was written, not to the render time, so a hook re-render that leaves the data alone does not push the estimate back. An estimate that has already passed gets ` (overdue)`. The `tomorrow` or date notation is decided from the time you are viewing the page, so it changes on its own after midnight or when you reopen the window.
- An open tab reloads every 15 seconds, and newly completed steps play a completion effect. The status band at the top of the page refreshes on the same cycle.
- The page is opened over a static server bound to 127.0.0.1 (`serve.py`), because an in-app browser such as Orca blocks `file://` navigation from inside a page. It starts on its own the first time you open a page and serves only `deadhd-*.html` from `/tmp`.
- The hub is built by reading this machine's session state files only.

## Waiting-for-you band and calibrated ETA

- Installed as a plugin, the hooks in `hooks/hooks.json` take session events (permission request, turn end, tool run, compaction, session end), write the state to `/tmp/deadhd-state/<session ID>.json`, and re-render the page. A band appears at the top: `Waiting for permission · 12m`, `Waiting for your input · 23m`, `Working · Last tool Bash 8s ago`, `No signal`, `Session ended`. The hooks keep the band fresh even when the model forgets to update the page.
- After a compaction, the session-start hook tells the model the data file path again.
- The skill folder and Orca installs do not carry the hooks. To use them, add the same hooks to `~/.claude/settings.json`, replacing `${CLAUDE_PLUGIN_ROOT}` with the absolute path of the skill folder. Without the hooks no status band appears on the page, and the hub lists the session as `No hooks` or `Done`.

```json
{
  "hooks": {
    "Notification": [{ "matcher": "permission_prompt|idle_prompt", "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/deadhd/state.py\"" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/deadhd/state.py\"" }] }],
    "PostToolUse": [{ "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/deadhd/state.py\"" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/deadhd/state.py\"" }] }],
    "SessionStart": [{ "matcher": "compact", "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/deadhd/state.py\"" }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/skills/deadhd/state.py\"" }] }]
  }
}
```

- Calibration: when a step finishes, the estimate first written for it and the actual duration accumulate in `~/.config/deadhd/history.jsonl`, and from three records on a calibrated completion time is shown next to the raw one. What is recorded is only the step id, the estimate, and the actual minutes.

## Hub

One page that gathers the sessions running on this machine. Open it with `/deadhd hub`, or with the `Hub ↗` button at the top right of a session page. A tile carries the status badge, the title and key, a per-step mini strip, `6/12 done`, what is running now, and the completion estimate.

- Sorted permission > no signal > input > working > no hooks > done > ended > past sessions, and within a state the session that has waited longest comes first.
- Pressing a tile moves to that session's page in the same tab, and the `Hub ↗` button on a session page returns to the hub in the same tab.
- Only sessions that write a state file (1.8.0 and later) are gathered. A session not updated for more than 24 hours folds into "Ended and past".
- Pages are served by a static server bound to 127.0.0.1 (`serve.py`, port 47320, changeable with `DEADHD_PORT`), because the Orca built-in browser blocks `file://` navigation from inside a page. The server serves only `deadhd-*.html` from `/tmp`, does not follow symbolic links, and checks the `Host` header so an outside site cannot read it. It starts on its own the first time a page opens and stays after the session ends. To stop it, run `python3 ~/.claude/skills/deadhd/serve.py --stop` (the same path inside the plugin cache when installed as a plugin).
- `render.py` rewrites the hub file whenever a session page renders and on every hook event (`/tmp/deadhd-hub.html`, changeable with `DEADHD_HUB`).

## Requirements

- [Claude Code](https://code.claude.com)
- `python3` (standard library only)
- Chrome (needed only to regenerate the example images)

The `band` and `statusline` displays are drawn only on Claude Code's plugin mod; elsewhere only `html` is available.

## Install

### Install as a plugin

Run these commands in Claude Code.

```
/plugin marketplace add lcalmsky/deadhd
/plugin install deadhd@deadhd
```

Installed as a plugin, the invocation name is `/deadhd:deadhd`, and this is the only install method that carries the hooks.

<a id="orca-install"></a>

### Install from Orca

If you use [Orca](https://onorca.dev), open the [share link](https://share.onorca.dev/skills/share/shr_a38de6123a1ae29e31f2092e4369fa72d126a7487c0eb746) and press `Open in Orca`. Orca lets you review the included files and choose where to install. After installing, the invocation name is `/deadhd`.

> An Orca share link is a frozen bundle of the files uploaded at publish time. The current link contains v1.10.1, and releases after that are not reflected. For the latest version, install via the plugin or the skill folder.

### Install as a skill folder

```bash
git clone https://github.com/lcalmsky/deadhd.git
cp -r deadhd/skills/deadhd ~/.claude/skills/
```

Installed this way, the invocation name is `/deadhd`. Because `skills/deadhd/.claude-plugin/` is copied along, the folder is auto-loaded as the `deadhd@skills-dir` plugin from the next session on, which is what draws the band and the status line. The mod comes without a plugin install; the command hooks that maintain the status band do not. A plugin install uses the same mod through the marketplace entry point.

## Update

| Install method | How to update |
|---|---|
| Plugin | Auto-update is off by default for third-party marketplaces. In `/plugin`, select deadhd and press **Update now**, or run `claude plugin update deadhd@deadhd`. Turning on **Enable auto-update** for the deadhd marketplace in the Marketplaces tab of `/plugin` installs new versions automatically. After updating, run `/reload-plugins` or start a new session |
| Orca | A share link is a fixed copy from publish time, so reopening it does not install a new version. For the latest version, install via the plugin or the skill folder |
| Skill folder | `git pull` in the cloned repository, then copy `skills/deadhd` again |

## Usage

| Input | Behavior |
|---|---|
| `/deadhd` | Opens the progress page in a browser tab (same as `-h`) |
| `/deadhd -o` | Publishes as an Orca artifact (a web page with a shareable link). Requires an orca CLI login; falls back to a browser tab on failure |
| `/deadhd -c` | Publishes as a Claude artifact |
| `/deadhd setup` | Chooses the default open location, display, theme, and font again |
| `/deadhd hub` | Opens the hub page that gathers this machine's sessions |
| `/deadhd --open <mode>` | Opens in a different location for this run only |
| `/deadhd --view <display>` | Draws in a different display for this run only |
| `/deadhd --theme <theme>` | Renders with a different theme for this run only |
| `/deadhd --font <preset>` | Renders this run with a different heading font |
| `/deadhd off` | Stops updating the page |

While the band or the status line is showing in Claude Code:

| Input | Behavior |
|---|---|
| `/deadhd-band` | Folds or opens the band above the prompt |
| `/deadhd-statusline` | Folds or opens the status line under the prompt |
| `/deadhd-open` | Renders the progress page and opens it in a browser |

Instead of a command, you can ask in plain words, e.g. "show progress" or "show me a checklist".

## Settings

On the first run, it asks once for the open location, the display, the theme, and the font. The chosen values are reused from the next run on.

| Value | Behavior |
|---|---|
| `auto` | Opens an Orca tab when running inside Orca, otherwise the system browser |
| `orca` | Opens an Orca tab when the `orca` command is available |
| `browser` | Skips Orca and opens the system browser |
| `desktop` | Does not open the page; prints only the path. Press that path in the Claude desktop app to open it in the in-app browser panel. You can press the printed http address instead |

The display uses these values. Outside Claude Code the question is not asked and the display stays `html`.

| Value | Behavior |
|---|---|
| `band` | One line above the prompt (recommended) |
| `statusline` | One line under the prompt |
| `html` | The browser page |

The theme uses these values.

| Value | Behavior |
|---|---|
| `system` | Follows the operating system's light/dark setting (recommended) |
| `light` | Always the light theme |
| `dark` | Always the dark theme (Aurora) |
| `neon` | Cyberpunk neon: near-black violet with cyan, magenta, and fluorescent yellow |
| `synthwave` | Synthwave sunset: deep violet over a pink-and-orange retro sunset |
| `matrix` | Matrix terminal: green monochrome on black, every glyph monospaced |
| `nord` | Nord arctic: a calm palette that is easy on the eyes over a long session |
| `paper` | Paper notebook: a warm paper-texture light theme with a serif heading |
| `sakura` | Sakura: a cherry-blossom pink light theme with a handwritten heading |
| `ink` | Ink: pure white on pure black. States are told apart by fill, outline, and hatching instead of color |

### Fonts

A heading font is chosen by a single preset name. A preset bundles the family, weight, and letter spacing, and the default `default` keeps the heading font the theme already sets. Pick one in `/deadhd setup`, or change it for one run with `/deadhd --font <preset>`. The body font does not change.

| Value | Family | Weight · letter spacing |
|---|---|---|
| `default` | The theme's own font | Follows the theme |
| `pretendard` | Pretendard Variable | 800 · -0.03em |
| `noto-sans` | Noto Sans KR | 900 · -0.03em |
| `plex-sans` | IBM Plex Sans KR | 700 · -0.02em |
| `gothic-a1` | Gothic A1 | 900 · -0.03em |
| `nanum-gothic` | Nanum Gothic | 800 · -0.02em |
| `noto-serif` | Noto Serif KR | 900 · -0.02em |
| `nanum-myeongjo` | Nanum Myeongjo | 800 · -0.02em |
| `hahmlet` | Hahmlet | 900 · -0.02em |
| `gowun-batang` | Gowun Batang | 700 · -0.01em |
| `do-hyeon` | Do Hyeon | 400 · -0.04em |
| `black-han-sans` | Black Han Sans | 400 · 0 |

The config file is `~/.config/deadhd/config.json`, created under `XDG_CONFIG_HOME` when that is set. `/deadhd setup` lets you choose the open location, theme, and font again at any time.

If `~/.config/deadhd/writing-rules.md` exists, page sentences follow that file's rules. Without it, the default rules apply (noun-phrase titles, field terminology, no personification). You can symlink it to your own writing guide.

Call it once after starting a long task, and Claude updates the data whenever a step's state changes. A complete example of the data format is in [`skills/deadhd/example.json`](skills/deadhd/example.json).

## Files and ports

The files deadhd writes and reads.

| Path | Content |
|---|---|
| `/tmp/deadhd-<slug>.json` | Progress data. Written by the model |
| `/tmp/deadhd-<slug>.html` | Progress page |
| `/tmp/deadhd-hub.html` | Hub page |
| `/tmp/deadhd-state/<session ID>.json` | Session state. Written by the hooks and `render.py`. Files older than 7 days are cleaned up |
| `~/.config/deadhd/config.json` | Settings (open location, theme, font) |
| `~/.config/deadhd/history.jsonl` | Estimate and actual history |
| `~/.config/deadhd/writing-rules.md` | Writing rules (optional) |

The server uses port 47320 on 127.0.0.1. These environment variables change the defaults.

| Variable | Default |
|---|---|
| `DEADHD_PORT` | `47320` |
| `DEADHD_HUB` | `/tmp/deadhd-hub.html` |
| `DEADHD_STATE_DIR` | `/tmp/deadhd-state` |
| `DEADHD_HISTORY` | `~/.config/deadhd/history.jsonl` |
| `DEADHD_CONFIG` | `~/.config/deadhd/config.json` |
| `XDG_CONFIG_HOME` | When set, the settings and history are created under `$XDG_CONFIG_HOME/deadhd/` |
| `DEADHD_NOW` | Fixes the time the page uses. Used by tests and by example image capture |

## Test

```bash
python3 -m unittest skills/deadhd/test_render.py
```

The ten example images are regenerated on a machine with Chrome via these commands.

```bash
python3 docs/capture_themes.py && python3 docs/capture_themes.py --lang en   # themes.png, themes.en.png
python3 docs/capture_views.py && python3 docs/capture_views.py --lang en     # views.png, views.en.png
python3 docs/capture_hub.py && python3 docs/capture_hub.py --lang en         # hub.png, hub.en.png, live.png, live.en.png
python3 docs/capture_board.py && python3 docs/capture_board.py --lang en     # board.png, board.en.png
```

## License

[MIT](LICENSE)
