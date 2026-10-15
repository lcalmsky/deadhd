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
  - `stallAfter`: minutes of silence before a `now` lane counts as stalled. Defaults to 10. The page decides this in the browser, so a lane you stopped updating still shows up as stalled.
  - `estimate`: minutes left, as on a `now` item.
  - `note`: a few words under the current stage dot, e.g. `code-reviewer`.
  - `body`: the text the row expands to, one or two sentences.
  - `evidence`: chips, as on an item. `log`: the lane's own transitions, `{"at": …, "text": …}` each; the page shows the eight newest of all lanes together.
