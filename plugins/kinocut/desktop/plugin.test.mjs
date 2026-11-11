// node --test plugins/kinocut/desktop/plugin.test.mjs
// plugin.js imports the Hermes SDK (unresolvable here), so load only the marked pure reducer block.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const src = readFileSync(new URL('./plugin.js', import.meta.url), 'utf8')
const begin = src.indexOf('// --- reducer:begin')
const end = src.indexOf('// --- reducer:end')
assert.ok(begin >= 0 && end > begin, 'reducer markers present')
const block = src.slice(begin, end)
const { reduceRenders, initialRenders, runKind, LOOKUP_TOOLS, eventScope, isFailedComplete } = await import(
  'data:text/javascript;base64,' + Buffer.from(block).toString('base64')
)

const T = 'mcp__kinocut__video_trim'
const ev = (type, payload, now = 0) => ({ type, payload, now })

test('start -> progress -> complete', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'a', name: T }, 1000))
  assert.equal(s.active.a.tool, 'video_trim')
  assert.equal(s.active.a.percent, null)
  s = reduceRenders(s, ev('progress', { tool_id: 'a', name: T, percent: 42, message: 'encoding' }, 1500))
  assert.equal(s.active.a.percent, 42)
  assert.equal(s.active.a.message, 'encoding')
  s = reduceRenders(s, ev('complete', { tool_id: 'a', name: T }, 3500))
  assert.deepEqual(s.active, {})
  assert.equal(s.recent.length, 1)
  assert.equal(s.recent[0].status, 'done')
  assert.equal(s.recent[0].durationMs, 2500)
  assert.equal(s.recent[0].message, 'encoding')
})

test('failure is detected', () => {
  for (const extra of [{ error: 'boom' }, { ok: false }, { result: { error: 'x' } }]) {
    let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'f', name: T }))
    s = reduceRenders(s, ev('complete', { tool_id: 'f', name: T, ...extra }))
    assert.equal(s.recent[0].status, 'failed')
  }
})

test('non-Kinocut tools are ignored', () => {
  const s0 = initialRenders()
  assert.equal(reduceRenders(s0, ev('start', { tool_id: 'x', name: 'mcp__other__render' })), s0)
  assert.equal(reduceRenders(s0, ev('start', { tool_id: 'x', name: 'terminal' })), s0)
  assert.equal(reduceRenders(s0, ev('start', { tool_id: 'x' })), s0)
})

test('kinocut matching: kinocut MCP server (any case), or a bare video_/audio_/kinocut tool', () => {
  for (const name of ['mcp__KinoCut__anything', 'mcp__kinocut-dev__video_info', 'video_info', 'audio_ops', 'kinocut_do']) {
    const s = reduceRenders(initialRenders(), ev('start', { tool_id: 'k', name }))
    assert.ok(s.active.k, name)
  }
})

test('recent is capped at 10, newest first', () => {
  let s = initialRenders()
  for (let i = 0; i < 15; i++) {
    s = reduceRenders(s, ev('start', { tool_id: `t${i}`, name: T }, i))
    s = reduceRenders(s, ev('complete', { tool_id: `t${i}`, name: T }, i + 1))
  }
  assert.equal(s.recent.length, 10)
  assert.equal(s.recent[0].tool_id, 't14')
  assert.equal(s.recent[9].tool_id, 't5')
})

test('percent is clamped to 0-100', () => {
  let s = reduceRenders(initialRenders(), ev('progress', { tool_id: 'p', name: T, percent: 250 }))
  assert.equal(s.active.p.percent, 100)
  s = reduceRenders(s, ev('progress', { tool_id: 'p', name: T, percent: -5 }))
  assert.equal(s.active.p.percent, 0)
  s = reduceRenders(s, ev('progress', { tool_id: 'p', name: T, percent: null }))
  assert.equal(s.active.p.percent, 0, 'null keeps the last known percent')
})

test('reducer does not mutate its input', () => {
  const s0 = reduceRenders(initialRenders(), ev('start', { tool_id: 'm', name: T }))
  const snap = JSON.stringify(s0)
  reduceRenders(s0, ev('complete', { tool_id: 'm', name: T }))
  assert.equal(JSON.stringify(s0), snap)
})

test('another MCP server with video_ tools is ignored', () => {
  const s = reduceRenders(initialRenders(), { type: 'start', payload: { tool_id: 'x', name: 'mcp__othervideo__video_trim' } })
  assert.equal(Object.keys(s.active).length, 0)
})

