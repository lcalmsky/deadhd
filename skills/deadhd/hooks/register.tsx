import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, ThemeKey } from 'claude-code'

import type { DeadhdLang, DeadhdState, DeadhdStep, DeadhdView } from '../types'

const DEFAULT_STATE_DIR = '/tmp/deadhd-state'
const REFRESH_MS = 5000

/** PromptHint hands the tree no width, so this is the budget its pieces are cut to. */
const STATUS_COLS = 240
/** Cells the progress bar draws; `done/total` is rounded onto them. */
const BAR_CELLS = 6
const SEP = ' · '
const OPEN_TIMEOUT_MS = 15000

/** The slash command each line leads with, the one that folds it. */
const BAND_CMD = '/deadhd-band'
const STATUS_CMD = '/deadhd-statusline'

/** The command a status line names at its end, so the page has a keyboard way open too. */
const OPEN_CMD = '/deadhd-open'

/** With no state file and no config the session draws in this view, as render.py decides too. */
export const DEFAULT_VIEW: DeadhdView = 'html'

const VIEWS: readonly DeadhdView[] = ['html', 'band', 'statusline']

/** The theme keys a piece may name; `plain` leaves the text the person's own color. */
export type Tone =
  | 'plain'
  | Extract<
      ThemeKey,
      | 'claude'
      | 'permission'
      | 'text'
      | 'success'
      | 'subtle'
      | 'planMode'
      | 'warning'
      | 'error'
      | 'suggestion'
      | 'inactive'
      | 'autoAccept'
      | 'merged'
      | 'ide'
      | 'remember'
    >

/** One drawn piece of a line: `text` is what shows, `tone` what colors it. */
export type Segment = { text: string; tone: Tone; bold?: boolean }

/** One field of a line: its pieces drawn side by side, a separator before the next field. */
type Field = { tag: string; parts: Segment[] }

const WORDS: Record<
  DeadhdLang,
  {
    blocked: string
    left: string
    allDone: string
    next: string
    eta: string
    background: string
    compacted: string
    collapse: string
    expand: string
    open: string
    folded: string
    unfolded: string
    statusFolded: string
    statusUnfolded: string
    bandOnly: string
    statusOnly: string
    permission: string
    input: string
    opened: string
    noPage: string
    openFailed: string
    desktopPath: string
    noBrowser: string
  }
> = {
  ko: {
    blocked: '막힘',
    left: '남음',
    allDone: '완료',
    next: '다음',
    eta: '예상',
    background: '백그라운드',
    compacted: '압축',
    collapse: '접기',
    expand: '펼치기',
    open: '열기',
    folded: '밴드를 접었어요',
    unfolded: '밴드를 펼쳤어요',
    statusFolded: '상태줄을 접었어요',
    statusUnfolded: '상태줄을 펼쳤어요',
    bandOnly: '지금은 밴드 모드가 아니에요. /deadhd setup 에서 밴드를 고르면 보여요.',
    statusOnly: '지금은 상태줄 모드가 아니에요. /deadhd setup 에서 상태줄을 고르면 보여요.',
    permission: '권한 승인 대기',
    input: '입력 대기',
    opened: 'HTML 페이지를 열었어요',
    noPage: '아직 HTML 페이지가 없어요',
    openFailed: 'HTML 페이지를 열지 못했어요',
    desktopPath: 'Claude 데스크톱 앱에서 이 경로를 눌러 주세요:',
    noBrowser: '열 수 있는 브라우저를 찾지 못했어요:',
  },
  en: {
    blocked: 'blocked',
    left: 'left',
    allDone: 'all done',
    next: 'next',
    eta: 'ETA',
    background: 'background',
    compacted: 'compacted',
    collapse: 'Collapse',
    expand: 'Expand',
    open: 'Open',
    folded: 'Band collapsed.',
    unfolded: 'Band expanded.',
    statusFolded: 'Collapsed the status line',
    statusUnfolded: 'Expanded the status line',
    bandOnly: 'The band is not drawn in this view. Choose band with /deadhd setup.',
    statusOnly: 'The status line is not drawn in this view. Choose statusline with /deadhd setup.',
    permission: 'waiting for permission',
    input: 'waiting for input',
    opened: 'Opened the HTML.',
    noPage: 'No HTML page yet.',
    openFailed: 'Could not open the HTML',
    desktopPath: 'Press this path in the Claude desktop app to open the page:',
    noBrowser: 'Could not find a browser to open the page:',
  },
}

const live = atom({ plugin: 'deadhd', key: 'state' } as const, null)
const collapsed = atom({ plugin: 'deadhd', key: 'collapsed' } as const, false)
const shown = atom({ plugin: 'deadhd', key: 'view' } as const, DEFAULT_VIEW)

/**
 * The text each mode last asked a repaint for, so a refresh whose line did not
 * move stays quiet. A hot reload losing it costs one extra repaint.
 */
const painted: Partial<Record<'band' | 'status', string>> = {}

