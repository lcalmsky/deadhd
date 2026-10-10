import type {
  CommandRunInput,
  On,
  RenderElement,
  RenderPropsOf,
  SessionStartInput,
} from 'claude-code'
import type { MockClock } from 'claude-code/testing'
import { describe, expect, mock, test } from 'claude-code/testing'

import {
  bandAlertLine,
  bandLine,
  cellWidth,
  formatLine,
  normalize,
  resolveView,
  statusLine,
} from './register'

const PLUGIN = 'deadhd'
const SESSION_ID = 'ed57a32e-b6cc-48e6-aca1-4d4bf18f60fc'
const STATE_PATH = `/tmp/deadhd-state/${SESSION_ID}.json`
const DATA_PATH = '/tmp/deadhd-cas-1161-r3.json'
const OUT_PATH = '/tmp/deadhd-cas-1161-r3.html'
const HOME = '/Users/tester'
const CONFIG_PATH = `${HOME}/.config/deadhd/config.json`

const SESSION: SessionStartInput = { cwd: '/work', surface: 'terminal', isInteractive: true }

/** Four minutes after the sample's current step started, and two after its last write. */
const NOW = Date.parse('2026-10-09T15:38:53+09:00')

const BAND: RenderPropsOf['AbovePrompt'] = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 20,
  bodyColumns: 100,
  scroll: { offset: 0, bodyRows: 19 },
  view: {},
}

/** The props the engine hands the PromptHint hook; the line itself comes from `next(e)`. */
const HINT: RenderPropsOf['PromptHint'] = {
  isDraft: false,
  isWorking: false,
  hint: '? for shortcuts',
}

/** The tree the engine draws under the deadhd line, as `next(e)` resolves to it. */
const ENGINE_HINT: RenderElement = { type: 'Text', children: ['? for shortcuts'] }

/** One state file, as the skill's state.py and render.py write it. */
const SAMPLE = {
  sessionId: SESSION_ID,
  view: 'band',
  data: DATA_PATH,
  out: OUT_PATH,
  status: 'working',
  since: '2026-10-09T15:34:53+09:00',
  message: null,
  lastTool: null,
  backgroundTasks: [
    { type: 'bash', description: 'watch' },
    { type: 'bash', description: 'build' },
  ],
  compactions: { count: 1, lastAt: '2026-10-09T15:00:00+09:00' },
  summary: {
    title: 'CAS-1161 콘솔 dev 회귀 3회차',
    key: 'CAS-1161',
    keyHref: 'https://example.atlassian.net/browse/CAS-1161',
    lang: 'ko',
    updated: '2026-10-09 15:35 KST',
    counts: { done: 3, now: 1, side: 0, left: 2, blocked: 1 },
    total: 6,
    nowLabel: '실제 화면 확인',
    pr: { text: 'app-api#512', href: 'https://github.com/example/app-api/pull/512' },
    eta: '2026-10-09T16:20:00+09:00' as string | null,
    // render.py 는 보정할 표본이 모자라면 이 키를 null 로 싣는다.
    etaCalibrated: null as string | null,
    allDone: false,
    // SKILL.md 가 데이터 JSON 을 마지막으로 쓴 시각. 「N분 전」 의 기준이다.
    dataAt: '2026-10-09T15:36:53+09:00',
  },
  updatedAt: '2026-10-09T15:36:53+09:00',
}

/** The data file the state file points at, as the skill's render.py reads it. */
const BOARD = {
  key: 'CAS-1161',
  title: 'CAS-1161 콘솔 dev 회귀 3회차',
  lanes: ['준비', '배포'],
  items: [
    { id: 'a', lane: 0, col: 0, label: '준비', sub: '완료', state: 'done' },
    { id: 'b', lane: 0, col: 1, label: 'setup 통합', state: 'left' },
    {
      id: 'c',
      lane: 1,
      col: 0,
      label: '실제 화면 확인',
      sub: '진행',
      state: 'now',
      startedAt: '2026-10-09T15:34:53+09:00',
    },
    { id: 'd', lane: 1, col: 1, label: '배포 검증', sub: '권한 대기', state: 'blocked' },
    { id: 'e', lane: 1, col: 2, label: '정리', state: 'left' },
    { id: 'f', lane: 1, col: 3, label: '보고', sub: '완료', state: 'done' },
  ],
}

const STATE = normalize(SAMPLE, BOARD)

/** The sample with a state-file field or a summary field put where a test wants it. */
const stateOf = (
  patch: Partial<typeof SAMPLE> = {},
  summary: Partial<typeof SAMPLE.summary> = {},
): typeof SAMPLE => ({ ...SAMPLE, ...patch, summary: { ...SAMPLE.summary, ...summary } })

/** The sample's state file with the view the status line's tests draw in. */
const statusState = (
  patch: Partial<typeof SAMPLE> = {},
  summary: Partial<typeof SAMPLE.summary> = {},
): typeof SAMPLE => stateOf({ view: 'statusline', ...patch }, summary)

/** Every file the two reads reach, as the session's directory holds them. */
const filesOf = (
  state: unknown = SAMPLE,
  board: unknown = BOARD,
): Record<string, string> => ({
  [STATE_PATH]: JSON.stringify(state),
  [DATA_PATH]: JSON.stringify(board),
})

/** One `/deadhd-open` run, as the engine raises it. */
const open: CommandRunInput = {
  command: 'deadhd-open',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: false, columns: 100 },
}

/** One `/deadhd-band` run, as the engine raises it. */
const run: CommandRunInput = { ...open, command: 'deadhd-band' }

/** One `/deadhd-statusline` run, as the engine raises it. */
const statusRun: CommandRunInput = { ...open, command: 'deadhd-statusline' }

/** One command's answer, as the engine returns it. */
const result = { exitCode: 0, stderr: '' }

/**
 * The world beneath the plugin, in memory: the files the skill wrote, the
 * engine's own answers, and what the plugin asked the host to do.
 *
 * `skillInRoot` puts render.py at the plugin root rather than under it, which
 * is the skill-folder install; otherwise the skill is `${root}/skills/deadhd`.
 */
