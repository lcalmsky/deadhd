/**
 * deadhd's `$.state` contract: the normalized progress the band and the status
 * line draw from, which view this session draws in, and whether the person
 * folded the line down for this session.
 */

export type DeadhdLang = 'ko' | 'en'

/** Where the session's progress is drawn. */
export type DeadhdView = 'html' | 'band' | 'statusline'

/**
 * One step of the session's data file, as the band reads it.
 *
 * A step the data spells wrongly costs the pieces that read it, never the line.
 */
export type DeadhdStep = {
  /** The skill's own word for the step: `now`, `side`, `left`, `blocked` or `done`. */
  state: string
  label: string
  /** The one-to-three-word note drawn under the step; `''` when the data has none. */
  sub: string
  /** When the step started, ISO 8601 with an offset, or null when the data omits it. */
  startedAt: string | null
  /** The step's lane and column, the order the page draws it in. */
  lane: number
  col: number
}

/**
 * The session's state file and data file together, normalized: what the band
 * and the status line read.
 *
 * Absent or unreadable values are folded to the neutral ones (`0`, `''`,
 * `null`), so a file the skill wrote differently costs a part of the line,
 * never the plugin. A data file that is missing or broken costs the steps
 * alone: the summary still draws.
 */
export type DeadhdState = {
  /** The skill's own word: `working`, `waiting_permission`, `idle`, `ended`, ... */
  status: string
  lang: DeadhdLang
  /** The ticket or program key of the run, or null when the summary has none. */
  key: string | null
  title: string
  done: number
  now: number
  side: number
  left: number
  blocked: number
  total: number
  allDone: boolean
  /** The step the lines mark as running: the first `now`, else the first `side`. */
  current: DeadhdStep | null
  /** The first `left` step after `current`, in lane·column order. */
  next: DeadhdStep | null
  /** The first `blocked` step the data names. */
  stuck: DeadhdStep | null
  /** The completion estimate, an ISO 8601 instant with an offset, or null. */
  eta: string | null
  /**
   * When the skill last wrote the data file, ISO 8601 with an offset; the lines
   * count `N분 전` from here. The state file's own write time stands in when the
   * summary carries none, since the hooks rewrite it on every event.
   */
  updatedAt: string | null
  /** When the current status began, ISO 8601 with an offset. */
  since: string | null
  /** How many background tasks the session's last turn left running. */
  background: number
  /** How many times the session has compacted. */
  compactions: number
  /** The view the state file names, or null when it names none render.py knows. */
  view: DeadhdView | null
  /** The absolute path of the data file the page is rendered from, or null. */
  data: string | null
  /** The absolute path of the rendered page, or null before one is rendered. */
  out: string | null
}

declare module 'claude-code' {
  interface PluginState {
    deadhd: {
      /** The last state read, or null while the session has none. */
      state: DeadhdState | null
      /** True while the line is folded to its one-word summary; kept for the session. */
      collapsed: boolean
      /** The view in force: the state file's, else the config file's, else `html`. */
      view: DeadhdView
    }
  }
}
