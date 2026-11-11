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

// Kinocut tools that never write media (no `overwrite` parameter). They show under
// Activity, not Renders. tests/test_desktop_plugin_lookups.py keeps this in sync.
export const LOOKUP_TOOLS = new Set([
  'describe_operation',
  'list_operations',
  'search_tools',
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
  return { active: {}, recent: [], finished: [] }
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
  const n = Number(value)
  if (value === null || value === undefined || !Number.isFinite(n)) return null
  return Math.min(100, Math.max(0, Math.round(n)))
}

// Hermes hands MCP results to tool.complete as text: `{ result: "<JSON>" }`, sometimes
// nested once more. Unwrap up to three layers of JSON strings or `result` fields.
export function unwrapResult(value) {
  let r = value
  for (let i = 0; i < 3; i++) {
    if (typeof r === 'string') {
      try {
        r = JSON.parse(r)
      } catch {
        return null
      }
      continue
    }
    if (r && typeof r === 'object' && !('success' in r) && !('error' in r) && !('isError' in r) && 'result' in r) {
      r = r.result
      continue
    }
    break
  }
  return r && typeof r === 'object' ? r : null
}

function failureOf(r) {
  return Boolean(r && (r.error || r.ok === false || r.success === false || r.isError === true))
}

// The SDK doc does not name a failure field on tool.complete; accept the plausible ones,
// on the payload itself and on its (possibly text-wrapped) result.
export function isFailedComplete(payload) {
  if (!payload) return false
  if (failureOf(payload)) return true
  return failureOf(unwrapResult(payload.result))
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

// Keys of finished runs, so a progress or start frame that arrives after its complete
// (reordered or replayed) does not resurrect a "running" row.
const MAX_FINISHED = 200

// event: { type: 'start' | 'progress' | 'complete', payload, scope? (string), now? (ms) }
export function reduceRenders(state, event) {
  const prev = state || initialRenders()
  const finished = prev.finished || []
  const payload = (event && event.payload) || {}
  const id = payload.tool_id
  const name = payload.name
  if (!event || !id || !isKinocutTool(name)) return prev
  const key = runKey(typeof event.scope === 'string' ? event.scope : '', id)
  const now = typeof event.now === 'number' ? event.now : 0
  const tool = shortToolName(name)

  if (event.type === 'start' || event.type === 'progress') {
    if (event.type === 'progress' && finished.includes(key)) return prev
    const existing = prev.active[key]
    const percent = event.type === 'progress' ? clampPercent(payload.percent) : null
    const next = {
      key,
      tool_id: id,
      name,
      tool,
      startedAt: existing ? existing.startedAt : now,
      percent: percent !== null ? percent : existing ? existing.percent : null,
      message: typeof payload.message === 'string' && payload.message ? payload.message : existing ? existing.message : ''
    }
    return {
      active: { ...prev.active, [key]: next },
      recent: prev.recent,
      finished: event.type === 'start' ? finished.filter(k => k !== key) : finished
    }
  }

  if (event.type === 'complete') {
    const existing = prev.active[key]
    const active = { ...prev.active }
    delete active[key]
    const failed = isFailedComplete(payload)
    const startedAt = existing ? existing.startedAt : now
    const durationMs =
      typeof payload.duration_s === 'number' && Number.isFinite(payload.duration_s)
        ? Math.max(0, Math.round(payload.duration_s * 1000))
        : Math.max(0, now - startedAt)
    const result = unwrapResult(payload.result)
    const done = {
      key,
      tool_id: id,
      name,
      tool,
      kind: runKind(tool),
      status: failed ? 'failed' : 'done',
      durationMs,
      message: failed
        ? errorText(payload.error || (result && result.error) || (result && result.isError ? result : null)) ||
          (existing && existing.message) ||
          ''
        : (existing && existing.message) || (typeof payload.summary === 'string' ? payload.summary : ''),
      finishedAt: now
    }
    return {
      active,
      recent: capPerKind([done, ...prev.recent.filter(r => (r.key || r.tool_id) !== key)]),
      finished: [key, ...finished.filter(k => k !== key)].slice(0, MAX_FINISHED)
    }
  }
  return prev
}
// --- reducer:end ---

const FLASH_MS = 5000
const PANE_ID = 'kinocut-renders'

function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)} s`
  return `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`
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

function ProgressBar({ percent }) {
  return jsx('div', {
    style: { height: '4px', borderRadius: '2px', background: 'var(--ui-stroke-secondary)', overflow: 'hidden' },
    children: jsx('div', {
      style: {
        height: '100%',
        width: `${percent === null ? 100 : percent}%`,
        background: 'var(--ui-accent)',
        opacity: percent === null ? 0.4 : 1
      }
    })
  })
}

function RecentList({ items, empty, row }) {
  if (items.length === 0) return [jsx('div', { className: 'text-(--ui-text-tertiary)', children: empty }, 'empty')]
  return items.map(r =>
    row(r.key || r.tool_id, [
      jsxs(
        'div',
        {
          className: 'flex justify-between gap-2',
          children: [
            jsx('span', { children: `${r.status === 'failed' ? '✗' : '✓'} ${r.tool}` }),
            jsx('span', { className: 'text-(--ui-text-secondary)', children: formatDuration(r.durationMs) })
          ]
        },
        'h'
      ),
      r.status === 'failed' ? jsx('div', { className: 'text-(--ui-text-tertiary)', children: 'failed' }, 's') : null,
      r.message ? jsx('div', { className: 'text-(--ui-text-tertiary)', children: r.message }, 'm') : null
    ])
  )
}

function RendersPane({ store }) {
  const { renders } = useStore(store)
  const active = Object.values(renders.active)
  const row = (key, children) =>
    jsx('div', { className: 'flex flex-col gap-1 border-b border-(--ui-stroke-secondary) py-2', children }, key)
  const heading = text => jsx('div', { className: 'font-medium', children: text })
  const done = renders.recent.filter(r => r.kind === 'render')
  const lookups = renders.recent.filter(r => r.kind === 'activity')

  return jsxs('div', {
    className: 'flex h-full flex-col gap-3 overflow-auto p-3 text-sm',
    children: [
      active.length === 0
        ? jsxs('div', {
            className: 'flex flex-col gap-1',
            children: [
              jsx('div', { className: 'font-medium', children: 'Idle' }, 'h'),
              jsx('div', { className: 'text-(--ui-text-tertiary)', children: 'Nothing is running.' }, 't')
            ]
          })
        : [
            heading(active.length === 1 ? 'Running' : `Running (${active.length})`),
            ...active.map(a =>
              row(a.key || a.tool_id, [
                jsxs(
                  'div',
                  {
                    className: 'flex justify-between gap-2',
                    children: [
                      jsx('span', { children: a.tool }),
                      jsx('span', {
                        className: 'text-(--ui-text-secondary)',
                        children: a.percent === null ? '...' : `${a.percent}%`
                      })
                    ]
                  },
                  'h'
                ),
                jsx(ProgressBar, { percent: a.percent }, 'p'),
                a.message ? jsx('div', { className: 'text-(--ui-text-tertiary)', children: a.message }, 'm') : null
              ])
            )
          ],
      heading('Renders'),
      ...RecentList({ items: done, empty: 'No finished renders yet.', row }),
      heading('Activity'),
      ...RecentList({ items: lookups, empty: 'No lookups yet.', row })
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