function worldOf(
  on: On,
  files: Readonly<Record<string, string>>,
  now = NOW,
  skillInRoot = false,
): {
  clock: MockClock
  registered: string[]
  toasts: string[]
  runs: string[][]
  invalidates: string[]
  stats: string[]
  renderer: { exitCode: number; stdout: string; stderr: string }
  opener: { exitCode: number; stdout: string; stderr: string }
} {
  const clock = mock.clock(on, { now })
  const registered: string[] = []
  const toasts: string[] = []
  const runs: string[][] = []
  const invalidates: string[] = []
  const stats: string[] = []
  const renderer = { exitCode: 0, stdout: '', stderr: '' }
  const opener = { exitCode: 0, stdout: `opened: browser ${OUT_PATH}`, stderr: '' }

  mock.env(on, { HOME })

  on('fs.read', ($, e) => {
    const body = files[e.path]

    return body === undefined ? { deny: `ENOENT: ${e.path}` } : { value: body }
  })
  on('fs.stat', ($, e) => {
    stats.push(e.path)

    return skillInRoot && e.path.endsWith('/render.py')
      ? { value: { kind: 'file' as const, size: 0, mtimeMs: 0, isLink: false } }
      : { deny: `ENOENT: ${e.path}` }
  })
  on('session.id', () => ({ value: SESSION_ID }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('ui.toast', ($, e) => {
    toasts.push(e.text)

    return { value: undefined }
  })
  on('ui.invalidate', ($, e) => {
    invalidates.push(e.event)

    return { value: undefined }
  })
  on('command.register', ($, e) => {
    registered.push(e.name)

    return { value: { command: e.name } }
  })
  on('process.run', ($, e) => {
    runs.push([...e.argv])

    const which = e.argv.some(arg => String(arg).endsWith('render.py')) ? renderer : opener

    return {
      value: {
        exitCode: which.exitCode,
        stdout: which.stdout,
        stderr: which.stderr,
        isStdoutTruncated: false,
        isStderrTruncated: false,
      },
    }
  })

  return { clock, registered, toasts, runs, invalidates, stats, renderer, opener }
}

/** The status line's world: the files, the pinned-status answer and the engine's hint tree. */
const statusWorld = (
  on: On,
  files: Readonly<Record<string, string>>,
  hint: RenderElement = ENGINE_HINT,
  now = NOW,
): ReturnType<typeof worldOf> => {
  const world = worldOf(on, files, now)

  pinsNothing(on)
  on('ui.render', () => hint)

  return world
}

/** Every string a drawn tree holds, in drawing order, a Button's label included. */
const textOf = (node: unknown): string => {
  if (typeof node === 'string') {
    return node
  }

  if (node === null || typeof node !== 'object') {
    return ''
  }

  const element = node as { type?: string; props?: Record<string, unknown>; children?: unknown[] }
  const own = element.type === 'Button' && typeof element.props?.label === 'string' ? element.props.label : ''

  return own + (element.children ?? []).map(textOf).join('')
}

/** A drawn tree as plain data: its own props and the children it holds. */
const elementOf = (node: unknown): { type?: string; props?: Record<string, unknown>; children?: unknown[] } =>
  node as { type?: string; props?: Record<string, unknown>; children?: unknown[] }

/** The rows a drawn tree holds, the outermost Box's children in order. */
const rowsOf = (drawn: unknown): unknown[] => elementOf(drawn).children ?? []

/** One Text of a drawn line, as the colors and the dim flag under test read it. */
type Painted = { text: string; color: unknown; bold: unknown; dim: unknown }

const paintedOf = async (ui: {
  findAll: (query: { type: string }) => Promise<readonly { text: string; props: Record<string, unknown> }[]>
}): Promise<Painted[]> =>
  (await ui.findAll({ type: 'Text' })).map(one => ({
    text: one.text,
    color: one.props.color,
    bold: one.props.bold,
    dim: one.props.dimColor,
  }))

/** The piece whose words are `text`; a trailing space before the button is not part of it. */
const pieceOf = (painted: readonly Painted[], text: string): Painted | undefined =>
  painted.find(one => one.text.trim() === text)

/** Answers the pinned-status call a statusline start makes, drawing nothing. */
const pinsNothing = (on: On): void => {
  on('ui.status', () => ({ value: undefined }))
}

const line = (parts: readonly { text: string }[]): string => parts.map(part => part.text).join('')

/** The piece of a drawn line whose words are `text`, the trailing space aside. */
const pieceIn = (
  parts: readonly { text: string; tone: string }[],
  text: string,
): { text: string; tone: string } | undefined => parts.find(part => part.text.trim() === text)

const MOUNT = { plugin: PLUGIN, component: 'AbovePrompt', props: BAND } as const
const MOUNT_HINT = { plugin: PLUGIN, component: 'PromptHint', props: HINT } as const

/** The mark both lines lead with, from the piece a test reads. */
const STATUS_MARK = '◆'

/** The pull request the sample's running step carries, as the row draws it. */
const PR_PIECE = '🔀 app-api#512'

/** The pull request's own words: the part the link wraps, the mark left outside it. */
const PR_TEXT = 'app-api#512'

/** The mark and the count as one piece: no separator falls between them. */
const MARK_COUNT = `${STATUS_MARK} ✓ 3/6`

/** The whole long row the sample draws, piece by piece. */
const LONG_ROW =
  `${STATUS_MARK} ✓ 3/6 ▓▓▓░░░ · CAS-1161 콘솔 dev 회귀 3회차 · ` +
  '▶ 실제 화면 확인 4분째 · 🔀 app-api#512 · ⏭ 다음 정리 · ⏱ 예상 16:20 · 🔄 2분 전 · ' +
  '⛔ 막힘 1: 배포 검증 · ⏳ 남음 2 · 🧵 백그라운드 2 · 🗜 압축 1'

/** What the engine draws when the plugin leaves the component to it. */
const ENGINE_OWN: RenderElement = { type: 'Text', children: ['(the engine drew its own)'] }

describe('the band', () => {
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`draws the short line from the session's files, on the ${surface}`, async ($, on) => {
      worldOf(on, filesOf())

      await $.session.start(SESSION)

      const ui = await $.ui.mount({ ...MOUNT, surface })
      const drawn = textOf(await ui.drawn())

      expect(drawn).toContain(STATUS_MARK)
      expect(drawn).toContain('▓▓▓░░░ 3/6')
      expect(drawn).toContain('▶ 실제 화면 확인 4분째')
      expect(drawn).toContain('막힘 1')
      expect(drawn).toContain('남음 2')
      expect(drawn).toContain('열기')
      expect(drawn).toContain('접기')
      expect(drawn).not.toContain('CAS-1161')

      await ui.unmount()
    })
  }

  test('with no state file the engine keeps the band it draws', async ($, on) => {
    worldOf(on, {})
    on('ui.render', () => ENGINE_OWN)

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await ui.drawn())).toBe('(the engine drew its own)')

    await ui.unmount()
  })

  test('a survey on the band is left to the engine', async ($, on) => {
    worldOf(on, filesOf())
    on('ui.render', () => ({ type: 'Text', children: ['(a survey)'] }))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({
      ...MOUNT,
      surface: 'terminal',
      props: { ...BAND, hasSurvey: true },
    })

    expect(textOf(await ui.drawn())).toBe('(a survey)')

    await ui.unmount()
  })

  test('adds a second row when a step is stuck and the session waits', async ($, on) => {
    const waiting = stateOf({ status: 'waiting_permission' })

    worldOf(on, filesOf(waiting))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
    const drawn = textOf(await ui.drawn())

    expect(drawn).toContain('⛔ 막힘: 배포 검증 (권한 대기)')
    expect(drawn).toContain('🔐 권한 승인 대기 4분째')
    expect(drawn).toContain('접기')

    await ui.unmount()
  })

  test('keeps to one row while nothing needs attention', async ($, on) => {
    const clean = stateOf({}, { counts: { done: 4, now: 1, side: 0, left: 1, blocked: 0 } })

    worldOf(on, filesOf(clean, { items: BOARD.items.filter(item => item.state !== 'blocked') }))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
    const drawn = textOf(await ui.drawn())

    expect(drawn).toContain('남음 1')
    expect(drawn).not.toContain('막힘')
    expect(drawn).not.toContain('막힘:')

    await ui.unmount()
  })

  test('drops the second row when the band has room for one', async ($, on) => {
    worldOf(on, filesOf(stateOf({ status: 'waiting_permission' })))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({
      ...MOUNT,
      surface: 'terminal',
      props: { ...BAND, maxRows: 1 },
    })
    const drawn = textOf(await ui.drawn())

    expect(drawn).toContain('막힘 1')
    expect(drawn).not.toContain('막힘:')
    expect(drawn).not.toContain('권한 승인 대기')

    await ui.unmount()
  })

  test('gives the alert row the whole region, since it carries no button', async ($, on) => {
    const waiting = stateOf({ status: 'waiting_permission' })

    worldOf(on, filesOf(waiting))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({
      ...MOUNT,
      surface: 'terminal',
      props: { ...BAND, bodyColumns: 60 },
    })
    const rows = rowsOf(await ui.drawn())
    const alerts = line(bandAlertLine(normalize(waiting, BOARD), NOW, 60))

    // 1줄째는 버튼 두 개의 폭(18칸)을 뺀 42칸이지만, 2줄째는 60칸을 다 쓴다.
    expect(cellWidth(line(bandAlertLine(normalize(waiting, BOARD), NOW, 42)))).toBeLessThan(
      cellWidth(alerts),
    )
    expect(textOf(rows[1])).toBe(`${alerts} `)

    await ui.unmount()
  })

  test('folds to one line and opens again from it', async ($, on) => {
    worldOf(on, filesOf())

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await ui.drawn())).toContain('접기')

    await ui.press({ key: 'collapse' })
    await ui.unmount()

    const folded = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
    const summary = textOf(await folded.drawn())

    expect(summary).toContain(`${STATUS_MARK} ✓ 3/6`)
    expect(summary).not.toContain('/deadhd-band')
    expect(summary).toContain('열기')
    expect(summary).toContain('펼치기')
    expect(summary).not.toContain('막힘')

    await folded.press({ key: 'expand' })
    await folded.unmount()

    const opened = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await opened.drawn())).toContain('막힘 1')

    await opened.unmount()
  })

  test('opens again when a step gets stuck while it is folded', async ($, on) => {
    const files = filesOf()

    const { clock } = worldOf(on, files)

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    await ui.press({ key: 'collapse' })
    await ui.unmount()

    files[STATE_PATH] = JSON.stringify(
      stateOf({}, { counts: { ...SAMPLE.summary.counts, blocked: 2 } }),
    )

    await clock.advance(5000)

    const after = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
    const drawn = textOf(await after.drawn())

    expect(drawn).toContain('막힘 2')
    expect(drawn).toContain('접기')

    await after.unmount()
  })

  test('stays folded as the turns end', async ($, on) => {
    const files = filesOf()

    const { clock } = worldOf(on, files)

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    await ui.press({ key: 'collapse' })
    await ui.unmount()

    // 턴이 끝나면 상태가 idle 로 돌아온다. 접기를 풀 만한 변화는 아니다.
    files[STATE_PATH] = JSON.stringify(stateOf({ status: 'idle' }))

    await clock.advance(15000)

    const after = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
    const drawn = textOf(await after.drawn())

    expect(drawn).toContain(`${STATUS_MARK} ✓ 3/6`)
    expect(drawn).toContain('펼치기')
    expect(drawn).not.toContain('막힘')

    await after.unmount()
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    test(`paints each piece with its theme key, on the ${surface}`, async ($, on) => {
      worldOf(on, filesOf())

      await $.session.start(SESSION)

      const ui = await $.ui.mount({ ...MOUNT, surface })
      const painted = await paintedOf(ui)
      const separators = painted.filter(one => one.text.includes('·'))

      expect(pieceOf(painted, STATUS_MARK)).toMatchObject({ color: 'claude', bold: true })
      expect(pieceOf(painted, '▓▓▓')?.color).toBe('success')
      expect(pieceOf(painted, '░░░')?.color).toBe('subtle')
      expect(pieceOf(painted, '3/6')).toMatchObject({ color: 'success', bold: true })
      expect(pieceOf(painted, '▶ 실제 화면 확인 4분째')).toMatchObject({
        color: 'suggestion',
        bold: true,
      })
      expect(pieceOf(painted, '막힘 1')).toMatchObject({ color: 'error', bold: true })
      expect(pieceOf(painted, '남음 2')?.color).toBe('text')
      expect(separators.length).toBeGreaterThan(0)
      expect(separators.every(one => one.color === 'subtle')).toBe(true)

      await ui.unmount()
    })
  }

  test('paints the stuck step and the wait on the second row', async ($, on) => {
    worldOf(on, filesOf(stateOf({ status: 'idle' })))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })
    const painted = await paintedOf(ui)

    expect(pieceOf(painted, '⛔ 막힘:')).toMatchObject({ color: 'error', bold: true })
    expect(pieceOf(painted, '배포 검증 (권한 대기)')).toMatchObject({ color: 'error', bold: true })
    expect(pieceOf(painted, '⌨️ 입력 대기 4분째')).toMatchObject({ color: 'merged', bold: true })

    await ui.unmount()
  })

  test('ends with 완료 once every step is done', async ($, on) => {
    const ended = stateOf(
      {},
      {
        allDone: true,
        counts: { done: 6, now: 0, side: 0, left: 0, blocked: 0 },
      },
    )

    const done = BOARD.items.map(item => ({ ...item, state: 'done' }))

    worldOf(on, filesOf(ended, { ...BOARD, items: done }))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await ui.drawn())).toContain('완료')

    await ui.unmount()
  })
})

