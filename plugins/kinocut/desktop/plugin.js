// Kinocut desktop plugin for Hermes Desktop (opt-in).
//
// Shows the running Kinocut tool (and its percent, when the tool reports one) in the
// status bar, and a "Kinocut renders" pane that keeps renders apart from lookups. Both
// are fed by the gateway tool.start / tool.progress / tool.complete events.
// Plain uncompiled ESM: no JSX, only `@hermes/plugin-sdk`, `react` and
// `react/jsx-runtime` resolve, and relative imports do not (so the reducer below is
// inlined; plugin.test.mjs extracts the marked block to test it).
import { host, PALETTE_AREA, STATUSBAR_AREAS } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

// --- reducer:begin (pure; no SDK use; keep self-contained) ---
const MAX_RECENT = 10

// Inspection tools appear in Activity; tests/test_desktop_plugin_lookups.py checks this list.
export const LOOKUP_TOOLS = new Set([
  'describe_operation',
  'list_operations',
  'search_tools',
  'video_direct',
  'video_doctor',
  'video_info',
  'video_info_detailed'
])

export function runKind(tool) {
  return LOOKUP_TOOLS.has(tool) ? 'activity' : 'render'
}

// Keep the newest MAX_RECENT of each kind, so a burst of lookups never pushes renders out.
function capPerKind(items) {
  const seen = { render: 0, activity: 0 }
  return items.filter(item => ++seen[item.kind] <= MAX_RECENT)
}

export function initialRenders() {
  return { active: {}, recent: [], finished: [], nextHistoryId: 1 }
}

export function shortToolName(name) {
  const parts = String(name || '').split('__')
  return parts[parts.length - 1] || String(name || '')
}

export function isKinocutTool(name) {
  if (typeof name !== 'string' || !name) return false
  const parts = name.split('__')
  // Namespaced MCP calls belong to Kinocut only when the server is Kinocut.
  if (parts[0] === 'mcp' && parts.length >= 3) return parts[1].toLowerCase().includes('kinocut')
  return /^(video_|audio_|kinocut)/i.test(name)
}

export function clampPercent(value) {
  if (typeof value !== 'number' && !(typeof value === 'string' && value.trim())) return null
  const n = Number(value)
  if (value === null || value === undefined || !Number.isFinite(n)) return null
  return Math.min(100, Math.max(0, Math.round(n)))
}

// Hermes hands MCP results to tool.complete as text: `{ result: "<JSON>" }`, sometimes
// nested once more. Unwrap up to three layers of JSON strings or `result` fields.
function inspectResult(value) {
  let result = value
  let failed = false
  let message = ''
  for (let depth = 0; depth <= 3; depth++) {
    if (typeof result === 'string' && depth < 3) {
      try {
        result = JSON.parse(result)
        continue
      } catch {
        break
      }
    }
    if (!result || typeof result !== 'object') break
    failed ||= failureOf(result)
    message = errorText(result.error) || errorText(result) || message
    if (depth === 3 || !('result' in result) || (!failed && 'success' in result)) break
    result = result.result
  }
  return { result, failed, message: typeof result === 'string' ? result || message : message }
}

export function unwrapResult(value) {
  const { result } = inspectResult(value)
  return result && typeof result === 'object' ? result : null
}

function failureOf(r) {
  return Boolean(r && (r.error || r.ok === false || r.success === false || r.isError === true || r.is_error === true))
}

// The SDK doc does not name a failure field on tool.complete; accept the plausible ones,
// on the payload itself and on its (possibly text-wrapped) result.
export function isFailedComplete(payload) {
  if (!payload) return false
  if (failureOf(payload)) return true
  return inspectResult(payload.result).failed
}

function outputSize(result) {
  if (Number.isFinite(result?.size_bytes) && result.size_bytes >= 0) return result.size_bytes
  if (Number.isFinite(result?.size_mb)) {
    const bytes = result.size_mb * 1024 ** 2
    if (Number.isFinite(bytes) && bytes >= 0) return bytes
  }
  return null
}

const STALL_GAP_MS = 10_000

export function estimateRemainingMs(previous, percent, now) {
  if (!previous || previous.percent === null || percent === null || percent >= 100) return null
  const elapsed = now - previous.at
  const advanced = percent - previous.percent
  if (elapsed < 250 || advanced < 15) return null
  return Math.round(elapsed * (100 - percent) / advanced)
}

function errorText(err) {
  if (!err) return ''
  if (typeof err === 'string') return err
  if (typeof err === 'object' && typeof err.message === 'string') return err.message
  if (typeof err === 'object' && Array.isArray(err.content)) {
    const t = err.content.find(c => c && typeof c.text === 'string')
    if (t) return t.text
  }
  return ''
}

