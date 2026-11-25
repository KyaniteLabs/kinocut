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
const {
  reduceRenders,
  initialRenders,
  runKind,
  LOOKUP_TOOLS,
  eventScope,
  isFailedComplete,
  formatDuration,
  effectiveRemainingMs
} = await import(
  'data:text/javascript;base64,' + Buffer.from(block).toString('base64')
)

const T = 'mcp__kinocut__video_trim'
const OK = { result: { success: true } }
const ev = (type, payload, now = 0) => ({ type, payload, now })

test('start -> progress -> complete', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'a', name: T }, 1000))
  assert.equal(s.active.a.tool, 'video_trim')
  assert.equal(s.active.a.percent, null)
  s = reduceRenders(s, ev('progress', { tool_id: 'a', name: T, percent: 42, message: 'encoding' }, 1500))
  assert.equal(s.active.a.percent, 42)
  assert.equal(s.active.a.message, 'encoding')
  s = reduceRenders(s, ev('complete', { tool_id: 'a', name: T, ...OK }, 3500))
  assert.deepEqual(s.active, {})
  assert.equal(s.recent.length, 1)
  assert.equal(s.recent[0].status, 'done')
  assert.equal(s.recent[0].durationMs, 2500)
  assert.equal(s.recent[0].message, 'encoding')
})

test('failure is detected', () => {
  for (const extra of [{ error: 'boom' }, { ok: false }, { is_error: true }, { result: { error: 'x' } }]) {
    let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'f', name: T }))
    s = reduceRenders(s, ev('complete', { tool_id: 'f', name: T, ...extra }))
    assert.equal(s.recent[0].status, 'failed')
  }
})

test('running estimates use advancing progress samples', () => {
  const progress = (percent, now) => ev('progress', { tool_id: 'eta', name: T, percent }, now)
  let s = reduceRenders(initialRenders(), progress(20, 1000))
  assert.equal(s.active.eta.remainingMs, null)
  s = reduceRenders(s, progress(50, 2500))
  assert.equal(s.active.eta.remainingMs, 2500)
  s = reduceRenders(s, progress(100, 5000))
  assert.equal(s.active.eta.remainingMs, null)
})

test('finished renders retain the output size reported by Kinocut', () => {
  const result = JSON.stringify({ result: JSON.stringify({ success: true, size_bytes: 1048576 }) })
  const s = reduceRenders(initialRenders(), ev('complete', { tool_id: 'size', name: T, result }))
  assert.equal(s.recent[0].sizeBytes, 1048576)
})

test('message-only progress retains the last valid percentage and ETA', () => {
  const payload = { tool_id: 'progress', name: T }
  let state = reduceRenders(initialRenders(), ev('progress', { ...payload, percent: 10 }, 0))
  state = reduceRenders(state, ev('progress', { ...payload, percent: 40 }, 1000))
  for (const percent of [undefined, ' ', false, []]) {
    state = reduceRenders(state, ev('progress', { ...payload, percent, message: 'encoding' }, 2000))
    assert.equal(state.active.progress.percent, 40)
    assert.equal(state.active.progress.remainingMs, 2000)
  }
})

