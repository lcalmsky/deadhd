## Setup

Ask once, then save the answers as the defaults. There are four questions: the default open location, the default display, the default theme, and the default heading font. Ask with the `AskUserQuestion` tool when it is available, otherwise ask in plain text; when the tool is available, put all four questions in a single call (the tool allows at most four). The display answer decides whether a fifth question follows (see Session HUD).

Display, three choices:

- `band` (recommended): a one-line band above the prompt. Lightest of the three, and no browser tab.
- `statusline`: a hint line under the prompt, with more fields on the line.
- `html`: the browser page, as before.

Save it with `python3 <skill-dir>/config.py set view <value>`. Outside Claude Code (no `CLAUDE_CODE_SESSION_ID`) skip this question and leave the view at `html`, which is also what a session with no saved view and no state file draws.

Session HUD, asked as a second `AskUserQuestion` call right after the first one, and only when the display answer is `band` or `statusline`. Two choices:

- `on` (recommended): the session state, the wait and the last tool are drawn from the session's own events, so they show before `/deadhd` has run.
- `off`: the line is drawn from the run that has written the checklist, so nothing of the session's own watch shows.

Save it with `python3 <skill-dir>/config.py set hud <value>`. With the `html` display, or outside Claude Code, do not ask it and save nothing: an unset `hud` reads as `on`.

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

Save the answers with `python3 <skill-dir>/config.py set open <value>`, `python3 <skill-dir>/config.py set view <value>`, `python3 <skill-dir>/config.py set theme <value>`, and `python3 <skill-dir>/config.py set font <value>`. Calling the skill with `setup` asks all four questions again, and the HUD question when the display answer is `band` or `statusline`.

- First run: on an ordinary run that is not `-c`, `-o`, `--open`, `off`, or `setup`, run `python3 <skill-dir>/config.py get open`, `python3 <skill-dir>/config.py get view`, `python3 <skill-dir>/config.py get theme`, `python3 <skill-dir>/config.py get font`, and `python3 <skill-dir>/config.py get hud` first. Ask only for the ones that print `unset`, save them, then continue the original work. The display question is skipped outside Claude Code, and the HUD question is asked only when the display answer is `band` or `statusline`.