/**
 * The cells each mode's line may take, as the surface last measured them: the
 * band's region without its buttons, the status line's viewport without the
 * button beside it. A refresh cuts the line it compares to the same width; the
 * fixed budget stands in until a drawing has measured one.
 */
const widths: Record<'band' | 'status', number> = { band: STATUS_COLS, status: STATUS_COLS }

/**
 * Code point ranges that take two cells in a terminal's monospace metric:
 * East Asian Wide, plus the emoji blocks a terminal draws with emoji
 * presentation (a symbol below U+1F300 like `✅` or `⏳` is one of these).
 */
const WIDE: readonly (readonly [number, number])[] = [
  [0x1100, 0x115f],
  [0x231a, 0x231b],
  [0x23e9, 0x23f3],
  [0x25fd, 0x25fe],
  [0x2614, 0x2615],
  [0x2648, 0x2653],
  [0x267f, 0x267f],
  [0x2693, 0x2693],
  [0x26a1, 0x26a1],
  [0x26aa, 0x26ab],
  [0x26bd, 0x26be],
  [0x26c4, 0x26c5],
  [0x26ce, 0x26ce],
  [0x26d4, 0x26d4],
  [0x26ea, 0x26ea],
  [0x26f2, 0x26f3],
  [0x26f5, 0x26f5],
  [0x26fa, 0x26fa],
  [0x26fd, 0x26fd],
  [0x2705, 0x2705],
  [0x270a, 0x270b],
  [0x2728, 0x2728],
  [0x274c, 0x274c],
  [0x274e, 0x274e],
  [0x2753, 0x2755],
  [0x2757, 0x2757],
  [0x2795, 0x2797],
  [0x27b0, 0x27b0],
  [0x27bf, 0x27bf],
  [0x2b1b, 0x2b1c],
  [0x2b50, 0x2b50],
  [0x2b55, 0x2b55],
  [0x2e80, 0xa4cf],
  [0xac00, 0xd7a3],
  [0xf900, 0xfaff],
  [0xfe30, 0xfe4f],
  [0xff00, 0xff60],
  [0xffe0, 0xffe6],
  [0x1f300, 0x1faff],
  [0x20000, 0x3fffd],
]

/** Code point ranges that take no cell of their own (combining and zero width). */
const ZERO: readonly (readonly [number, number])[] = [
  [0x0300, 0x036f],
  [0x200b, 0x200f],
  [0xfe00, 0xfe0f],
]

/** The variation selector that asks for a glyph's emoji drawing. */
const VS16 = 0xfe0f

const within = (code: number, ranges: readonly (readonly [number, number])[]): boolean =>
  ranges.some(([low, high]) => code >= low && code <= high)

/**
 * How many terminal cells `text` takes, one code point at a time. A symbol
 * drawn as text (`✓`, `▶`, `↗`, `▓`) is one cell, an emoji-presentation one is
 * two, and a base character followed by U+FE0F is drawn as the emoji it selects.
 */
export function cellWidth(text: string): number {
  const points = Array.from(text, code => code.codePointAt(0) ?? 0)
  let cells = 0

  for (let at = 0; at < points.length; at += 1) {
    const point = points[at] ?? 0

    if (within(point, ZERO)) {
      // The selector itself is no cell; the character it follows gains the one
      // that makes it an emoji.
      const before = points[at - 1]

      if (point === VS16 && before !== undefined && !within(before, WIDE) && !within(before, ZERO)) {
        cells += 1
      }

      continue
    }

    cells += within(point, WIDE) ? 2 : 1
  }

  return cells
}

/** Cells a band control takes when drawn: `[ label ]`, brackets and padding included. */
const buttonCols = (label: string): number => cellWidth(label) + 4

/** The Text props a tone names: the theme key itself, or the text's own color. */
const paint = (tone: Tone): { color?: ThemeKey } => (tone === 'plain' ? {} : { color: tone })

const record = (value: unknown): Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}

const count = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0

const text = (value: unknown, fallback: string): string =>
  typeof value === 'string' ? value : fallback

/** A value the config or a state file may spell as a view; anything else has no reading. */
const asView = (value: unknown): DeadhdView | null =>
  typeof value === 'string' && (VIEWS as readonly string[]).includes(value)
    ? (value as DeadhdView)
    : null

/** The view in force: the state file's own, else the config file's, else the default. */
export function resolveView(stateView: unknown, configView: unknown): DeadhdView {
  return asView(stateView) ?? asView(configView) ?? DEFAULT_VIEW
}

/** A lane or column as the data file may spell it; a non-integer has no reading. */
const asIndex = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value >= 0 ? Math.floor(value) : null
  }

  if (typeof value === 'string' && /^\d+$/.test(value)) {
    return Number(value)
  }

  return null
}

/** The words the lines add for a status the session waits in; null while it works or has ended. */
export function statusLabel(status: string, lang: DeadhdLang): string | null {
  if (status === '' || status === 'working' || status === 'ended') {
    return null
  }

  const words = WORDS[lang]

  if (status === 'waiting_permission') {
    return words.permission
  }

  if (status === 'idle') {
    return words.input
  }

  return status
}