test('nested gateway failure retains its cause and never reports an output size', () => {
  const result = JSON.stringify({ is_error: true, content: [{ text: 'render stopped' }], size_bytes: 16 })
  const state = reduceRenders(initialRenders(), ev('complete', { tool_id: 'constructor', name: T, result }))
  const [row] = state.recent
  assert.equal(row.historyId, 1)
  assert.equal(row.status, 'failed')
  assert.equal(row.message, 'render stopped')
  assert.equal(row.sizeBytes, null)
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
  s = reduceRenders(initialRenders(), ev('progress', { tool_id: 'p', name: T, percent: -5 }))
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
  assert.equal(LOOKUP_TOOLS.size, 7)
  assert.equal(runKind('video_direct'), 'activity', 'a plan writes no media')
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

test('completing a reused tool_id preserves each started run in history', () => {
  let s = initialRenders()
  s = reduceRenders(s, ev('start', { tool_id: 'reuse', name: T }, 100))
  s = reduceRenders(s, ev('complete', { tool_id: 'reuse', name: T, summary: 'first', ...OK }, 200))
  s = reduceRenders(s, ev('start', { tool_id: 'reuse', name: T }, 300))
  s = reduceRenders(s, ev('complete', { tool_id: 'reuse', name: T, error: 'second failed' }, 400))

  assert.equal(s.recent.length, 2)
  assert.deepEqual(s.recent.map(r => [r.status, r.message]), [['failed', 'second failed'], ['done', 'first']])
})

test('a duplicate complete for a finished run is not recorded twice', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'dup', name: T }, 100))
  s = reduceRenders(s, ev('complete', { tool_id: 'dup', name: T, summary: 'once' }, 200))
  const after = reduceRenders(s, ev('complete', { tool_id: 'dup', name: T, summary: 'again' }, 300))
  assert.equal(after, s)
  assert.equal(after.recent.length, 1)
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

test('outer failure flag survives unwrapping the inner cause', () => {
  for (const cause of ['Missing source', { message: 'Missing source' }, JSON.stringify({ error: 'Missing source' })]) {
    const result = JSON.stringify({ is_error: true, result: cause })
    const [row] = reduceRenders(initialRenders(), ev('complete', { tool_id: 'f', name: T, result })).recent
    assert.equal(row.status, 'failed')
    assert.equal(row.message, 'Missing source')
  }
})

test('regressive progress cannot undo 100% or revive an ETA', () => {
  let state = initialRenders()
  for (const [percent, now] of [[20, 0], [100, 1000], [95, 1500]]) {
    state = reduceRenders(state, ev('progress', { tool_id: 'p', name: T, percent }, now))
  }
  assert.equal(state.active.p.percent, 100)
  assert.equal(state.active.p.remainingMs, null)
})

test('ETA measures resumed progress from the end of a stall', () => {
  let state = initialRenders()
  for (const [percent, now] of [[10, 0], [40, 1000], [40, 61000], [60, 62000]]) {
    state = reduceRenders(state, ev('progress', { tool_id: 'p', name: T, percent }, now))
  }
  assert.equal(state.active.p.remainingMs, 2000)
})

test('ETA drops silent stall gaps and recovers on resumed forward progress', () => {
  let state = initialRenders()
  for (const [percent, now] of [[10, 0], [40, 1000], [60, 62000]]) {
    state = reduceRenders(state, ev('progress', { tool_id: 'p', name: T, percent }, now))
  }
  assert.equal(state.active.p.remainingMs, null)
  state = reduceRenders(state, ev('progress', { tool_id: 'p', name: T, percent: 80 }, 63000))
  assert.equal(state.active.p.remainingMs, 1000)
})

test('repeated percentages without a stall still accumulate enough progress for an ETA', () => {
  let state = initialRenders()
  const samples = [[10, 0], [10, 500], [20, 1000], [20, 1500], [30, 2000], [30, 2500], [40, 3000]]
  for (const [percent, now] of samples) {
    state = reduceRenders(state, ev('progress', { tool_id: 'p', name: T, percent }, now))
  }
  assert.equal(state.active.p.percent, 40)
  assert.equal(state.active.p.remainingMs, 7000)
})

test('MiB values that overflow in bytes have no display size', () => {
  const result = { size_mb: Number.MAX_VALUE }
  const [row] = reduceRenders(initialRenders(), ev('complete', { tool_id: 's', name: T, result })).recent
  assert.equal(row.sizeBytes, null)
})

test('queued durable job is never labeled done and retains job_id (D7-001/C5-001)', () => {
  const queued = {
    success: true,
    operation: 'repurpose',
    job_id: 'job:123',
    status: 'queued',
    clips: []
  }
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'q1', name: 'mcp__kinocut__video_repurpose' }, 100))
  s = reduceRenders(s, ev('complete', { tool_id: 'q1', name: 'mcp__kinocut__video_repurpose', result: JSON.stringify(queued) }, 250))
  assert.equal(s.recent.length, 1)
  assert.equal(s.recent[0].status, 'queued')
  assert.notEqual(s.recent[0].status, 'done')
  assert.equal(s.recent[0].jobId, 'job:123')
})