// Two sessions or gateway connections can both use tool_id "call_1". The scope (profile,
// connection, session) keeps their rows apart; with no scope the key is the bare id.
export function eventScope(frame) {
  if (!frame || typeof frame !== 'object') return ''
  return [frame.profile, frame.connectionId, frame.session_id]
    .map(v => (typeof v === 'string' || typeof v === 'number' ? String(v) : ''))
    .join('|')
    .replace(/^\|+$/, '')
}

function runKey(scope, id) {
  return scope ? `${scope}#${id}` : String(id)
}

// Keys of finished runs, so a late progress frame or a duplicate complete does not
// resurrect or re-record a run. A start for a finished key does reopen it: providers
// reuse tool ids (e.g. "call_0" every turn), and Hermes start frames carry no timestamp
// that could tell a reuse from a replay. The desktop gateway does not replay tool.start.
const MAX_FINISHED = 200

// event: { type: 'start' | 'progress' | 'complete', payload, scope? (string), now? (ms) }
export function reduceRenders(state, event) {
  const prev = state || initialRenders()
  const finished = prev.finished || []
  const nextHistoryId = prev.nextHistoryId || 1
  const payload = (event && event.payload) || {}
  const id = payload.tool_id
  const name = payload.name
  if (!event || !id || !isKinocutTool(name)) return prev
  const key = runKey(typeof event.scope === 'string' ? event.scope : '', id)
  const now = typeof event.now === 'number' ? event.now : 0
  const tool = shortToolName(name)

  if (event.type === 'start' || event.type === 'progress') {
    if (event.type === 'progress' && finished.includes(key)) return prev
    const existing = Object.hasOwn(prev.active, key) ? prev.active[key] : null
    const percent = event.type === 'progress' ? clampPercent(payload.percent) : null
    if (percent !== null && existing?.percent != null && percent < existing.percent) return prev
    const historyId = existing ? existing.historyId : nextHistoryId
    let progressSample = existing?.progressSample ?? null
    let lastAdvanceAt = existing?.lastAdvanceAt ?? null
    let remainingMs = existing?.remainingMs ?? null
    if (percent !== null) {
      const advanced = existing?.percent == null || percent > existing.percent
      const stalled = lastAdvanceAt !== null && now - lastAdvanceAt >= STALL_GAP_MS
      if (percent === 100) {
        progressSample = { percent, at: now }
        lastAdvanceAt = now
        remainingMs = null
      } else if (!progressSample || stalled) {
        progressSample = { percent, at: now }
        lastAdvanceAt = now
        remainingMs = null
      } else if (advanced) {
        lastAdvanceAt = now
        const estimate = estimateRemainingMs(progressSample, percent, now)
        if (estimate !== null) {
          progressSample = { percent, at: now }
          remainingMs = estimate
        }
      }
    }
    const next = {
      key,
      historyId,
      tool_id: id,
      name,
      tool,
      startedAt: existing ? existing.startedAt : now,
      percent: percent !== null ? percent : existing ? existing.percent : null,
      progressSample,
      lastAdvanceAt,
      remainingMs,
      message: typeof payload.message === 'string' && payload.message ? payload.message : existing ? existing.message : ''
    }
    return {
      active: { ...prev.active, [key]: next },
      recent: prev.recent,
      finished: event.type === 'start' ? finished.filter(k => k !== key) : finished,
      nextHistoryId: existing ? nextHistoryId : nextHistoryId + 1
    }
  }

  if (event.type === 'complete') {
    const existing = Object.hasOwn(prev.active, key) ? prev.active[key] : null
    if (!existing && finished.includes(key)) return prev
    const active = { ...prev.active }
    delete active[key]
    const historyId = existing ? existing.historyId : nextHistoryId
    const historyKey = `${key}@${historyId}`
    const details = inspectResult(payload.result)
    const failed = failureOf(payload) || details.failed
    const startedAt = existing ? existing.startedAt : now
    const durationMs =
      typeof payload.duration_s === 'number' && Number.isFinite(payload.duration_s)
        ? Math.max(0, Math.round(payload.duration_s * 1000))
        : Math.max(0, now - startedAt)
    const done = {
      key: historyKey,
      runKey: key,
      historyId,
      tool_id: id,
      name,
      tool,
      kind: runKind(tool),
      status: failed ? 'failed' : 'done',
      durationMs,
      sizeBytes: failed ? null : outputSize(details.result),
      message: failed
        ? errorText(payload.error) || details.message ||
          (existing && existing.message) ||
          ''
        : (existing && existing.message) || (typeof payload.summary === 'string' ? payload.summary : ''),
      finishedAt: now
    }
    return {
      active,
      recent: capPerKind([done, ...prev.recent.filter(r => r.historyId !== historyId)]),
      finished: [key, ...finished.filter(k => k !== key)].slice(0, MAX_FINISHED),
      nextHistoryId: existing ? nextHistoryId : nextHistoryId + 1
    }
  }
  return prev
}
// --- reducer:end ---