describe('the band line', () => {
  test('carries the progress, the current step and the counts', () => {
    expect(line(bandLine(STATE, NOW, 200))).toBe(
      `${STATUS_MARK} · ▓▓▓░░░ 3/6 · ▶ 실제 화면 확인 4분째 · 막힘 1 · 남음 2`,
    )
  })

  test('leads with the mark the status line leads with, not the command name', () => {
    const drawn = line(bandLine(STATE, NOW, 200))

    expect(drawn.startsWith(`${STATUS_MARK} ·`)).toBe(true)
    expect(drawn).not.toContain('/deadhd-band')
  })

  test('marks work running in parallel with its own glyph and color', () => {
    const parallel = normalize(
      stateOf({}, { counts: { done: 0, now: 0, side: 1, left: 0, blocked: 0 } }),
      { items: [{ label: '병렬 작업', state: 'side', lane: 0, col: 0 }] },
    )
    const parts = bandLine(parallel, NOW, 200)

    expect(line(parts)).toContain('◐ 병렬 작업')
    expect(parts.find(part => part.text.includes('◐'))?.tone).toBe('autoAccept')
  })

  test('leaves out what the session does not have', () => {
    const bare = normalize({ status: 'working', summary: { title: '', lang: 'ko', total: 1, counts: { done: 1 } } })

    expect(line(bandLine(bare, NOW, 200))).toBe(`${STATUS_MARK} · ▓▓▓▓▓▓ 1/1`)
  })

  test('cuts the current step so the row fits', () => {
    const long = {
      ...STATE!,
      current: { ...STATE!.current!, label: '아주 긴 단계 이름이 여기에 들어 있다' },
    }
    const drawn = line(bandLine(long, NOW, 60))

    expect(cellWidth(drawn)).toBeLessThanOrEqual(60)
    expect(drawn).toContain('…')
    expect(drawn).toContain('3/6')
    expect(drawn).toContain('남음 2')
  })

  test('drops the current step when not even one column of it fits', () => {
    const long = {
      ...STATE!,
      current: { ...STATE!.current!, label: '아주 긴 단계 이름이 여기에 들어 있다' },
    }

    // Past the step, the left count is the next piece the band's row spares.
    // The mark leaves the row's other pieces 31 cells before not one of the
    // step's own is left.
    expect(line(bandLine(long, NOW, 31))).toBe(`${STATUS_MARK} · ▓▓▓░░░ 3/6 · 막힘 1`)
  })

  test('fits the row in 60 and 40 cells, as the status line does', () => {
    const long = {
      ...STATE!,
      current: { ...STATE!.current!, label: '아주 긴 단계 이름이 여기에 들어 있다' },
    }

    for (const maxCols of [60, 40]) {
      expect(cellWidth(line(bandLine(long, NOW, maxCols)))).toBeLessThanOrEqual(maxCols)
    }
  })
})

