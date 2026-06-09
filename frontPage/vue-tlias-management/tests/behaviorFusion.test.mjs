import test from 'node:test'
import assert from 'node:assert/strict'
import {
  countContinuousStateRuns,
  selectStateWindowSamples,
  summarizeBehaviorSegment,
  summarizeMaxContinuousStateDuration,
  summarizeTimedStateSamples
} from '../src/views/alert/behaviorFusion.js'

const SEGMENT_START = 1000
const SEGMENT_END = 21000
const MAX_GAP_MS = 3500

function samples(start, end, interval, key, value = true) {
  const result = []
  for (let ts = start; ts <= end; ts += interval) result.push({ ts, [key]: value })
  return result
}

test('continuous eye closure below eight seconds does not reach the fatigue threshold', () => {
  const eyeSamples = [
    ...samples(SEGMENT_START, 8000, 1000, 'closed'),
    { ts: 8999, closed: false }
  ]
  assert.equal(
    summarizeMaxContinuousStateDuration(eyeSamples, SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS),
    7999
  )
})

test('continuous eye closure at eight seconds reaches the fatigue threshold', () => {
  const eyeSamples = [
    ...samples(SEGMENT_START, 9000, 1000, 'closed'),
    { ts: 9000, closed: false }
  ]
  assert.equal(
    summarizeMaxContinuousStateDuration(eyeSamples, SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS),
    8000
  )
})

test('separate eye closures are not accumulated into the continuous threshold', () => {
  const eyeSamples = [
    ...samples(SEGMENT_START, 6000, 1000, 'closed'),
    { ts: 6000, closed: false },
    ...samples(10000, 15000, 1000, 'closed'),
    { ts: 15000, closed: false }
  ]
  assert.equal(
    summarizeMaxContinuousStateDuration(eyeSamples, SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS),
    5000
  )
  assert.equal(summarizeTimedStateSamples(eyeSamples, SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS), 10000)
})

test('stream interruption extends a state by at most one sample gap', () => {
  assert.equal(
    summarizeTimedStateSamples([{ ts: 5000, closed: true }], SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS),
    MAX_GAP_MS
  )
})

test('mouth-open run below five seconds is not a yawn', () => {
  const mouthSamples = [
    { ts: 2000, open: true },
    { ts: 4000, open: true },
    { ts: 6999, open: false }
  ]
  assert.equal(
    countContinuousStateRuns(mouthSamples, SEGMENT_START, SEGMENT_END, 'open', 5000, MAX_GAP_MS),
    0
  )
})

test('continuous mouth-open run at five seconds is one yawn', () => {
  const mouthSamples = [
    { ts: 2000, open: true },
    { ts: 4500, open: true },
    { ts: 7000, open: false }
  ]
  assert.equal(
    countContinuousStateRuns(mouthSamples, SEGMENT_START, SEGMENT_END, 'open', 5000, MAX_GAP_MS),
    1
  )
})

test('behavior summary preserves both eye and mouth results for the segment', () => {
  const result = summarizeBehaviorSegment(
    [...samples(SEGMENT_START, 11000, 1000, 'closed'), { ts: 11000, closed: false }],
    [{ ts: 14000, open: true }, { ts: 16500, open: true }, { ts: 19000, open: false }],
    SEGMENT_START,
    SEGMENT_END,
    { maxSampleGapMs: MAX_GAP_MS, yawnHoldMs: 5000 }
  )
  assert.deepEqual(result, { closedMs: 10000, maxContinuousClosedMs: 10000, yawnCount: 1 })
})

test('diagnostic sample window contains only the fatigue decision window', () => {
  const result = selectStateWindowSamples(
    [
      { ts: 500, closed: false, closedScore: 10 },
      { ts: 1000, closed: true, closedScore: 90 },
      { ts: 20000, closed: true, closedScore: 95 },
      { ts: 21000, closed: false, closedScore: 5 }
    ],
    SEGMENT_START,
    SEGMENT_END,
    'closed',
    ['closedScore']
  )
  assert.deepEqual(result, [
    { timestamp: 1000, offsetMs: 0, closed: false, closedScore: 10, carriedForward: true },
    { timestamp: 1000, offsetMs: 0, closed: true, closedScore: 90 },
    { timestamp: 20000, offsetMs: 19000, closed: true, closedScore: 95 }
  ])
})