test('submitted and running durable job statuses stay distinct from done', () => {
  for (const [wireStatus, expected] of [['submitted', 'submitted'], ['pending', 'queued'], ['running', 'running'], ['in_progress', 'running']]) {
    const result = { success: true, job_id: `job:${wireStatus}`, status: wireStatus }
    let s = reduceRenders(initialRenders(), ev('start', { tool_id: wireStatus, name: T }, 10))
    s = reduceRenders(s, ev('complete', { tool_id: wireStatus, name: T, result }, 20))
    assert.equal(s.recent[0].status, expected)
    assert.equal(s.recent[0].jobId, `job:${wireStatus}`)
  }
})

test('ambiguous completion envelopes never default to done (D7-004)', () => {
  for (const payload of [
    { tool_id: 'u1', name: T },
    { tool_id: 'u2', name: T, result: null },
    { tool_id: 'u3', name: T, result: 'plain text, not JSON' },
    { tool_id: 'u4', name: T, result: {} }
  ]) {
    let s = reduceRenders(initialRenders(), ev('start', { tool_id: payload.tool_id, name: T }, 100))
    s = reduceRenders(s, ev('complete', payload, 200))
    assert.equal(s.recent[0].status, 'unknown', JSON.stringify(payload))
    assert.notEqual(s.recent[0].status, 'done')
  }
})

test('structuredContent failure without outer error flag counts as failed (D7-004)', () => {
  const payload = {
    tool_id: 'sc1',
    name: T,
    result: { structuredContent: { success: false, error: 'codec unsupported' } }
  }
  assert.equal(isFailedComplete(payload), true)
  const [row] = reduceRenders(initialRenders(), ev('complete', payload, 500)).recent
  assert.equal(row.status, 'failed')
  assert.equal(row.message, 'codec unsupported')
})

test('terminal summary takes precedence over stale progress message on done (D7-004)', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'sum', name: T }, 100))
  s = reduceRenders(s, ev('progress', { tool_id: 'sum', name: T, percent: 50, message: 'encoding frame 50' }, 200))
  s = reduceRenders(s, ev('complete', { tool_id: 'sum', name: T, summary: 'Trimmed 12.0s clip', ...OK }, 500))
  assert.equal(s.recent[0].status, 'done')
  assert.equal(s.recent[0].message, 'Trimmed 12.0s clip')
})

test('completed rows retain output artifact paths, review card, directive, and sha256 (D7-009)', () => {
  const result = JSON.stringify({
    success: true,
    output_path: '/renders/cut.mp4',
    size_bytes: 2048,
    preview_directive: '::preview{file="/renders/cut_review_card.html"}',
    plays_inline: true,
    review_card: {
      created: true,
      output_path: '/renders/cut_review_card.html',
      input_sha256: 'a'.repeat(64)
    }
  })
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'art', name: T }, 100))
  s = reduceRenders(s, ev('complete', { tool_id: 'art', name: T, result }, 600))
  const [row] = s.recent
  assert.equal(row.status, 'done')
  assert.equal(row.outputPath, '/renders/cut.mp4')
  assert.equal(row.reviewCardPath, '/renders/cut_review_card.html')
  assert.equal(row.previewDirective, '::preview{file="/renders/cut_review_card.html"}')
  assert.equal(row.playsInline, true)
  assert.equal(row.artifactSha256, 'a'.repeat(64))
})

test('active map is capped and never leaks 500/500 uncapped rows on missing completes (D7-003/C5-002)', () => {
  let s = initialRenders()
  for (let i = 0; i < 500; i++) {
    s = reduceRenders(s, ev('start', { tool_id: `run_${i}`, name: T }, i * 10))
  }
  assert.ok(Object.keys(s.active).length <= 50, `active leaked: ${Object.keys(s.active).length}`)
  assert.ok(s.recent.length > 0, 'evicted rows should surface in recent as stale')
  assert.equal(s.recent[0].status, 'stale')
})