describe('the band alerts', () => {
  test('names the stuck step, then the wait', () => {
    const waiting = { ...STATE!, status: 'waiting_permission' }

    expect(line(bandAlertLine(waiting, NOW, 200))).toBe(
      '⛔ 막힘: 배포 검증 (권한 대기) · 🔐 권한 승인 대기 4분째',
    )
  })

  test('is empty while the session works and no step is stuck', () => {
    const clean = { ...STATE!, blocked: 0, stuck: null }

    expect(bandAlertLine(clean, NOW, 200)).toEqual([])
  })
})

describe('the status hint', () => {
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`draws the long row and the engine hint as two rows, on the ${surface}`, async ($, on) => {
      statusWorld(on, filesOf(statusState()))

      await $.session.start(SESSION)

      const ui = await $.ui.mount({ ...MOUNT_HINT, surface })
      const drawn = await ui.drawn()
      const rows = rowsOf(drawn)

      expect(elementOf(drawn).props?.flexDirection).toBe('column')
      expect(rows).toHaveLength(2)
      // 버튼 두 개는 줄 뒤에 나란히 붙는다.
      expect(textOf(rows[0])).toBe(`${LONG_ROW} 열기접기`)
      expect(rows[1]).toEqual(ENGINE_HINT)

      await ui.unmount()
    })

    test(`links the key and the pull request, on the ${surface}`, async ($, on) => {
      statusWorld(on, filesOf(statusState()))

      await $.session.start(SESSION)

      const ui = await $.ui.mount({ ...MOUNT_HINT, surface })
      const links = await ui.findAll({ type: 'Link' })
      const drawn = textOf(await ui.drawn())

      expect(links.map(one => one.props.href)).toEqual([
        'https://example.atlassian.net/browse/CAS-1161',
        'https://github.com/example/app-api/pull/512',
      ])
      expect(textOf(links[0])).toBe('CAS-1161')
      expect(textOf(links[1])).toBe(PR_TEXT)
      expect(drawn).toContain(PR_PIECE)
      expect(drawn).toContain('열기')

      await ui.unmount()
    })
  }

  test('links the key and the pull request words alone, their neighbours left outside', async ($, on) => {
    statusWorld(on, filesOf(statusState({}, { title: '다른 제목' })))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const links = await ui.findAll({ type: 'Link' })

    expect(textOf(links[0])).toBe('CAS-1161')
    expect(textOf(links[1])).toBe(PR_TEXT)

    await ui.unmount()
  })

  test('keeps the buttons and the count on the folded row, naming no command', async ($, on) => {
    statusWorld(on, filesOf(statusState()))

    await $.session.start(SESSION)
    await $.command.run(statusRun)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const drawn = textOf(await ui.drawn())

    expect(drawn).toContain(`${STATUS_MARK} ✓ 3/6`)
    // 접힌 줄은 명령 이름 대신 버튼 두 개로 되돌아가는 길을 알린다.
    expect(drawn).toContain('열기')
    expect(drawn).toContain('펼치기')
    expect(drawn).not.toContain('/deadhd-statusline')
    expect(drawn).not.toContain('⏳ 남음 2')

    await ui.unmount()
  })

  test('opens the page from the hint button, in the same two steps as the band', async ($, on) => {
    const { toasts, runs } = statusWorld(on, filesOf(statusState()))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })

    await ui.press({ key: 'open' })
    await ui.unmount()

    expect(runs).toHaveLength(2)
    expect(runs[0]?.slice(0, 1)).toEqual(['python3'])
    expect(runs[0]?.[1]?.endsWith('/render.py')).toBe(true)
    expect(runs[0]?.slice(2)).toEqual(['--page', '--session', SESSION_ID, DATA_PATH, OUT_PATH])
    expect(runs[1]?.[0]).toBe('bash')
    expect(runs[1]?.[1]?.endsWith('/open.sh')).toBe(true)
    expect(runs[1]?.[2]).toBe(OUT_PATH)
    expect(toasts).toEqual(['HTML 페이지를 열었어요'])
  })

  test('leaves the engine hint its own tree and color', async ($, on) => {
    const hint: RenderElement = { type: 'Text', props: { color: 'warning' }, children: ['esc to interrupt'] }

    statusWorld(on, filesOf(statusState()), hint)

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const painted = await paintedOf(ui)

    expect(pieceOf(painted, 'esc to interrupt')?.color).toBe('warning')

    await ui.unmount()
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    test(`paints each piece with its theme key, on the ${surface}`, async ($, on) => {
      statusWorld(on, filesOf(statusState()))

      await $.session.start(SESSION)

      const ui = await $.ui.mount({ ...MOUNT_HINT, surface })
      const painted = await paintedOf(ui)
      const separators = painted.filter(one => one.text.includes('·'))

      expect(pieceOf(painted, STATUS_MARK)).toMatchObject({ color: 'claude', bold: true })
      expect(pieceOf(painted, '✓ 3/6')).toMatchObject({ color: 'success', bold: true })
      expect(pieceOf(painted, '▓▓▓')?.color).toBe('success')
      expect(pieceOf(painted, '░░░')?.color).toBe('subtle')
      expect(pieceOf(painted, 'CAS-1161')).toMatchObject({ color: 'permission', bold: true })
      expect(pieceOf(painted, '콘솔 dev 회귀 3회차')?.color).toBe('text')
      expect(pieceOf(painted, '▶ 실제 화면 확인 4분째')).toMatchObject({
        color: 'suggestion',
        bold: true,
      })
      expect(pieceOf(painted, '🔀')).toMatchObject({ color: 'permission' })
      expect(pieceOf(painted, PR_TEXT)).toMatchObject({ color: 'permission' })
      expect(pieceOf(painted, '⏭ 다음 정리')?.color).toBe('inactive')
      expect(pieceOf(painted, '⏱ 예상 16:20')?.color).toBe('planMode')
      expect(pieceOf(painted, '🔄 2분 전')?.color).toBe('subtle')
      expect(pieceOf(painted, '⛔ 막힘 1')).toMatchObject({ color: 'error', bold: true })
      expect(pieceOf(painted, ': 배포 검증')).toMatchObject({ color: 'error', bold: true })
      expect(pieceOf(painted, '⏳ 남음 2')?.color).toBe('text')
      expect(pieceOf(painted, '🧵 백그라운드 2')?.color).toBe('ide')
      expect(pieceOf(painted, '🗜 압축 1')?.color).toBe('remember')
      expect(separators.length).toBeGreaterThan(0)
      expect(separators.every(one => one.color === 'subtle')).toBe(true)

      await ui.unmount()
    })
  }

  test('falls quiet, warns, then stops, as the last write falls behind', async ($, on) => {
    const written = (minutes: number): typeof SAMPLE =>
      statusState({}, { dataAt: new Date(NOW - minutes * 60000).toISOString() })

    statusWorld(on, filesOf(written(11)))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const painted = await paintedOf(ui)

    expect(pieceOf(painted, '⚠️ 11분 전')?.color).toBe('warning')

    await ui.unmount()
  })

  test('keeps the row whole under a long engine hint', async ($, on) => {
    statusWorld(on, filesOf(statusState()), { type: 'Text', children: ['x'.repeat(200)] })

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const rows = rowsOf(await ui.drawn())
    const painted = await paintedOf(ui)

    expect(textOf(rows[0])).toBe(`${LONG_ROW} 열기접기`)
    expect(textOf(rows[1])).toBe('x'.repeat(200))
    expect(pieceOf(painted, '⏳ 남음 2')).toBeDefined()

    await ui.unmount()
  })

  test('cuts the long row to its budget', async ($, on) => {
    const long = statusState({}, { title: '아주 긴 제목이 여기에 들어 있다 '.repeat(12) })

    statusWorld(on, filesOf(long))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const rows = rowsOf(await ui.drawn())
    const painted = await paintedOf(ui)

    expect(cellWidth(textOf(rows[0]))).toBeLessThanOrEqual(240)
    expect(textOf(rows[0])).toContain('…')
    expect(pieceOf(painted, '⏳ 남음 2')).toBeDefined()
    // The button is drawn outside the budget, so the row keeps it however tight it gets.
    expect(textOf(rows[0])).toContain('열기')

    await ui.unmount()
  })

  test('cuts the long row to the width the surface measured', async ($, on) => {
    const long = statusState({}, { title: '아주 긴 제목이 여기에 들어 있다 '.repeat(12) })

    statusWorld(on, filesOf(long))

    await $.session.start(SESSION)

    const narrow = await $.ui.mount({
      ...MOUNT_HINT,
      surface: 'terminal',
      viewport: { columns: 120, rows: 24 },
    })
    const cut = textOf(rowsOf(await narrow.drawn())[0])

    await narrow.unmount()

    const wide = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const whole = textOf(rowsOf(await wide.drawn())[0])

    await wide.unmount()

    // PromptHint hands the tree no width of its own, so the viewport's cells are
    // the budget: the narrow surface gives way where a 240-cell one keeps the pieces.
    expect(whole).toContain('▶ 실제 화면 확인')
    expect(whole).toContain(PR_PIECE)
    expect(cut).not.toContain('▶ 실제 화면 확인')
    expect(cut).not.toContain('🗜 압축 1')
    expect(cut).toContain(PR_PIECE)
    expect(cut).toContain('⏳ 남음 2')
    expect(cut).toContain('✓ 3/6')
    expect(cellWidth(cut)).toBeLessThan(cellWidth(whole))
    // The hint line is drawn indented, so of the screen's 120 cells the four of
    // indent and the two buttons with the space before each are not the line's
    // to draw in. What the drawing adds beside the line (a space and the two
    // buttons) is not its either.
    expect(cellWidth(formatLine(normalize(long, BOARD), NOW, 98))).toBeLessThanOrEqual(98)
    expect(cellWidth(cut)).toBeLessThan(cellWidth(whole))
  })

  test('keeps the line and its two buttons inside the viewport', async ($, on) => {
    const long = statusState({}, { title: '아주 긴 제목이 여기에 들어 있다 '.repeat(12) })

    statusWorld(on, filesOf(long))

    await $.session.start(SESSION)

    const ui = await $.ui.mount({
      ...MOUNT_HINT,
      surface: 'terminal',
      viewport: { columns: 120, rows: 24 },
    })
    const row = textOf(rowsOf(await ui.drawn())[0])

    // 120칸에서 들여쓰기 4칸과 버튼 두 개(각 8칸)와 그 앞 여백을 뺀 98칸이 줄의 몫이다.
    expect(cellWidth(row.replace(/열기접기$/, '').trimEnd())).toBeLessThanOrEqual(98)
    // 줄에 붙은 여백과 버튼 글자까지 더해도 화면 안에 남는다.
    expect(cellWidth(row)).toBeLessThanOrEqual(107)

    await ui.unmount()
  })

  test('with no state file the engine keeps its own hint', async ($, on) => {
    worldOf(on, {})
    pinsNothing(on)
    on('ui.render', () => ENGINE_OWN)

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })

    expect(textOf(await ui.drawn())).toBe('(the engine drew its own)')

    await ui.unmount()
  })

  test('clears the pinned line once and never draws a status text', async ($, on) => {
    const statuses: (string | undefined)[] = []

    const { clock } = worldOf(on, filesOf(statusState()))
    on('ui.status', ($, e) => {
      statuses.push(e.text)

      return { value: undefined }
    })

    await $.session.start(SESSION)
    await clock.advance(5000)
    await $.command.run(open)

    expect(statuses).toEqual([undefined])
  })
})