/** Whole minutes between an ISO instant and `now`, or null when either does not read as one. */
const minutesBetween = (from: string | null, now: number): number | null => {
  if (from === null) {
    return null
  }

  const at = Date.parse(from)

  if (!Number.isFinite(at) || now < at) {
    return null
  }

  return Math.floor((now - at) / 60000)
}

/** `8분째` / `8m in`: how long a step has been running. */
const since = (minutes: number, lang: DeadhdLang): string =>
  lang === 'en' ? `${minutes}m in` : `${minutes}분째`

/** `8분 전` / `8m ago`: how long since the state file was written. */
const ago = (minutes: number, lang: DeadhdLang): string =>
  lang === 'en' ? `${minutes}m ago` : `${minutes}분 전`

/** The `HH:MM` an eta carries, in the offset its writer used; null for anything else. */
const clockOf = (eta: string | null): string | null => {
  if (eta === null) {
    return null
  }

  const match = /T(\d{2}:\d{2})/.exec(eta)

  return match === null ? null : (match[1] ?? null)
}

/** The first line of a command's stderr, trimmed; `''` when it wrote none. */
const firstLine = (output: string): string => (output.split('\n')[0] ?? '').trim()

/** `label` cut to `room` cells, its ellipsis counted, or `…` when not even one cell is left. */
const cut = (label: string, room: number): string => {
  if (cellWidth(label) <= room) {
    return label
  }

  if (room <= 1) {
    return '…'
  }

  let kept = ''
  let used = 0

  for (const code of label) {
    const wide = cellWidth(code)

    if (used + wide > room - 1) {
      break
    }

    kept += code
    used += wide
  }

  return `${kept.trimEnd()}…`
}

const barParts = (done: number, total: number): Segment[] => {
  const cells = Math.max(0, Math.min(BAR_CELLS, Math.round((done / total) * BAR_CELLS)))
  const parts: Segment[] = []

  if (cells > 0) {
    parts.push({ text: '▓'.repeat(cells), tone: 'success' })
  }

  if (cells < BAR_CELLS) {
    parts.push({ text: '░'.repeat(BAR_CELLS - cells), tone: 'subtle' })
  }

  return parts
}

/** The glyph and color a marked step carries: work running in parallel draws its own. */
const stepMark = (state: string, running: string): Segment =>
  state === 'side'
    ? { text: '◇', tone: 'autoAccept' }
    : { text: running, tone: 'suggestion', bold: true }

/** The piece for the step a line marks, colored and marked by that step's own state. */
const stepField = (step: DeadhdStep, lang: DeadhdLang, now: number, running: string): Field => {
  const mark = stepMark(step.state, running)
  const minutes = minutesBetween(step.startedAt, now)
  const tail = minutes === null ? '' : ` ${since(minutes, lang)}`

  return {
    tag: 'current',
    parts: [
      { text: `${mark.text} ${step.label}${tail}`, tone: mark.tone, bold: mark.bold === true },
    ],
  }
}

/** The piece for a session waiting on the person, or null while this session works. */
const waitField = (state: DeadhdState, now: number): Field | null => {
  if (state.status !== 'waiting_permission' && state.status !== 'idle') {
    return null
  }

  const word = statusLabel(state.status, state.lang) ?? state.status
  const minutes = minutesBetween(state.since, now)
  const tail = minutes === null ? '' : ` ${since(minutes, state.lang)}`
  const asking = state.status === 'waiting_permission'

  return {
    tag: 'wait',
    parts: [
      { text: `${asking ? '🔐' : '⌨️'} ${word}${tail}`, tone: asking ? 'warning' : 'merged', bold: true },
    ],
  }
}

/** The band's first row: how far the run has come, and what is on it. */
const bandFields = (state: DeadhdState, now: number): Field[] => {
  const words = WORDS[state.lang]
  const fields: Field[] = [{ tag: 'name', parts: [{ text: BAND_CMD, tone: 'claude', bold: true }] }]

  if (state.total > 0) {
    fields.push({
      tag: 'bar',
      parts: [
        ...barParts(state.done, state.total),
        { text: ' ', tone: 'plain' },
        { text: `${state.done}/${state.total}`, tone: 'success', bold: true },
      ],
    })
  }

  if (state.current !== null) {
    fields.push(stepField(state.current, state.lang, now, '▶'))
  }

  if (state.blocked > 0) {
    fields.push({
      tag: 'stuck',
      parts: [{ text: `${words.blocked} ${state.blocked}`, tone: 'error', bold: true }],
    })
  }

  if (state.left > 0) {
    fields.push({ tag: 'leftCount', parts: [{ text: `${words.left} ${state.left}`, tone: 'text' }] })
  }

  if (state.allDone) {
    fields.push({ tag: 'allDone', parts: [{ text: words.allDone, tone: 'success', bold: true }] })
  }

  return fields
}