const FLASH_MS = 5000
const PANE_ID = 'kinocut-renders'

// The desktop plugin loads as a single module with no relative asset imports.
// This 24px copy of ../icon.png keeps the mark available offline.
const KINOCUT_MARK = 'data:image/png;base64,' + [
  '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'
].join('')

function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)} s`
  return `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`
}

function formatOutputSize(bytes) {
  if (bytes === null) return ''
  if (bytes < 1024) return `${Math.round(bytes)} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`
}

function createStore(ctx) {
  let state = { renders: initialRenders(), flash: null }
  let cancelFlash = null
  const listeners = new Set()
  const emit = () => listeners.forEach(fn => fn())
  const clearFlash = () => {
    if (cancelFlash) cancelFlash()
    cancelFlash = null
  }
  ctx.onDispose(() => {
    clearFlash()
    listeners.clear()
  })
  return {
    get: () => state,
    subscribe(fn) {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    dispatch(type, payload, scope) {
      const renders = reduceRenders(state.renders, { type, payload, scope, now: Date.now() })
      if (renders === state.renders) return
      let flash = state.flash
      if (type === 'complete') {
        const latest = renders.recent[0]
        if (latest) {
          flash = { tool: latest.tool, failed: latest.status === 'failed' }
          clearFlash()
          cancelFlash = ctx.setTimeout(() => {
            cancelFlash = null
            state = { ...state, flash: null }
            emit()
          }, FLASH_MS)
        }
      }
      state = { renders, flash }
      emit()
    }
  }
}

function useStore(store) {
  const [snap, setSnap] = useState(store.get())
  useEffect(() => {
    setSnap(store.get())
    return store.subscribe(() => setSnap(store.get()))
  }, [store])
  return snap
}

const PANE_STYLE = `
.kinocut-pane .kinocut-result {
  border: 1px solid var(--ui-stroke-secondary);
  border-radius: 8px;
  background: var(--ui-bg-card);
  padding: 10px 12px;
}
.kinocut-pane .kinocut-result:focus-visible {
  outline: 2px solid var(--ui-accent-secondary, Highlight);
  outline-offset: 2px;
}
.kinocut-pane .kinocut-failed {
  color: color-mix(in srgb, var(--ui-red, var(--ui-text-primary)) 82%, var(--ui-text-primary));
}
.kinocut-pane .kinocut-progress {
  --kinocut-progress-track: color-mix(in srgb, var(--ui-accent-secondary, Highlight) 18%, transparent);
  display: block;
  width: 100%;
  height: 6px;
  margin-block: 6px 2px;
  appearance: none;
  border: 0;
  border-radius: 3px;
  overflow: hidden;
  background: var(--kinocut-progress-track);
}
.kinocut-pane .kinocut-progress::-webkit-progress-bar {
  background: transparent;
}
.kinocut-pane .kinocut-progress::-webkit-progress-value {
  background: var(--ui-accent-secondary, Highlight);
  border-radius: 3px;
}
.kinocut-pane .kinocut-progress::-moz-progress-bar {
  background: var(--ui-accent-secondary, Highlight);
  border-radius: 3px;
}
`

function ProgressBar({ tool, percent }) {
  const label = `${tool} progress`
  if (percent === null) {
    return jsx('div', {
      role: 'progressbar',
      'aria-label': label,
      'aria-valuetext': 'Waiting for a progress update',
      className: 'kinocut-progress'
    })
  }
  return jsx('progress', {
    'aria-label': label,
    max: 100,
    value: percent,
    className: 'kinocut-progress'
  })
}

function renderFailureCause(message) {
  const retryStart = message.lastIndexOf('; retry with ')
  if (retryStart === -1) return message
  const retry = message.slice(retryStart)
  const hasInvocation = retry.endsWith(' (MCP)') || (retry.includes(' (MCP) / ') && retry.endsWith(' (CLI)'))
  return hasInvocation ? jsxs('details', {
    children: [jsx('summary', { children: message.slice(0, retryStart) }), message.slice(retryStart + 2)]
  }) : message
}

function RecentList({ items, row }) {
  return items.map(r =>
    row(
      r.key || r.tool_id,
      [
        jsxs(
          'div',
          {
            className: 'flex justify-between gap-2',
            children: [
              jsx('span', { className: 'min-w-0 break-all font-medium', children: r.tool }),
              jsx('span', {
                className: 'whitespace-nowrap font-mono text-xs text-(--ui-text-secondary)',
                children: [formatDuration(r.durationMs), formatOutputSize(r.sizeBytes)].filter(Boolean).join(' · ')
              })
            ]
          },
          'h'
        ),
        jsx(
          'div',
          {
            className: r.status === 'failed' ? 'kinocut-failed text-xs' : 'text-xs text-(--ui-text-secondary)',
            children: r.status === 'failed' ? 'Failed' : 'Finished'
          },
          's'
        ),
        r.message
          ? jsx('div', {
              className: 'break-words text-(--ui-text-secondary)',
              children: r.status === 'failed' ? renderFailureCause(r.message) : r.message
            }, 'm')
          : null
      ],
      0
    )
  )
}

function RendersPane({ store }) {
  const { renders } = useStore(store)
  const active = Object.values(renders.active)
  const row = (key, children, tabIndex) =>
    jsx(
      'div',
      {
        className: 'kinocut-result flex flex-col gap-1',
        tabIndex,
        children
      },
      key
    )
  const heading = text => jsx('h3', { className: 'text-xs font-semibold text-(--ui-text-secondary)', children: text })
  const done = renders.recent.filter(r => r.kind === 'render')
  const lookups = renders.recent.filter(r => r.kind === 'activity')

  return jsxs('div', {
    className: 'kinocut-pane flex h-full flex-col gap-3 overflow-auto p-3 text-sm',
    children: [
      jsx('style', { children: PANE_STYLE }),
      jsxs('header', {
        className: 'flex items-center gap-2',
        children: [
          jsx('img', { src: KINOCUT_MARK, alt: '', width: 24, height: 24 }),
          jsx('h2', { className: 'text-base font-semibold', children: 'Kinocut renders' })
        ]
      }),
      active.length === 0 && done.length === 0 && lookups.length === 0 &&
        jsx('p', {
          className: 'kinocut-result text-(--ui-text-secondary)',
          children: 'Start a Kinocut edit in chat to see its progress here.'
        }),
      ...active.map(a =>
        row(a.key || a.tool_id, [
          jsxs('div', {
            className: 'font-semibold',
            children: [
              `${a.tool} is running`,
              a.percent === null ? '.' : jsxs('span', {
                className: 'font-mono',
                children: [
                  ` at ${a.percent}%`,
                  a.remainingMs === null ? '.' : `, about ${formatDuration(a.remainingMs)} left.`
                ]
              })
            ]
          }, 'h'),
          jsx(ProgressBar, { tool: a.tool, percent: a.percent }, 'p'),
          a.message ? jsx('div', { className: 'break-words text-(--ui-text-secondary)', children: a.message }, 'm') : null
        ], 0)
      ),
      done.length > 0 && heading('Renders'),
      ...RecentList({ items: done, row }),
      lookups.length > 0 && heading('Activity'),
      ...RecentList({ items: lookups, row })
    ]
  })
}

function StatusItem({ store, onOpen }) {
  const { renders, flash } = useStore(store)
  const active = Object.values(renders.active)
  let label = null
  let title = 'Kinocut renders'
  if (active.length > 0) {
    const a = active[active.length - 1]
    label = `Kinocut ${a.tool}${a.percent === null ? '' : ` ${a.percent}%`}`
    if (a.message) title = a.message
  } else if (flash) {
    label = `Kinocut ${flash.failed ? '✗' : '✓'} ${flash.tool}`
  }
  if (label === null) return null
  return jsx('button', {
    type: 'button',
    className: 'px-1.5 text-[0.6875rem] text-(--ui-text-secondary)',
    title,
    onClick: onOpen,
    children: label
  })
}

export default {
  id: 'kinocut',
  name: 'Kinocut',
  defaultEnabled: false,
  register(ctx) {
    const store = createStore(ctx)
    const renderPane = () => jsx(RendersPane, { store })

    const openPane = () => {
      if (typeof host.openWorkspace === 'function') {
        host.openWorkspace(PANE_ID, { title: 'Kinocut renders', render: renderPane })
      } else {
        host.notify({ kind: 'info', message: 'Open the "Kinocut renders" pane from the layout.' })
      }
    }

    for (const [type, kind] of [
      ['tool.start', 'start'],
      ['tool.progress', 'progress'],
      ['tool.complete', 'complete']
    ]) {
      ctx.onEvent(type, frame => store.dispatch(kind, frame && frame.payload, eventScope(frame)))
    }

    ctx.registerMany([
      {
        id: 'pane',
        area: 'panes',
        title: 'Kinocut renders',
        data: { placement: 'right', width: '300px' },
        render: renderPane
      },
      {
        id: 'status',
        area: STATUSBAR_AREAS.right,
        order: 125,
        render: () => jsx(StatusItem, { store, onOpen: openPane })
      },
      {
        id: 'show',
        area: PALETTE_AREA,
        data: {
          id: 'kinocut.show-renders',
          label: 'Kinocut: Show renders',
          keywords: ['kinocut', 'render', 'video', 'progress'],
          run: openPane
        }
      }
    ])
  }
}