describe('the status line command', () => {
  test('folds and unfolds from the buttons beside it, as the command does', async ($, on) => {
    statusWorld(on, filesOf(statusState()))

    await $.session.start(SESSION)

    const long = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const open = textOf(await long.drawn())

    expect(open).toContain(`${LONG_ROW} 열기접기`)
    expect(open).not.toContain('펼치기')

    await long.press({ key: 'collapse' })
    await long.unmount()

    const folded = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const shut = textOf(await folded.drawn())

    expect(shut).toContain(`${STATUS_MARK} ✓ 3/6 열기펼치기`)
    expect(shut).not.toContain('접기')

    await folded.press({ key: 'expand' })
    await folded.unmount()

    const opened = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })

    expect(textOf(await opened.drawn())).toContain('⏳ 남음 2')
    // 버튼이 바꾸는 것은 /deadhd-statusline 이 토글하는 것과 같은 접힘 상태다.
    expect((await $.command.run(statusRun)).text).toBe('상태줄을 접었어요')

    await opened.unmount()
  })

  test('folds and opens the line, answering each time', async ($, on) => {
    statusWorld(on, filesOf(statusState()))

    await $.session.start(SESSION)

    expect((await $.command.run(statusRun)).text).toBe('상태줄을 접었어요')

    const folded = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })
    const drawn = textOf(await folded.drawn())

    expect(drawn).toContain(`${STATUS_MARK} ✓ 3/6`)
    expect(drawn).not.toContain('⏳ 남음 2')
    // The engine's own hint stays under the line whether or not it is folded.
    expect(drawn).toContain('? for shortcuts')

    await folded.unmount()

    expect((await $.command.run(statusRun)).text).toBe('상태줄을 펼쳤어요')
  })

  test('opens again when a step gets stuck while it is folded', async ($, on) => {
    const files = filesOf(statusState())

    const { clock } = statusWorld(on, files)

    await $.session.start(SESSION)
    await $.command.run(statusRun)

    const folded = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })

    expect(textOf(await folded.drawn())).toContain(`${STATUS_MARK} ✓ 3/6`)

    await folded.unmount()

    files[STATE_PATH] = JSON.stringify(
      statusState({}, { counts: { ...SAMPLE.summary.counts, blocked: 2 } }),
    )

    await clock.advance(5000)

    const after = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })

    expect(textOf(await after.drawn())).toContain('⛔ 막힘 2')

    await after.unmount()
  })

  test('is declared while the status line draws', async ($, on) => {
    const { registered } = statusWorld(on, filesOf(statusState()))

    await $.session.start(SESSION)

    expect(registered).toEqual(['deadhd-band', 'deadhd-statusline', 'deadhd-open'])
  })

  test('tells the person to switch views when the view is not the status line', async ($, on) => {
    worldOf(on, filesOf())

    await $.session.start(SESSION)

    expect((await $.command.run(statusRun)).text).toBe(
      '지금은 상태줄 모드가 아니에요. /deadhd setup 에서 상태줄을 고르면 보여요.',
    )
  })
})

