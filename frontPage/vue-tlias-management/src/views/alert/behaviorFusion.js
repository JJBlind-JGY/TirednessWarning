export function summarizeTimedStateSamples(
  samplesSource,
  segmentStart,
  segmentEnd,
  stateKey,
  maxGapMs
) {
  let previousSample = null
  const recentSamples = []
  ;[...samplesSource].sort((a, b) => Number(a.ts || 0) - Number(b.ts || 0)).forEach((sample) => {
    const ts = Number(sample.ts)
    if (!Number.isFinite(ts) || ts >= segmentEnd) return
    if (ts < segmentStart) previousSample = sample
    else recentSamples.push(sample)
  })
  const samples = previousSample ? [{ ...previousSample, ts: segmentStart }, ...recentSamples] : recentSamples
  return samples.reduce((duration, sample, index) => {
    if (sample[stateKey] !== true) return duration
    const ts = Number(sample.ts)
    const nextTs = index + 1 < samples.length ? Number(samples[index + 1].ts) : segmentEnd
    const start = Math.max(segmentStart, ts)
    const end = Math.min(segmentEnd, nextTs, ts + maxGapMs)
    return end > start ? duration + (end - start) : duration
  }, 0)
}

export function summarizeMaxContinuousStateDuration(
  samplesSource,
  segmentStart,
  segmentEnd,
  stateKey,
  maxGapMs
) {
  let previousSample = null
  const recentSamples = []
  ;[...samplesSource].sort((a, b) => Number(a.ts || 0) - Number(b.ts || 0)).forEach((sample) => {
    const ts = Number(sample.ts)
    if (!Number.isFinite(ts) || ts >= segmentEnd) return
    if (ts < segmentStart) previousSample = sample
    else recentSamples.push(sample)
  })
  const samples = previousSample ? [{ ...previousSample, ts: segmentStart }, ...recentSamples] : recentSamples
  let maxDuration = 0
  let runStart = null
  let runEnd = null

  const closeRun = () => {
    if (runStart != null && runEnd != null) maxDuration = Math.max(maxDuration, runEnd - runStart)
    runStart = null
    runEnd = null
  }

  samples.forEach((sample, index) => {
    const ts = Number(sample.ts)
    const nextTs = index + 1 < samples.length ? Number(samples[index + 1].ts) : segmentEnd
    const start = Math.max(segmentStart, ts)
    const end = Math.min(segmentEnd, nextTs, ts + maxGapMs)
    if (end <= start || sample[stateKey] !== true) {
      closeRun()
      return
    }
    if (runStart == null || start > runEnd) {
      closeRun()
      runStart = start
    }
    runEnd = Math.max(runEnd ?? end, end)
  })
  closeRun()
  return maxDuration
}

export function countContinuousStateRuns(
  samplesSource,
  segmentStart,
  segmentEnd,
  stateKey,
  minDurationMs,
  maxGapMs
) {
  let previousSample = null
  const recentSamples = []
  ;[...samplesSource].sort((a, b) => Number(a.ts || 0) - Number(b.ts || 0)).forEach((sample) => {
    const ts = Number(sample.ts)
    if (!Number.isFinite(ts) || ts >= segmentEnd) return
    if (ts < segmentStart) previousSample = sample
    else recentSamples.push(sample)
  })
  const samples = previousSample ? [{ ...previousSample, ts: segmentStart }, ...recentSamples] : recentSamples
  let count = 0
  let runStart = null
  let runEnd = null
  let lastTrueTs = null

  const closeRun = (observedEnd = false) => {
    if (runStart != null && runEnd != null && lastTrueTs != null) {
      const observedDuration = lastTrueTs - runStart
      const inferredDuration = runEnd - runStart
      if (observedDuration >= minDurationMs || (observedEnd && inferredDuration >= minDurationMs)) count += 1
    }
    runStart = null
    runEnd = null
    lastTrueTs = null
  }

  samples.forEach((sample, index) => {
    const ts = Number(sample.ts)
    const nextTs = index + 1 < samples.length ? Number(samples[index + 1].ts) : segmentEnd
    const start = Math.max(segmentStart, ts)
    const end = Math.min(segmentEnd, nextTs, ts + maxGapMs)
    if (end <= start) return
    if (sample[stateKey] === true) {
      if (runStart != null && runEnd != null && start > runEnd) closeRun(false)
      if (runStart == null) runStart = start
      runEnd = end
      lastTrueTs = Math.max(start, ts)
      return
    }
    closeRun(runEnd != null && start <= runEnd)
  })
  closeRun(false)
  return count
}

export function summarizeBehaviorSegment(
  eyeSamples,
  mouthSamples,
  segmentStart,
  segmentEnd,
  { maxSampleGapMs, yawnHoldMs }
) {
  return {
    closedMs: summarizeTimedStateSamples(
      eyeSamples,
      segmentStart,
      segmentEnd,
      'closed',
      maxSampleGapMs
    ),
    maxContinuousClosedMs: summarizeMaxContinuousStateDuration(
      eyeSamples,
      segmentStart,
      segmentEnd,
      'closed',
      maxSampleGapMs
    ),
    yawnCount: countContinuousStateRuns(
      mouthSamples,
      segmentStart,
      segmentEnd,
      'open',
      yawnHoldMs,
      maxSampleGapMs
    )
  }
}

export function selectStateWindowSamples(
  samplesSource,
  windowStart,
  windowEnd,
  stateKey,
  scoreKeys = []
) {
  let previousSample = null
  const windowSamples = []
  ;[...samplesSource].sort((a, b) => Number(a.ts || 0) - Number(b.ts || 0)).forEach((sample) => {
    const ts = Number(sample.ts || 0)
    if (!ts || ts >= windowEnd) return
    if (ts < windowStart) previousSample = sample
    else windowSamples.push(sample)
  })
  if (previousSample) windowSamples.unshift({ ...previousSample, ts: windowStart, carriedForward: true })
  return windowSamples.map((sample) => {
    const result = {
      timestamp: Number(sample.ts),
      offsetMs: Number(sample.ts) - windowStart,
      [stateKey]: sample[stateKey] == null ? null : sample[stateKey] === true
    }
    scoreKeys.forEach((key) => { result[key] = Number(sample[key] || 0) })
    if (sample.carriedForward) result.carriedForward = true
    return result
  })
}