test('nameless complete handles known tool_id and marks unmatched active runs stale + dismissible (D7-003/C5-002)', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'k1', name: T }, 100))
  s = reduceRenders(s, ev('complete', { tool_id: 'k1', result: { success: true, output_path: '/tmp/a.mp4' } }, 200))
  assert.deepEqual(s.active, {})
  assert.equal(s.recent[0].status, 'done')
  assert.equal(s.recent[0].outputPath, '/tmp/a.mp4')

  s = reduceRenders(initialRenders(), ev('start', { tool_id: 'k2', name: T }, 100))
  s = reduceRenders(s, ev('complete', {}, 300))
  assert.equal(s.active.k2.stale, true)
  assert.equal(s.active.k2.status, 'stale')
  assert.equal(s.active.k2.remainingMs, null)

  s = reduceRenders(s, { type: 'dismiss', key: 'k2', now: 400 })
  assert.deepEqual(s.active, {})
})

test('tick and disconnect mark idle/disconnected active entries stale without marking failed (D7-003)', () => {
  let s = reduceRenders(initialRenders(), ev('start', { tool_id: 'idle1', name: T }, 0))
  s = reduceRenders(s, { type: 'tick', now: 10 * 60 * 1000 })
  assert.equal(s.active.idle1.stale, true)
  assert.equal(s.active.idle1.status, 'stale')

  let s2 = reduceRenders(initialRenders(), { type: 'start', payload: { tool_id: 'dc1', name: T }, scope: 's1', now: 0 })
  s2 = reduceRenders(s2, { type: 'disconnect', scope: 's1', now: 5000 })
  assert.equal(s2.active['s1#dc1'].stale, true)
  assert.equal(s2.active['s1#dc1'].status, 'stale')
})

test('ETA expires across unreported stalls and message-only updates (D7-007)', () => {
  const payload = { tool_id: 'stall', name: T }
  let s = reduceRenders(initialRenders(), ev('progress', { ...payload, percent: 10 }, 0))
  s = reduceRenders(s, ev('progress', { ...payload, percent: 40 }, 1000))
  assert.equal(s.active.stall.remainingMs, 2000)
  // At 61s, a message-only progress update must drop the frozen ETA.
  s = reduceRenders(s, ev('progress', { ...payload, message: 'still working' }, 61_000))
  assert.equal(s.active.stall.percent, 40)
  assert.equal(s.active.stall.remainingMs, null)

  // Even without a progress event, effectiveRemainingMs expires in silence.
  let s2 = reduceRenders(initialRenders(), ev('progress', { ...payload, percent: 10 }, 0))
  s2 = reduceRenders(s2, ev('progress', { ...payload, percent: 40 }, 1000))
  assert.equal(effectiveRemainingMs(s2.active.stall, 2000), 2000)
  assert.equal(effectiveRemainingMs(s2.active.stall, 61_000), null)

  // Start-less completion without duration_s records null duration instead of 0 ms.
  const [row] = reduceRenders(initialRenders(), ev('complete', { tool_id: 'nodur', name: T, ...OK }, 5000)).recent
  assert.equal(row.durationMs, null)
})

test('formatDuration never renders 1 m 60 s or 60.0 s at rollover boundaries (D7-026)', () => {
  assert.equal(formatDuration(0), '0 ms')
  assert.equal(formatDuration(999.6), '1.0 s')
  assert.equal(formatDuration(59_940), '59.9 s')
  assert.equal(formatDuration(59_950), '1 m 0 s')
  assert.equal(formatDuration(60_000), '1 m 0 s')
  assert.equal(formatDuration(119_400), '1 m 59 s')
  assert.equal(formatDuration(119_600), '2 m 0 s')
  assert.equal(formatDuration(null), '')
  assert.equal(formatDuration(-5), '')
})