describe('the view', () => {
  test('resolves the state file first, then the config, then html', () => {
    expect(resolveView('statusline', 'band')).toBe('statusline')
    expect(resolveView(null, 'statusline')).toBe('statusline')
    expect(resolveView(null, null)).toBe('html')
    expect(resolveView('html', 'band')).toBe('html')
    expect(resolveView('paper', 'band')).toBe('band')
  })

  test('draws nothing for a session with no view anywhere', async ($, on) => {
    worldOf(on, filesOf(stateOf({ view: undefined })))
    pinsNothing(on)
    on('ui.render', () => ENGINE_OWN)

    await $.session.start(SESSION)

    const band = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await band.drawn())).toBe('(the engine drew its own)')

    await band.unmount()
  })

  test('takes the config file when the state file names no view', async ($, on) => {
    worldOf(on, {
      ...filesOf(stateOf({ view: undefined })),
      [CONFIG_PATH]: JSON.stringify({ view: 'band' }),
    })

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await ui.drawn())).toContain(STATUS_MARK)

    await ui.unmount()
  })

  test('lets the state file beat the config file', async ($, on) => {
    statusWorld(on, {
      ...filesOf(statusState()),
      [CONFIG_PATH]: JSON.stringify({ view: 'band' }),
    })

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })

    expect(textOf(await ui.drawn())).toContain(STATUS_MARK)

    await ui.unmount()
  })

  test('draws nothing in the html view', async ($, on) => {
    worldOf(on, filesOf(stateOf({ view: 'html' })))
    pinsNothing(on)
    on('ui.render', () => ENGINE_OWN)

    await $.session.start(SESSION)

    const band = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await band.drawn())).toBe('(the engine drew its own)')

    await band.unmount()

    const hint = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })

    expect(textOf(await hint.drawn())).toBe('(the engine drew its own)')

    await hint.unmount()
  })

  test('follows a change of view without a restart', async ($, on) => {
    const files = filesOf()

    const { clock } = statusWorld(on, files)

    await $.session.start(SESSION)

    const band = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await band.drawn())).toContain(STATUS_MARK)

    await band.unmount()

    files[STATE_PATH] = JSON.stringify(statusState())

    await clock.advance(5000)

    const hint = await $.ui.mount({ ...MOUNT_HINT, surface: 'terminal' })

    expect(textOf(await hint.drawn())).toContain(STATUS_MARK)

    await hint.unmount()
  })
})

describe('formatLine', () => {
  test('draws the long row in order', () => {
    expect(formatLine(STATE, NOW, 240)).toBe(LONG_ROW)
  })

  test('leaves out the pieces the session does not have', () => {
    const bare = normalize({
      status: 'working',
      summary: { title: '작은 판', lang: 'ko', total: 1, counts: { done: 1 } },
    })

    expect(formatLine(bare, NOW, 240)).toBe(`${STATUS_MARK} ✓ 1/1 ▓▓▓▓▓▓ · 작은 판`)
  })

  test('draws the mark against the count, no separator between them', () => {
    const row = formatLine(STATE, NOW, 240)

    expect(row.startsWith(MARK_COUNT)).toBe(true)
    expect(row).not.toContain(`${STATUS_MARK} ·`)
    // The bar's own cells go without the mark going with them: the mark is the
    // count's first piece, not a field the row can drop.
    expect(formatLine({ ...STATE!, key: null, title: '' }, NOW, 4)).toBe(MARK_COUNT)
  })

  test('names the next left step after the current one, not before it', () => {
    expect(formatLine(STATE, NOW, 240)).toContain('⏭ 다음 정리')
  })

  test('draws the calibrated estimate when the summary carries one, else the raw one', () => {
    const raw = normalize(stateOf(), BOARD)
    const calibrated = normalize(stateOf({}, { etaCalibrated: '2026-10-09T16:48:00+09:00' }), BOARD)

    expect(raw?.eta).toBe('2026-10-09T16:20:00+09:00')
    expect(formatLine(raw, NOW, 240)).toContain('⏱ 예상 16:20')

    // render.py 가 보정값을 실으면 그쪽이 실제 완료 예상이다. 형식은 둘 다 같다.
    expect(calibrated?.eta).toBe('2026-10-09T16:48:00+09:00')
    expect(formatLine(calibrated, NOW, 240)).toContain('⏱ 예상 16:48')
  })

  test('leaves the estimate out when the summary carries neither', () => {
    const none = normalize(stateOf({}, { eta: null }), BOARD)

    expect(none?.eta).toBeNull()
    expect(formatLine(none, NOW, 240)).not.toContain('⏱')
  })

  test('draws from the summary alone when the data file is gone', () => {
    const alone = normalize(stateOf({ data: '' }))

    expect(formatLine(alone, NOW, 240)).toBe(
      `${STATUS_MARK} ✓ 3/6 ▓▓▓░░░ · CAS-1161 콘솔 dev 회귀 3회차 · ` +
        '▶ 실제 화면 확인 · 🔀 app-api#512 · ⏱ 예상 16:20 · 🔄 2분 전 · ⛔ 막힘 1 · ⏳ 남음 2 · ' +
        '🧵 백그라운드 2 · 🗜 압축 1',
    )
  })

  test('gives way in the order the pieces can spare it', () => {
    const long = { ...STATE!, title: '아주 긴 제목이 여기에 들어 있다 '.repeat(4) }
    const full = cellWidth(formatLine(long, NOW, 240))

    // One cell short of the whole row: only the title gives way, and only a cell of it.
    const cut = formatLine(long, NOW, full - 1)

    expect(cut).toContain('…')
    expect(cut).toContain('⏭ 다음 정리')
    expect(cut).toContain('배포 검증')

    // Too narrow for the keyed title at all: the next step goes before the blocked label.
    const keyed = cellWidth(formatLine({ ...STATE!, title: '' }, NOW, 240))
    const dropped = formatLine(long, NOW, keyed + 1)

    expect(dropped).not.toContain('아주')
    expect(dropped).toContain('⏭ 다음 정리')
    expect(dropped).toContain('배포 검증')

    // Narrower still: the blocked label is cut, and the next step is already gone.
    const tight = formatLine(long, NOW, keyed - 15)
    expect(cellWidth(tight)).toBeLessThanOrEqual(keyed - 15)
    expect(tight).not.toContain('⏭')
    expect(tight).toContain('배포')
  })

  test('gives the pieces up in the order the row can spare them, down to the count', () => {
    const bare = { ...STATE!, key: null, title: '' }
    // Everything but the mark and the count goes before the bar's own cells do.
    const kept = `${MARK_COUNT} ▓▓▓░░░`
    const bar = MARK_COUNT

    expect(formatLine(bare, NOW, cellWidth(kept))).toBe(kept)
    expect(formatLine(bare, NOW, cellWidth(bar))).toBe(bar)
    // Under the count's own cells the row stops giving way: the mark, the count
    // and a wait the session is in are not the fit's to drop.
    expect(formatLine(bare, NOW, 4)).toBe(bar)
    expect(formatLine({ ...bare, status: 'waiting_permission' }, NOW, 4)).toContain(bar)
  })

  test('gives up the pull request before the count, the title taking the cells it leaves', () => {
    const withPr = `${MARK_COUNT} ▓▓▓░░░ · CAS-1161 · ${PR_PIECE}`

    expect(formatLine(STATE, NOW, cellWidth(withPr))).toBe(withPr)

    // A cell short of that row the pull request is the piece that goes, and the
    // title, which gave its body away first, takes the cells it leaves: the
    // count stays and the title's own words are back beside it.
    const freed = formatLine(STATE, NOW, cellWidth(withPr) - 1)

    expect(freed).not.toContain(PR_PIECE)
    expect(freed).toContain('✓ 3/6')
    expect(freed).toContain('CAS-1161 콘솔 dev 회귀…')
    expect(cellWidth(freed)).toBeLessThanOrEqual(cellWidth(withPr) - 1)
  })

  test('draws the words in English for a state file that says en', () => {
    const english = formatLine(normalize(stateOf({}, { lang: 'en' }), BOARD), NOW, 240)

    expect(english).toContain('▶ 실제 화면 확인 4m in')
    expect(english).toContain('⏭ next 정리')
    expect(english).toContain('⏱ ETA 16:20')
    expect(english).toContain('🔄 2m ago')
    expect(english).toContain('⛔ blocked 1: 배포 검증')
    expect(english).toContain('⏳ left 2')
    expect(english).toContain('🧵 background 2')
    expect(english).toContain('🗜 compacted 1')
  })

  test('warns, then stops, as the last write falls behind', () => {
    const written = (minutes: number): typeof SAMPLE =>
      stateOf({}, { dataAt: new Date(NOW - minutes * 60000).toISOString() })

    expect(formatLine(normalize(written(10), BOARD), NOW, 240)).toContain('🔄 10분 전')
    expect(formatLine(normalize(written(11), BOARD), NOW, 240)).toContain('⚠️ 11분 전')
    expect(formatLine(normalize(written(30), BOARD), NOW, 240)).toContain('⚠️ 30분 전')
    expect(formatLine(normalize(written(31), BOARD), NOW, 240)).toContain('🛑 31분 전')
  })

  test('counts from the data write, not the state write the hooks keep fresh', () => {
    const stalled = stateOf(
      { updatedAt: new Date(NOW).toISOString() },
      { dataAt: new Date(NOW - 31 * 60000).toISOString() },
    )

    expect(formatLine(normalize(stalled, BOARD), NOW, 240)).toContain('🛑 31분 전')
  })

  test('falls back to the state write for a state file with no data write', () => {
    const older = stateOf({ updatedAt: new Date(NOW - 31 * 60000).toISOString() }, { dataAt: undefined })

    expect(formatLine(normalize(older, BOARD), NOW, 240)).toContain('🛑 31분 전')
  })

  test('draws nothing without a state', () => {
    expect(formatLine(null, NOW, 240)).toBe('')
  })

  test('draws the key a title opens with once, not beside a copy of it', () => {
    const row = formatLine(STATE, NOW, 240)

    expect(row).toContain('CAS-1161 콘솔 dev 회귀 3회차')
    expect(row).not.toContain('CAS-1161 CAS-1161')
    // The key an opening title repeats is still the run's own piece, cut and
    // colored as the key; the title's words after it are the title.
    expect(pieceIn(statusLine(STATE, NOW, 240), 'CAS-1161')?.tone).toBe('permission')
    expect(pieceIn(statusLine(STATE, NOW, 240), '콘솔 dev 회귀 3회차')?.tone).toBe('text')
  })

  test('keeps the key beside a title that does not open with it', () => {
    const other = normalize(stateOf({}, { title: '다른 제목' }), BOARD)
    const row = formatLine(other, NOW, 240)

    expect(row).toContain('CAS-1161 다른 제목')
    expect(row).not.toContain('CAS-1161 CAS-1161')
  })

  test('reads a key only where a word ends, not inside a longer one', () => {
    const longer = normalize(stateOf({}, { title: 'CAS-11610 회귀' }), BOARD)

    expect(formatLine(longer, NOW, 240)).toContain('CAS-1161 CAS-11610 회귀')
  })

  test('draws the whole line in 60 and 40 cells', () => {
    for (const maxCols of [60, 40]) {
      expect(cellWidth(formatLine(STATE, NOW, maxCols))).toBeLessThanOrEqual(maxCols)
    }
  })

  test('draws the title again in the cells the fields before it left', () => {
    // A row far too long for its cells: the title gives its body away at once,
    // and takes back the cells the fields dropped after it leave behind.
    const long = normalize(stateOf({}, { title: '아주 긴 제목이 여기에 들어 있다 '.repeat(12) }), BOARD)
    const row = formatLine(long, NOW, 109)

    expect(row).toContain('아주')
    expect(row).toContain('…')
    expect(row).toContain('⏳ 남음 2')
    expect(cellWidth(row)).toBeLessThanOrEqual(109)
  })
})