/** The band's second row: the step that got stuck and the wait, when either is on. */
const bandAlertFields = (state: DeadhdState, now: number): Field[] => {
  const words = WORDS[state.lang]
  const fields: Field[] = []

  if (state.stuck !== null) {
    const note = state.stuck.sub === '' ? state.stuck.label : `${state.stuck.label} (${state.stuck.sub})`

    fields.push({
      tag: 'blocked',
      parts: [
        { text: `⛔ ${words.blocked}: `, tone: 'error', bold: true },
        { text: note, tone: 'error', bold: true },
      ],
    })
  }

  const wait = waitField(state, now)

  if (wait !== null) {
    fields.push(wait)
  }

  return fields
}

/** The status line's pieces, in the order the long row draws them. */
const statusFields = (state: DeadhdState, now: number): Field[] => {
  const words = WORDS[state.lang]
  const fields: Field[] = [{ tag: 'name', parts: [{ text: STATUS_CMD, tone: 'claude', bold: true }] }]

  if (state.total > 0) {
    fields.push({
      tag: 'count',
      parts: [
        { text: `✅ ${state.done}/${state.total}`, tone: 'success', bold: true },
        { text: ' ', tone: 'plain' },
        ...barParts(state.done, state.total),
      ],
    })
  }

  const heading: Segment[] = []

  if (state.key !== null) {
    heading.push({
      text: state.title === '' ? state.key : `${state.key} `,
      tone: 'permission',
      bold: true,
    })
  }

  if (state.title !== '') {
    heading.push({ text: state.title, tone: 'text' })
  }

  if (heading.length > 0) {
    fields.push({ tag: 'title', parts: heading })
  }

  if (state.current !== null) {
    fields.push(stepField(state.current, state.lang, now, '▶️'))
  }

  if (state.next !== null) {
    fields.push({
      tag: 'next',
      parts: [{ text: `⏭ ${words.next} ${state.next.label}`, tone: 'inactive' }],
    })
  }

  const eta = clockOf(state.eta)

  if (eta !== null) {
    fields.push({ tag: 'eta', parts: [{ text: `⏱ ${words.eta} ${eta}`, tone: 'planMode' }] })
  }

  const stale = minutesBetween(state.updatedAt, now)

  if (stale !== null) {
    fields.push({ tag: 'ago', parts: [updatePiece(stale, state.lang)] })
  }

  if (state.blocked > 0) {
    const parts: Segment[] = [
      { text: `⛔ ${words.blocked} ${state.blocked}`, tone: 'error', bold: true },
    ]

    if (state.stuck !== null) {
      parts.push({ text: `: ${state.stuck.label}`, tone: 'error', bold: true })
    }

    fields.push({ tag: 'blocked', parts })
  }

  if (state.left > 0) {
    fields.push({ tag: 'left', parts: [{ text: `⏳ ${words.left} ${state.left}`, tone: 'text' }] })
  }

  const wait = waitField(state, now)

  if (wait !== null) {
    fields.push(wait)
  }

  if (state.background > 0) {
    fields.push({
      tag: 'background',
      parts: [{ text: `🧵 ${words.background} ${state.background}`, tone: 'ide' }],
    })
  }

  if (state.compactions > 0) {
    fields.push({
      tag: 'compacted',
      parts: [{ text: `🗜 ${words.compacted} ${state.compactions}`, tone: 'remember' }],
    })
  }

  fields.push({ tag: 'openCmd', parts: [{ text: `↗ ${OPEN_CMD}`, tone: 'suggestion' }] })

  return fields
}

/** The last-update piece: quiet while the skill keeps up, louder as it falls behind. */
const updatePiece = (minutes: number, lang: DeadhdLang): Segment => {
  const body = ago(minutes, lang)

  if (minutes > 30) {
    return { text: `🛑 ${body}`, tone: 'error' }
  }

  if (minutes > 10) {
    return { text: `⚠️ ${body}`, tone: 'warning' }
  }

  return { text: `🔄 ${body}`, tone: 'subtle' }
}

const fieldWidth = (field: Field): number =>
  field.parts.reduce((cells, part) => cells + cellWidth(part.text), 0)

/** Cells the whole line takes, its separators counted. */
const lineWidth = (fields: readonly Field[]): number =>
  fields.length === 0
    ? 0
    : fields.reduce((cells, field) => cells + fieldWidth(field), 0) +
      (fields.length - 1) * cellWidth(SEP)

/** Cuts a field's last piece to the cells left for it, or drops that piece when none are. */
const cutLast = (field: Field, room: number): void => {
  const last = field.parts[field.parts.length - 1]

  if (last === undefined) {
    return
  }

  const fixed = field.parts
    .slice(0, -1)
    .reduce((cells, part) => cells + cellWidth(part.text), 0)
  const left = room - fixed

  if (left <= 1) {
    field.parts.pop()

    return
  }

  field.parts[field.parts.length - 1] = { ...last, text: cut(last.text, left) }
}

/**
 * Brings a line inside `maxCols` cells, giving way in the order the fields can
 * spare it: the title first, then the next step, then the blocked step's label,
 * the step a line marks, and the command a status line ends with last of all.
 */
