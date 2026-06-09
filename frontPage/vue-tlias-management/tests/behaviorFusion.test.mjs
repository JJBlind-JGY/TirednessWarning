import test from 'node:test'
import assert from 'node:assert/strict'
import {
  countContinuousStateRuns,
  summarizeBehaviorSegment,
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

test('closed duration below ten seconds does not reach the fatigue threshold', () => {
  const eyeSamples = [
    ...samples(SEGMENT_START, 10000, 1000, 'closed'),
    { ts: 10500, closed: false }
  ]
  assert.equal(
    summarizeTimedStateSamples(eyeSamples, SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS),
    9500
  )
})

test('closed duration at ten seconds reaches the fatigue threshold', () => {
  const eyeSamples = [
    ...samples(SEGMENT_START, 11000, 1000, 'closed'),
    { ts: 11000, closed: false }
  ]
  assert.equal(
    summarizeTimedStateSamples(eyeSamples, SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS),
    10000
  )
})

test('invalid frame stops the current run without clearing earlier closed time', () => {
  const eyeSamples = [
    ...samples(SEGMENT_START, 6000, 1000, 'closed'),
    { ts: 6000, closed: false },
    ...samples(10000, 15000, 1000, 'closed'),
    { ts: 15000, closed: false }
  ]
  assert.equal(
    summarizeTimedStateSamples(eyeSamples, SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS),
    10000
  )
})

test('stream interruption extends a state by at most one sample gap', () => {
  assert.equal(
    summarizeTimedStateSamples([{ ts: 5000, closed: true }], SEGMENT_START, SEGMENT_END, 'closed', MAX_GAP_MS),
    MAX_GAP_MS
  )
})

test('mouth-open run below three seconds is not a yawn', () => {
  const mouthSamples = [
    { ts: 2000, open: true },
    { ts: 4000, open: true },
    { ts: 4999, open: false }
  ]
  assert.equal(
    countContinuousStateRuns(mouthSamples, SEGMENT_START, SEGMENT_END, 'open', 3000, MAX_GAP_MS),
    0
  )
})

test('continuous mouth-open run at three seconds is one yawn', () => {
  const mouthSamples = [
    { ts: 2000, open: true },
    { ts: 3500, open: true },
    { ts: 5000, open: false }
  ]
  assert.equal(
    countContinuousStateRuns(mouthSamples, SEGMENT_START, SEGMENT_END, 'open', 3000, MAX_GAP_MS),
    1
  )
})

test('behavior summary preserves both eye and mouth results for the segment', () => {
  const result = summarizeBehaviorSegment(
    [...samples(SEGMENT_START, 11000, 1000, 'closed'), { ts: 11000, closed: false }],
    [{ ts: 14000, open: true }, { ts: 17000, open: false }],
    SEGMENT_START,
    SEGMENT_END,
    { maxSampleGapMs: MAX_GAP_MS, yawnHoldMs: 3000 }
  )
  assert.deepEqual(result, { closedMs: 10000, yawnCount: 1 })
})