describe('the live clock', () => {
  test('repaints the status line as the minutes move', async ($, on) => {
    const { clock, invalidates } = statusWorld(on, filesOf(statusState()))

    await $.session.start(SESSION)

    const after = invalidates.length

    await clock.advance(5000)

    expect(invalidates.length).toBe(after)

    await clock.advance(60000)

    expect(invalidates.length).toBeGreaterThan(after)
  })

  test('repaints the band as the minutes move', async ($, on) => {
    const { clock, invalidates } = worldOf(on, filesOf())

    await $.session.start(SESSION)

    const after = invalidates.length

    await clock.advance(5000)

    expect(invalidates.length).toBe(after)

    await clock.advance(60000)

    expect(invalidates.length).toBeGreaterThan(after)
  })
})

describe('the open button and command', () => {
  test('renders the page, then opens it, and toasts the answer', async ($, on) => {
    const { toasts, runs } = worldOf(on, filesOf())

    await $.session.start(SESSION)

    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    await ui.press({ key: 'open' })
    await ui.unmount()

    expect(runs).toHaveLength(2)
    expect(runs[0]?.slice(0, 1)).toEqual(['python3'])
    expect(runs[0]?.[1]?.endsWith('/render.py')).toBe(true)
    expect(runs[0]?.slice(2)).toEqual(['--page', '--session', SESSION_ID, DATA_PATH, OUT_PATH])
    expect(runs[1]?.[0]).toBe('bash')
    expect(runs[1]?.[1]?.endsWith('/open.sh')).toBe(true)
    expect(runs[1]?.[2]).toBe(OUT_PATH)
    expect(toasts).toEqual(['HTML 페이지를 열었어요'])
  })

  test('answers the same sentence as a command', async ($, on) => {
    const { toasts, runs } = worldOf(on, filesOf())

    await $.session.start(SESSION)

    const answered = await $.command.run(open)
    const ui = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    await ui.press({ key: 'open' })
    await ui.unmount()

    expect(answered.text).toBe('HTML 페이지를 열었어요')
    expect(toasts).toEqual([answered.text])
    expect(runs).toHaveLength(4)
  })

  test('says there is no page yet when the state names none', async ($, on) => {
    const { runs } = worldOf(on, filesOf(stateOf({ out: '' })))
    pinsNothing(on)

    await $.session.start(SESSION)

    expect((await $.command.run(open)).text).toBe('아직 HTML 페이지가 없어요')
    expect(runs).toEqual([])
  })

  test('says there is no page yet when the state names no data file', async ($, on) => {
    const { runs } = worldOf(on, filesOf(stateOf({ data: '' })))
    pinsNothing(on)

    await $.session.start(SESSION)

    expect((await $.command.run(open)).text).toBe('아직 HTML 페이지가 없어요')
    expect(runs).toEqual([])
  })

  test('reports the exit code and the first line when the render fails', async ($, on) => {
    const world = worldOf(on, filesOf())
    pinsNothing(on)

    world.renderer.exitCode = 1
    world.renderer.stderr = 'render.py: 데이터를 읽지 못했다\nstack'

    await $.session.start(SESSION)

    expect((await $.command.run(open)).text).toBe(
      'HTML 페이지를 열지 못했어요: exit 1: render.py: 데이터를 읽지 못했다',
    )
    expect(world.runs).toHaveLength(1)
  })

  test('reports the exit code and the first line of what the opener wrote', async ($, on) => {
    const world = worldOf(on, filesOf())
    pinsNothing(on)

    world.opener.exitCode = 2
    world.opener.stderr = 'no such file: /tmp/x.html\nstack'

    await $.session.start(SESSION)

    expect((await $.command.run(open)).text).toBe(
      'HTML 페이지를 열지 못했어요: exit 2: no such file: /tmp/x.html',
    )
    expect(world.runs).toHaveLength(2)
  })

  test('gives the path when the opener leaves the page to the desktop app', async ($, on) => {
    const world = worldOf(on, filesOf())
    pinsNothing(on)

    world.opener.stdout = `opened: desktop ${OUT_PATH}`

    await $.session.start(SESSION)

    expect((await $.command.run(open)).text).toBe(
      `Claude 데스크톱 앱에서 이 경로를 눌러 주세요: ${OUT_PATH}`,
    )
  })

  test('says no browser was found when the opener opened nothing', async ($, on) => {
    const world = worldOf(on, filesOf())
    pinsNothing(on)

    world.opener.stdout = `opened: none ${OUT_PATH}`

    await $.session.start(SESSION)

    expect((await $.command.run(open)).text).toBe(`열 수 있는 브라우저를 찾지 못했어요: ${OUT_PATH}`)
  })

  test('runs the opener while the status line draws', async ($, on) => {
    const { runs } = worldOf(on, filesOf(statusState()))
    pinsNothing(on)

    await $.session.start(SESSION)

    expect((await $.command.run(open)).text).toBe('HTML 페이지를 열었어요')
    expect(runs).toHaveLength(2)
  })

  test('reaches the skill folder when the plugin root is the skill', async ($, on) => {
    const { runs, stats } = worldOf(on, filesOf(), NOW, true)
    pinsNothing(on)

    await $.session.start(SESSION)

    await $.command.run(open)

    // 스킬 폴더가 곧 플러그인 루트다. 탐침한 render.py 가 그대로 실행된다.
    expect(stats[0]?.endsWith('/render.py')).toBe(true)
    expect(runs[0]?.[1]).toBe(stats[0])
  })

  test('falls back to the skill under the plugin root', async ($, on) => {
    const { runs, stats } = worldOf(on, filesOf())
    pinsNothing(on)

    await $.session.start(SESSION)

    await $.command.run(open)

    // 루트에 render.py 가 없으면 플러그인 루트 아래 skills/deadhd 로 내려간다.
    expect(runs[0]?.[1]).toBe((stats[0] ?? '').replace(/\/render\.py$/, '/skills/deadhd/render.py'))
  })
})