const fit = (fields: Field[], maxCols: number): Field[] => {
  const shrink = (tag: string): void => {
    const field = fields.find(one => one.tag === tag)

    if (field === undefined) {
      return
    }

    cutLast(field, maxCols - (lineWidth(fields) - fieldWidth(field)))
  }

  const drop = (tag: string): void => {
    const at = fields.findIndex(one => one.tag === tag)

    if (at >= 0) {
      fields.splice(at, 1)
    }
  }

  if (lineWidth(fields) > maxCols) shrink('title')
  if (lineWidth(fields) > maxCols) drop('next')
  if (lineWidth(fields) > maxCols) shrink('blocked')
  if (lineWidth(fields) > maxCols) drop('blocked')
  if (lineWidth(fields) > maxCols) shrink('current')
  if (lineWidth(fields) > maxCols) drop('current')
  if (lineWidth(fields) > maxCols) drop('openCmd')

  return fields.filter(field => field.parts.length > 0)
}

/** One line's fields as the pieces a drawing lays out, a separator between the fields. */
const flatten = (fields: readonly Field[]): Segment[] => {
  const parts: Segment[] = []

  fields.forEach((field, index) => {
    if (index > 0) {
      parts.push({ text: SEP, tone: 'subtle' })
    }

    for (const part of field.parts) {
      parts.push(part)
    }
  })

  return parts
}

/** The band's first row, cut to `maxCols` cells. */
export function bandLine(state: DeadhdState | null, now: number, maxCols: number): Segment[] {
  if (state === null) {
    return []
  }

  return flatten(fit(bandFields(state, now), maxCols))
}

/** The band's second row, empty when neither a stuck step nor a wait is on. */
export function bandAlertLine(state: DeadhdState | null, now: number, maxCols: number): Segment[] {
  if (state === null) {
    return []
  }

  return flatten(fit(bandAlertFields(state, now), maxCols))
}

const segmentsText = (parts: readonly Segment[]): string => parts.map(part => part.text).join('')

/** The status line's pieces, cut to `maxCols` cells. */
export function statusLine(state: DeadhdState | null, now: number, maxCols: number): Segment[] {
  if (state === null) {
    return []
  }

  return flatten(fit(statusFields(state, now), maxCols))
}

/** The status line as plain text: the same pieces a drawing lays out, joined. */
export function formatLine(state: DeadhdState | null, now: number, maxCols: number): string {
  return segmentsText(statusLine(state, now, maxCols))
}

/** The folded band's one line: the command and how far the run has come, nothing else. */
function foldedSegments(state: DeadhdState): Segment[] {
  const parts: Segment[] = [{ text: BAND_CMD, tone: 'claude', bold: true }]

  if (state.total > 0) {
    parts.push(
      { text: ' ', tone: 'plain' },
      { text: `✓ ${state.done}/${state.total}`, tone: 'success' },
    )
  }

  return parts
}

/** The folded status line's one piece: the command, the count, and the way to the page. */
function statusFoldedSegments(state: DeadhdState): Segment[] {
  const parts: Segment[] = [{ text: STATUS_CMD, tone: 'claude', bold: true }]

  if (state.total > 0) {
    parts.push(
      { text: ' ', tone: 'plain' },
      { text: `✅ ${state.done}/${state.total}`, tone: 'success', bold: true },
    )
  }

  parts.push({ text: SEP, tone: 'subtle' }, { text: `↗ ${OPEN_CMD}`, tone: 'suggestion' })

  return parts
}

/** The data file's items in lane·column order; a column the data leaves out follows its lane's last. */
const readSteps = (data: unknown): DeadhdStep[] => {
  const board = record(data)
  const raw = board.items

  if (!Array.isArray(raw)) {
    return []
  }

  const items: readonly unknown[] = raw
  const lanes: readonly unknown[] = Array.isArray(board.lanes) ? board.lanes : []

  const laneOf = (value: unknown): number => {
    const direct = asIndex(value)

    if (direct !== null) {
      return direct
    }

    if (typeof value === 'string') {
      const at = lanes.findIndex(
        lane => lane === value || record(lane).id === value || record(lane).label === value,
      )

      if (at >= 0) {
        return at
      }
    }

    return 0
  }

  const filled = new Map<number, number>()

  return items
    .map((item, index) => {
      const source = record(item)
      const lane = laneOf(source.lane)
      const given = asIndex(source.col)
      const col = given ?? filled.get(lane) ?? 0

      filled.set(lane, col + 1)

      const step: DeadhdStep = {
        state: text(source.state, ''),
        label: text(source.label, ''),
        sub: text(source.sub, ''),
        startedAt: typeof source.startedAt === 'string' ? source.startedAt : null,
        lane,
        col,
      }

      return { step, index }
    })
    .sort(
      (left, right) =>
        left.step.lane - right.step.lane ||
        left.step.col - right.step.col ||
        left.index - right.index,
    )
    .map(one => one.step)
}

/** The first `left` step after `current`, in lane·column order. */
const nextStep = (steps: readonly DeadhdStep[], current: DeadhdStep | null): DeadhdStep | null => {
  const from = current === null ? 0 : steps.indexOf(current) + 1

  for (let at = Math.max(0, from); at < steps.length; at += 1) {
    const step = steps[at]

    if (step !== undefined && step.state === 'left') {
      return step
    }
  }

  return null
}