test('kinocut error objects show their message', () => {
  let s = reduceRenders(initialRenders(), { type: 'start', payload: { tool_id: 'e', name: 'mcp__kinocut__video_trim' } })
  s = reduceRenders(s, { type: 'complete', payload: { tool_id: 'e', name: 'mcp__kinocut__video_trim', result: { success: false, error: { message: 'bad range' } } } })
  assert.equal(s.recent[0].status, 'failed')
  assert.equal(s.recent[0].message, 'bad range')
})

test('lookups are tagged activity, everything else render', () => {
  assert.equal(runKind('video_info'), 'activity')
  assert.equal(runKind('search_tools'), 'activity')
  assert.equal(runKind('video_trim'), 'render')
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'l', name: 'mcp__kinocut__video_info' }))
  s = reduceRenders(s, ev('complete', { tool_id: 'l', name: 'mcp__kinocut__video_info' }))
  s = reduceRenders(s, ev('start', { tool_id: 'r', name: T }))
  s = reduceRenders(s, ev('complete', { tool_id: 'r', name: T }))
  assert.deepEqual(s.recent.map(r => [r.tool, r.kind]), [['video_trim', 'render'], ['video_info', 'activity']])
})

test('a burst of lookups never pushes renders out of recent', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'r', name: T }))
  s = reduceRenders(s, ev('complete', { tool_id: 'r', name: T }))
  for (let i = 0; i < 25; i++) {
    s = reduceRenders(s, ev('start', { tool_id: `l${i}`, name: 'mcp__kinocut__video_info' }))
    s = reduceRenders(s, ev('complete', { tool_id: `l${i}`, name: 'mcp__kinocut__video_info' }))
  }
  assert.equal(s.recent.filter(r => r.kind === 'activity').length, 10)
  assert.deepEqual(s.recent.filter(r => r.kind === 'render').map(r => r.tool_id), ['r'])
  assert.equal(LOOKUP_TOOLS.size, 6)
})

test('the same tool_id in two sessions stays two rows', () => {
  const a = eventScope({ profile: 'p', connectionId: 'c1', session_id: 's1' })
  const b = eventScope({ profile: 'p', connectionId: 'c1', session_id: 's2' })
  assert.notEqual(a, b)
  let s = reduceRenders(initialRenders(), { type: 'start', payload: { tool_id: 'call_1', name: T }, scope: a })
  s = reduceRenders(s, { type: 'start', payload: { tool_id: 'call_1', name: T }, scope: b })
  assert.equal(Object.keys(s.active).length, 2)
  s = reduceRenders(s, { type: 'complete', payload: { tool_id: 'call_1', name: T }, scope: a })
  assert.equal(Object.keys(s.active).length, 1, 'completing one session leaves the other running')
  assert.equal(Object.values(s.active)[0].key, `${b}#call_1`)
})

test('progress that arrives after complete does not bring the run back', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'z', name: T }))
  s = reduceRenders(s, ev('complete', { tool_id: 'z', name: T }))
  const after = reduceRenders(s, ev('progress', { tool_id: 'z', name: T, percent: 80 }))
  assert.equal(after, s)
  assert.deepEqual(after.active, {})
})

test('a reused tool_id starts a fresh run after the earlier run completed', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'reuse', name: T }, 100))
  s = reduceRenders(s, ev('complete', { tool_id: 'reuse', name: T }, 200))
  s = reduceRenders(s, ev('start', { tool_id: 'reuse', name: T }, 300))

  assert.equal(s.active.reuse.startedAt, 300)
  assert.equal(s.recent.length, 1)
  assert.equal(s.recent[0].durationMs, 100)
})

test('a Hermes text-wrapped failure counts as failed', () => {
  const inner = JSON.stringify({ success: false, error: 'Output path already exists' })
  for (const result of [inner, JSON.stringify({ result: inner }), { result: inner }]) {
    assert.equal(isFailedComplete({ result }), true, JSON.stringify(result))
    let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'w', name: T }))
    s = reduceRenders(s, ev('complete', { tool_id: 'w', name: T, result }))
    assert.equal(s.recent[0].status, 'failed')
    assert.equal(s.recent[0].message, 'Output path already exists')
  }
  assert.equal(isFailedComplete({ result: JSON.stringify({ success: true, output: 'x.mp4' }) }), false)
  assert.equal(isFailedComplete({ result: 'plain text, not JSON' }), false)
})

test('an MCP isError result counts as failed', () => {
  assert.equal(isFailedComplete({ result: { isError: true, content: [{ type: 'text', text: 'nope' }] } }), true)
})