describe('the command', () => {
  test('folds and opens the band, answering each time', async ($, on) => {
    worldOf(on, filesOf())

    await $.session.start(SESSION)

    const folded = await $.command.run(run)

    expect(folded.text).toBe('밴드를 접었어요')

    const band = await $.ui.mount({ ...MOUNT, surface: 'terminal' })

    expect(textOf(await band.drawn())).toContain('펼치기')

    await band.unmount()

    const opened = await $.command.run(run)

    expect(opened.text).toBe('밴드를 펼쳤어요')
  })

  test('is declared while the band draws', async ($, on) => {
    const { registered } = worldOf(on, filesOf())

    await $.session.start(SESSION)

    expect(registered).toEqual(['deadhd-band', 'deadhd-statusline', 'deadhd-open'])
  })

  test('tells the person to switch views when the view is not the band', async ($, on) => {
    worldOf(on, filesOf(statusState()))

    await $.session.start(SESSION)

    expect((await $.command.run(run)).text).toBe(
      '지금은 밴드 모드가 아니에요. /deadhd setup 에서 밴드를 고르면 보여요.',
    )
  })
})

describe('cellWidth', () => {
  test('counts a cell a code point, two for a wide one', () => {
    expect(cellWidth('abc')).toBe(3)
    expect(cellWidth('한글')).toBe(4)
    expect(cellWidth('é')).toBe(1)
    expect(cellWidth('🙂')).toBe(2)
  })

  test('counts the emoji the lines draw as two cells', () => {
    const emoji = ['⏭', '⏱', '🔄', '⚠️', '🛑', '⛔', '⏳', '🔐', '💬', '🧵', '🗜', '⌨️']

    for (const glyph of emoji) {
      expect([glyph, cellWidth(glyph)]).toEqual([glyph, 2])
    }
  })

  test('counts the text symbols the lines draw as one cell', () => {
    for (const glyph of ['✓', '▶', '↗', '▓', '░', '◇', '◐', '·']) {
      expect([glyph, cellWidth(glyph)]).toEqual([glyph, 1])
    }
  })

  test('reads a whole row by the same metric', () => {
    expect(cellWidth('✓ 3/6')).toBe(5)
    expect(cellWidth('⛔ 막힘 1')).toBe(9)
  })
})

describe('normalize', () => {
  test('folds a shape it does not know to the neutral values', () => {
    expect(normalize({ status: 7, summary: { counts: { done: 'x' }, lang: 'de' } })).toEqual({
      status: 'working',
      lang: 'ko',
      key: null,
      keyHref: null,
      title: '',
      pr: null,
      done: 0,
      now: 0,
      side: 0,
      left: 0,
      blocked: 0,
      total: 0,
      allDone: false,
      current: null,
      next: null,
      stuck: null,
      eta: null,
      updatedAt: null,
      since: null,
      background: 0,
      compactions: 0,
      view: null,
      data: null,
      out: null,
    })
  })

  test('is null for what is not a state file at all', () => {
    expect(normalize(null)).toBeNull()
    expect(normalize('[1,2,3]')).toBeNull()
    expect(normalize('a string')).toBeNull()
  })

  test('reads the view, the data path and the page path off the state file', () => {
    expect(STATE?.view).toBe('band')
    expect(STATE?.data).toBe(DATA_PATH)
    expect(STATE?.out).toBe(OUT_PATH)
    expect(normalize(stateOf({ view: 'paper' }))?.view).toBeNull()
  })

  test('reads the running step, the next one and the stuck one out of the data file', () => {
    expect(STATE?.current).toMatchObject({ state: 'now', label: '실제 화면 확인' })
    expect(STATE?.next).toMatchObject({ state: 'left', label: '정리' })
    expect(STATE?.stuck).toMatchObject({ state: 'blocked', label: '배포 검증', sub: '권한 대기' })
    expect(STATE?.background).toBe(2)
    expect(STATE?.compactions).toBe(1)
  })

  test('gives a step without a column the next free one in its lane', () => {
    const board = {
      items: [
        { label: '하나', state: 'done', lane: 0, col: 0 },
        { label: '둘', state: 'now', lane: 0 },
        { label: '셋', state: 'left', lane: 0 },
      ],
    }

    const state = normalize(SAMPLE, board)

    expect(state?.next).toMatchObject({ label: '셋' })
  })

  test('names the blocked step from the summary when the data file is gone', () => {
    const alone = normalize(
      stateOf({}, { counts: { done: 3, now: 0, side: 0, left: 2, blocked: 1 } }),
    )

    expect(alone?.current).toBeNull()
    expect(alone?.stuck).toMatchObject({ state: 'blocked', label: '실제 화면 확인' })
    expect(alone?.next).toBeNull()
  })

  test('survives a data file that is not JSON', () => {
    const broken = normalize(stateOf(), '{not json')

    expect(broken?.current).toMatchObject({ label: '실제 화면 확인' })
    expect(broken?.stuck).toBeNull()
  })
})