/** The non-empty string a state file field holds, or null. */
const path = (value: unknown): string | null =>
  typeof value === 'string' && value !== '' ? value : null

/**
 * One session's state file and data file together, as the two lines read them.
 * A shape this build does not know, or a data file that is missing or broken,
 * costs the parts that read it, never the whole line.
 */
export function normalize(raw: unknown, data?: unknown): DeadhdState | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    return null
  }

  const source = record(raw)
  const summary = record(source.summary)
  const counts = record(summary.counts)
  const steps = readSteps(data)
  const nowLabel = text(summary.nowLabel, '')
  // The hooks rewrite the state file on every event, so its own write time stays
  // fresh while the skill stalls. The data file's last write is the honest clock,
  // and a state file that carries none (an older one) falls back to `updatedAt`.
  const dataAt = typeof summary.dataAt === 'string' && summary.dataAt !== '' ? summary.dataAt : null
  const done = count(counts.done)
  const now = count(counts.now)
  const side = count(counts.side)
  const left = count(counts.left)
  const blocked = count(counts.blocked)

  // Without a data file the summary still names what runs, its nowLabel falling
  // back to the blocked step; the step's own state and start time are then lost.
  const summaryStep: DeadhdStep | null =
    steps.length === 0 && nowLabel !== ''
      ? {
          state: now > 0 ? 'now' : 'blocked',
          label: nowLabel,
          sub: '',
          startedAt: null,
          lane: 0,
          col: 0,
        }
      : null
  const running = steps.find(step => step.state === 'now') ?? steps.find(step => step.state === 'side') ?? null

  return {
    status: text(source.status, 'working'),
    lang: summary.lang === 'en' ? 'en' : 'ko',
    key: typeof summary.key === 'string' && summary.key !== '' ? summary.key : null,
    title: text(summary.title, ''),
    done,
    now,
    side,
    left,
    blocked,
    total: count(summary.total),
    allDone: summary.allDone === true,
    current: running ?? (now > 0 ? summaryStep : null),
    next: nextStep(steps, running),
    stuck: steps.find(step => step.state === 'blocked') ?? (now === 0 && blocked > 0 ? summaryStep : null),
    eta: typeof summary.eta === 'string' ? summary.eta : null,
    updatedAt: dataAt ?? (typeof source.updatedAt === 'string' ? source.updatedAt : null),
    since: typeof source.since === 'string' ? source.since : null,
    background: Array.isArray(source.backgroundTasks) ? source.backgroundTasks.length : 0,
    compactions: count(record(source.compactions).count),
    view: asView(source.view),
    data: path(source.data),
    out: path(source.out),
  }
}

/** One session as the two files leave it; null when the state file is not there or is not JSON. */
async function load($: EngineInterface): Promise<DeadhdState | null> {
  try {
    const dir = (await $.env.get('DEADHD_STATE_DIR')) ?? DEFAULT_STATE_DIR
    const session = await $.session.id()
    const raw: unknown = JSON.parse(await $.fs.read(`${dir}/${session}.json`))
    const data = path(record(raw).data)
    let board: unknown = null

    if (data !== null) {
      try {
        board = JSON.parse(await $.fs.read(data))
      } catch {
        board = null
      }
    }

    return normalize(raw, board)
  } catch {
    return null
  }
}

/** The deadhd config file's path, by the rule config.py's `config_path()` writes it. */
async function configPath($: EngineInterface): Promise<string | null> {
  const override = await $.env.get('DEADHD_CONFIG')

  if (typeof override === 'string' && override !== '') {
    return override
  }

  const xdg = await $.env.get('XDG_CONFIG_HOME')

  if (typeof xdg === 'string' && xdg !== '') {
    return `${xdg}/deadhd/config.json`
  }

  const home = await $.env.get('HOME')

  return typeof home === 'string' && home !== '' ? `${home}/.config/deadhd/config.json` : null
}

/** The view the deadhd config file saves, or null when it saves none this build knows. */
async function configView($: EngineInterface): Promise<DeadhdView | null> {
  const file = await configPath($)

  if (file === null) {
    return null
  }

  try {
    const raw: unknown = JSON.parse(await $.fs.read(file))

    return asView(record(raw).view)
  } catch {
    return null
  }
}

/** The view in force for this session: the state file's, else the config's, else `html`. */
async function viewOf($: EngineInterface, state: DeadhdState | null): Promise<DeadhdView> {
  return resolveView(state?.view ?? null, await configView($))
}

/**
 * The skill folder beside this module. It is the plugin root for a
 * skill-folder install and `${root}/skills/deadhd` for a marketplace one;
 * the one that holds render.py answers.
 */
async function skillDir($: EngineInterface): Promise<string> {
  const root = $.plugin.root

  try {
    await $.fs.stat(`${root}/render.py`)

    return root
  } catch {
    return `${root}/skills/deadhd`
  }
}

/**
 * Whether the fresh state asks for the person: a new blockage, or a wait for
 * permission. A turn's end also reads as `idle`, so an idle status alone must
 * not unfold a line the person folded.
 */
const needsAttention = (fresh: DeadhdState, previous: DeadhdState): boolean =>
  fresh.blocked > previous.blocked ||
  (fresh.status === 'waiting_permission' && previous.status !== 'waiting_permission')

/**
 * The line the current view would draw now, as plain text: what a refresh
 * compares against the last to tell whether a repaint would move anything.
 * A folded line carries no elapsed time, so it reads the same every interval.
 */
const paintText = (state: DeadhdState, now: number, folded: boolean, view: DeadhdView): string => {
  const mode = view === 'band' ? 'band' : 'status'
  const cells = widths[mode]

  return view === 'band'
    ? folded
      ? segmentsText(foldedSegments(state))
      : segmentsText(bandLine(state, now, cells))
    : folded
      ? segmentsText(statusFoldedSegments(state))
      : formatLine(state, now, cells)
}

/** The kind and the path `open.sh` names on its `opened:` line, or null. */
const openedOf = (output: string): { kind: string; path: string } | null => {
  const match = /^opened: (\S+) (.*)$/m.exec(output)

  return match === null ? null : { kind: match[1] ?? '', path: (match[2] ?? '').trim() }
}

/** What opening the page answers, in the words the button toasts and `/deadhd-open` returns. */
async function openText($: EngineInterface, state: DeadhdState | null): Promise<string> {
  const words = WORDS[state?.lang ?? 'ko']
  const out = state?.out ?? null
  const data = state?.data ?? null

  if (out === null || data === null) {
    return words.noPage
  }

  const dir = await skillDir($)

  try {
    // A session drawing in a band or status line has no page yet; this is what writes one.
    const session = await $.session.id()
    const page = await $.process.run(
      ['python3', `${dir}/render.py`, '--page', '--session', session, data, out],
      { timeoutMs: OPEN_TIMEOUT_MS },
    )

    if (page.exitCode !== 0) {
      const reason = firstLine(page.stderr)

      return `${words.openFailed}: exit ${page.exitCode}${reason === '' ? '' : `: ${reason}`}`
    }

    const opened = await $.process.run(['bash', `${dir}/open.sh`, out], { timeoutMs: OPEN_TIMEOUT_MS })

    if (opened.exitCode !== 0) {
      const reason = firstLine(opened.stderr)

      return `${words.openFailed}: exit ${opened.exitCode}${reason === '' ? '' : `: ${reason}`}`
    }

    // The exit code alone is not the answer: `desktop` and `none` exit 0 with the
    // page unopened, so the path goes into the sentence the person reads.
    const result = openedOf(opened.stdout)

    if (result === null || result.kind === 'orca-tab' || result.kind === 'browser') {
      return words.opened
    }

    return result.kind === 'desktop'
      ? `${words.desktopPath} ${result.path}`
      : `${words.noBrowser} ${result.path}`
  } catch (error) {
    return `${words.openFailed}: ${firstLine(String(error))}`
  }
}

/**
 * Reads the session's two files, the view in force, and, when the state
 * changed, puts it in the atoms the render hooks draw from. A new blockage or
 * a wait for permission opens a folded line again. An interval whose line moved (`8분째`
 * becoming `9분째`) asks the mode's component to draw again, so the clock keeps
 * up without a state write. Its own failures are swallowed: a refresh that
 * cannot read or write leaves the last line standing.
 */
async function refresh($: EngineInterface): Promise<void> {
  try {
    const fresh = await load($)
    const view = await viewOf($, fresh)
    const previous = await read($, live)
    const previousView = await read($, shown)

    if (JSON.stringify(previous) !== JSON.stringify(fresh)) {
      await update($, live, () => fresh)
    }

    // The view is re-read every interval, so a change in the config reaches the
    // lines without a restart; the hook reads this atom rather than the file.
    if (previousView !== view) {
      await update($, shown, () => view)
    }

    if (fresh !== null && previous !== null && needsAttention(fresh, previous)) {
      await update($, collapsed, () => false)
    }

    if (fresh === null || view === 'html') {
      return
    }

    const mode = view === 'band' ? 'band' : 'status'
    const folded = await read($, collapsed)
    const now = await $.clock.now()
    const line = paintText(fresh, now, folded, view)
    const before = painted[mode]

    painted[mode] = line

    if (before !== undefined && before !== line) {
      $.ui.invalidate('ui.render')
    }
  } catch {
    // Left as it stands.
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await refresh($)

    if ((await read($, shown)) === 'statusline') {
      // The status line comes from the PromptHint hook; clear any line an
      // earlier build pinned with `$.ui.status`.
      $.ui.status(undefined)
    }

    await $.command.register({
      name: 'deadhd-band',
      description: 'Fold or open the deadhd band above the prompt.',
    })
    await $.command.register({
      name: 'deadhd-statusline',
      description: 'Fold or open the deadhd status line under the prompt.',
    })
    await $.command.register({
      name: 'deadhd-open',
      description: 'Open the deadhd progress page in a browser.',
    })

    $.clock.every(REFRESH_MS, () => {
      void refresh($)
    })

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const ran = await next(e)

    void refresh($)

    return ran
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)

    // A tool call never waits on this: refresh reads the state, the config and the
    // data JSON, and the timer keeps the line current anyway. It swallows its own
    // failures, so nothing here needs a catch.
    void refresh($)

    return ran
  })

  on('command.run', { command: 'deadhd-open' }, async $ => {
    const state = await read($, live)

    return { text: await openText($, state) }
  })

  on('command.run', { command: 'deadhd-band' }, async $ => {
    const state = await read($, live)
    const words = WORDS[state?.lang ?? 'ko']

    if ((await viewOf($, state)) !== 'band') {
      return { text: words.bandOnly }
    }

    const wasFolded = await read($, collapsed)

    await update($, collapsed, () => !wasFolded)

    return { text: wasFolded ? words.unfolded : words.folded }
  })

  on('command.run', { command: 'deadhd-statusline' }, async $ => {
    const state = await read($, live)
    const words = WORDS[state?.lang ?? 'ko']

    if ((await viewOf($, state)) !== 'statusline') {
      return { text: words.statusOnly }
    }

    const wasFolded = await read($, collapsed)

    await update($, collapsed, () => !wasFolded)

    return { text: wasFolded ? words.statusUnfolded : words.statusFolded }
  })

  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    if ((await read($, shown)) !== 'statusline') {
      return next(e)
    }

    const state = await read($, live)

    if (state === null) {
      return next(e)
    }

    const folded = await read($, collapsed)
    const now = await $.clock.now()
    const words = WORDS[state.lang]
    // The button and the space before it are drawn beside the text, so their
    // cells come off the budget the line's own pieces are cut to. The width is
    // the surface's own, which PromptHint's props do not carry.
    const cols = e.viewport?.columns ?? STATUS_COLS
    const room = Math.max(0, cols - (1 + buttonCols(words.open)))

    if (room > 0) {
      widths.status = room
    }

    const parts = folded ? statusFoldedSegments(state) : statusLine(state, now, room)
    // The engine's hint keeps its own tree, drawn under the deadhd line.
    const hint = await next(e)
    const { Box, Text, Button } = $.ui.resolve(e)
    const open = (): void => {
      void openText($, state).then(message => $.ui.toast(message))
    }

    return (
      <Box flexDirection="column">
        <Box>
          {parts.map((part, index) => (
            <Text key={`part-${index}`} bold={part.bold === true} {...paint(part.tone)}>
              {index === parts.length - 1 ? `${part.text} ` : part.text}
            </Text>
          ))}
          <Button key="open" label={words.open} variant="primary" onPress={open} />
        </Box>
        {hint}
      </Box>
    )
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) {
      return next(e)
    }

    if ((await read($, shown)) !== 'band') {
      return next(e)
    }

    const state = await read($, live)

    if (state === null) {
      return next(e)
    }

    const { Box, Text, Button } = $.ui.resolve(e)
    const words = WORDS[state.lang]
    const open = (): void => {
      void openText($, state).then(message => $.ui.toast(message))
    }

    if (await read($, collapsed)) {
      const folded = foldedSegments(state)

      return (
        <Box>
          {folded.map((part, index) => (
            <Text key={`folded-${index}`} bold={part.bold === true} {...paint(part.tone)}>
              {index === folded.length - 1 ? `${part.text} ` : part.text}
            </Text>
          ))}
          <Button key="open" label={words.open} variant="primary" onPress={open} />
          <Button key="expand" label={words.expand} onPress={() => update($, collapsed, () => false)} />
        </Box>
      )
    }

    const now = await $.clock.now()
    const controls = buttonCols(words.open) + 1 + buttonCols(words.collapse) + 1
    const room = Math.max(0, e.props.bodyColumns - controls)

    if (room > 0) {
      widths.band = room
    }

    const line = bandLine(state, now, room)

    if (line.length === 0) {
      return next(e)
    }

    const rows = [
      <Box key="band-line">
        {line.map((part, index) => (
          <Text key={`part-${index}`} bold={part.bold === true} {...paint(part.tone)}>
            {index === line.length - 1 ? `${part.text} ` : part.text}
          </Text>
        ))}
        <Button key="open" label={words.open} variant="primary" onPress={open} />
        <Button key="collapse" label={words.collapse} onPress={() => update($, collapsed, () => true)} />
      </Box>,
    ]

    if (e.props.maxRows > 1) {
      // The second row carries no button, so the whole region is its budget.
      const alerts = bandAlertLine(state, now, e.props.bodyColumns)

      if (alerts.length > 0) {
        rows.push(
          <Box key="band-alerts">
            {alerts.map((part, index) => (
              <Text key={`alert-${index}`} bold={part.bold === true} {...paint(part.tone)}>
                {index === alerts.length - 1 ? `${part.text} ` : part.text}
              </Text>
            ))}
          </Box>,
        )
      }
    }

    return <Box flexDirection="column">{rows}</Box>
  })
}
