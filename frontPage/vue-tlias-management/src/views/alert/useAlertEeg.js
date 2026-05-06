import * as echarts from 'echarts'

const RAW_WAVE_LIMIT = 512
const WAVE_SMOOTH_WINDOW = 5
const WAVE_DISPLAY_RANGE = 100
const EMOTION_TEXT = {
  normal: '正常',
  anxiety: '焦虑',
  stress: '紧张',
  fatigue: '疲劳',
  weakness: '虚弱'
}
const BAND_NAMES = ['delta', 'theta', 'alpha', 'beta', 'gamma']
const BAND_LABELS = ['Delta', 'Theta', 'Alpha', 'Beta', 'Gamma']
const DEFAULT_BAND_SNAPSHOT = { delta: 0, theta: 0, alpha: 0, beta: 0, gamma: 0 }
const DEFAULT_INDICES = { anxiety_idx: 0, stress_idx: 0, fatigue_idx: 0, weakness_idx: 0 }
const EEG_RETRY_DELAY_MS = 2000

export function createEegMonitor({ state, getBindingById, getDeviceLabel, evaluateWarning, updateFusionState }) {
  const waveChartRefs = new Map()
  const waveChartInstances = new Map()
  const bandChartRefs = new Map()
  const bandChartInstances = new Map()
  const workerStreams = new Map()
  const retryTimers = new Map()

  function getBandSnapshot(rawPowers = {}) {
    const delta = Number(rawPowers.delta || 0)
    const theta = Number(rawPowers.theta || 0)
    const alpha = Number(rawPowers.low_alpha || 0) + Number(rawPowers.high_alpha || 0)
    const beta = Number(rawPowers.low_beta || 0) + Number(rawPowers.high_beta || 0)
    const gamma = Number(rawPowers.low_gamma || 0) + Number(rawPowers.mid_gamma || 0)
    const total = delta + theta + alpha + beta + gamma
    if (!total) return { delta: 0, theta: 0, alpha: 0, beta: 0, gamma: 0 }
    return {
      delta: (delta / total) * 100,
      theta: (theta / total) * 100,
      alpha: (alpha / total) * 100,
      beta: (beta / total) * 100,
      gamma: (gamma / total) * 100
    }
  }

  function smoothWaveSamples(samples) {
    return samples.map((_, index) => {
      const start = Math.max(0, index - WAVE_SMOOTH_WINDOW + 1)
      const window = samples.slice(start, index + 1)
      return window.reduce((sum, value) => sum + value, 0) / window.length
    })
  }

  function normalizeWaveChunk(binding, rawWave = []) {
    const numericSamples = rawWave.map(Number).filter(Number.isFinite)
    if (!numericSamples.length) return []
    const smoothed = smoothWaveSamples(numericSamples)
    const mean = smoothed.reduce((sum, value) => sum + value, 0) / smoothed.length
    const centered = smoothed.map((value) => value - mean)
    const peak = centered.reduce((max, value) => Math.max(max, Math.abs(value)), 0)
    if (!peak) return centered.map(() => 0)
    binding.waveScale = binding.waveScale > 0 ? binding.waveScale * 0.82 + peak * 0.18 : peak
    const scale = Math.max(binding.waveScale, 1)
    return centered.map((value) => Number((Math.tanh((value / scale) * 1.6) * WAVE_DISPLAY_RANGE).toFixed(2)))
  }

  function getWaveChartOption(binding) {
    return {
      color: ['#0f766e'],
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 24, bottom: 28 },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#9db4c0' } },
        data: binding.rawWaveBuffer.map((_, index) => index)
      },
      yAxis: {
        type: 'value',
        min: -WAVE_DISPLAY_RANGE,
        max: WAVE_DISPLAY_RANGE,
        axisLine: { show: false },
        splitLine: { lineStyle: { color: '#e6eef2' } }
      },
      series: [{
        name: 'EEG raw wave',
        type: 'line',
        showSymbol: false,
        smooth: true,
        sampling: 'lttb',
        animation: false,
        lineStyle: { width: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(15, 118, 110, 0.28)' },
            { offset: 1, color: 'rgba(15, 118, 110, 0.02)' }
          ])
        },
        data: [...binding.rawWaveBuffer]
      }]
    }
  }

  function getBandChartOption(binding) {
    const values = BAND_NAMES.map((name) => Number(binding.bandSnapshot[name] || 0).toFixed(1))
    return {
      tooltip: { trigger: 'item' },
      radar: {
        radius: '62%',
        center: ['50%', '56%'],
        splitNumber: 5,
        axisName: { color: '#325064' },
        splitArea: { areaStyle: { color: ['rgba(13,148,136,0.04)', 'rgba(13,148,136,0.08)'] } },
        splitLine: { lineStyle: { color: 'rgba(80,117,136,0.18)' } },
        axisLine: { lineStyle: { color: 'rgba(80,117,136,0.18)' } },
        indicator: BAND_LABELS.map((label) => ({ name: label, max: 100 }))
      },
      series: [{
        type: 'radar',
        data: [{
          value: values,
          name: 'EEG band ratio',
          symbol: 'circle',
          symbolSize: 7,
          lineStyle: { color: '#0f766e', width: 2 },
          itemStyle: { color: '#14b8a6' },
          areaStyle: { color: 'rgba(20,184,166,0.24)' }
        }]
      }]
    }
  }

  function ensureChartInstance(refMap, instanceMap, bindingId, optionFactory) {
    const el = refMap.get(bindingId)
    if (!el) return null
    let instance = instanceMap.get(bindingId)
    if (instance && instance.getDom() !== el) {
      instance.dispose()
      instanceMap.delete(bindingId)
      instance = null
    }
    if (!instance) {
      instance = echarts.init(el)
      instanceMap.set(bindingId, instance)
    }
    const binding = getBindingById(bindingId)
    if (binding) {
      instance.setOption(optionFactory(binding))
      instance.resize()
    }
    return instance
  }

  function ensureWaveChart(binding) {
    return ensureChartInstance(waveChartRefs, waveChartInstances, binding.id, getWaveChartOption)
  }

  function ensureBandChart(binding) {
    return ensureChartInstance(bandChartRefs, bandChartInstances, binding.id, getBandChartOption)
  }

  function refreshWaveChart(binding) {
    const instance = waveChartInstances.get(binding.id) || ensureWaveChart(binding)
    if (!instance) return
    instance.setOption({
      xAxis: { data: binding.rawWaveBuffer.map((_, index) => index) },
      yAxis: { min: -WAVE_DISPLAY_RANGE, max: WAVE_DISPLAY_RANGE },
      series: [{ data: [...binding.rawWaveBuffer] }]
    })
    instance.resize()
  }

  function refreshBandChart(binding) {
    const instance = bandChartInstances.get(binding.id) || ensureBandChart(binding)
    if (!instance) return
    instance.setOption({
      series: [{ data: [{ value: BAND_NAMES.map((name) => Number(binding.bandSnapshot[name] || 0).toFixed(1)) }] }]
    })
    instance.resize()
  }

  function disposeChart(bindingId) {
    const waveInstance = waveChartInstances.get(bindingId)
    if (waveInstance) waveInstance.dispose()
    waveChartInstances.delete(bindingId)
    const bandInstance = bandChartInstances.get(bindingId)
    if (bandInstance) bandInstance.dispose()
    bandChartInstances.delete(bindingId)
  }

  function setWaveChartRef(bindingId) {
    return (el) => {
      if (!el) {
        disposeChart(bindingId)
        waveChartRefs.delete(bindingId)
        return
      }
      waveChartRefs.set(bindingId, el)
      const binding = getBindingById(bindingId)
      if (binding) ensureWaveChart(binding)
    }
  }

  function setBandChartRef(bindingId) {
    return (el) => {
      if (!el) {
        const instance = bandChartInstances.get(bindingId)
        if (instance) instance.dispose()
        bandChartInstances.delete(bindingId)
        bandChartRefs.delete(bindingId)
        return
      }
      bandChartRefs.set(bindingId, el)
      const binding = getBindingById(bindingId)
      if (binding) ensureBandChart(binding)
    }
  }

  function appendRawWave(binding, rawWave = []) {
    if (!Array.isArray(rawWave) || !rawWave.length) return
    const samples = normalizeWaveChunk(binding, rawWave)
    if (!samples.length) return
    binding.rawWaveBuffer.push(...samples)
    if (binding.rawWaveBuffer.length > RAW_WAVE_LIMIT) {
      binding.rawWaveBuffer.splice(0, binding.rawWaveBuffer.length - RAW_WAVE_LIMIT)
    }
  }

  function clearCurrentEegPrediction(binding) {
    binding.lastValidEegEmotion = ''
    binding.lastValidEegAt = 0
    binding.eegFusionCandidate = ''
    binding.eegFusionStreak = 0
  }

  function resetEegState(binding, { status = 'idle', statusText = '等待脑电数据' } = {}) {
    binding.eegRunning = false
    binding.activeWorkerId = null
    binding.eegStatus = status
    binding.eegStatusText = statusText
    binding.eegEmotion = ''
    binding.eegEmotionZh = ''
    binding.eegQualityLevel = ''
    binding.signalQuality = null
    binding.reasonCodes = []
    binding.features = {}
    binding.indices = { ...DEFAULT_INDICES }
    binding.probs = {}
    binding.calibrationProgress = 0
    binding.analysisTime = ''
    binding.bandSnapshot = { ...DEFAULT_BAND_SNAPSHOT }
    binding.rawWaveBuffer = []
    binding.waveScale = 1
    clearCurrentEegPrediction(binding)
    refreshWaveChart(binding)
    refreshBandChart(binding)
    updateFusionState?.(binding)
    evaluateWarning(binding)
  }

  function updateEegData(binding, payload) {
    const status = payload.status || 'ok'
    const statusText = payload.message || payload.error || ''
    const offlineStatuses = new Set(['offline', 'error', 'reconnecting'])
    if (offlineStatuses.has(status)) {
      const retryWorkerId = payload.workerId ?? binding.activeWorkerId ?? binding.workerId
      resetEegState(binding, {
        status,
        statusText: statusText || (status === 'error' ? '脑电连接失败，自动重连中' : '脑电离线，自动重连中')
      })
      if (retryWorkerId != null) scheduleWorkerRetry(retryWorkerId)
      return
    }

    const hasRawWave = Array.isArray(payload.raw_wave) && payload.raw_wave.length > 0
    const hasRawPowers = payload.raw_powers && Object.keys(payload.raw_powers).length > 0
    const isStatusOnlyPayload = ['connecting', 'online'].includes(status)
      && !payload.analysis_time
      && !payload.emotion
      && !hasRawWave
      && !hasRawPowers

    if (isStatusOnlyPayload) {
      binding.eegRunning = true
      binding.eegStatus = status
      binding.eegStatusText = status === 'connecting' ? '脑电连接中' : '在线，等待脑电数据'
      updateFusionState?.(binding)
      evaluateWarning(binding)
      return
    }

    binding.eegStatus = payload.status || 'ok'
    binding.analysisTime = payload.analysis_time || new Date().toISOString()
    binding.eegEmotion = payload.emotion || 'normal'
    binding.eegEmotionZh = payload.emotion_zh || EMOTION_TEXT[binding.eegEmotion] || EMOTION_TEXT.normal
    binding.eegQualityLevel = payload.quality_level || ''
    binding.signalQuality = payload.signal_quality ?? null
    binding.reasonCodes = Array.isArray(payload.reason_codes) ? payload.reason_codes : []
    binding.features = payload.features || {}
    binding.indices = {
      anxiety_idx: Number(payload.indices?.anxiety_idx || 0),
      stress_idx: Number(payload.indices?.stress_idx || 0),
      fatigue_idx: Number(payload.indices?.fatigue_idx || 0),
      weakness_idx: Number(payload.indices?.weakness_idx || 0)
    }
    binding.probs = payload.probs || {}
    binding.calibrationProgress = Number(payload.calibration_progress || 0)
    binding.bandSnapshot = getBandSnapshot(payload.raw_powers)
    appendRawWave(binding, payload.raw_wave)

    if (payload.status === 'ok' && payload.valid_current === true) {
      binding.lastValidEegEmotion = binding.eegEmotion
      binding.lastValidEegAt = Date.now()
    } else {
      clearCurrentEegPrediction(binding)
    }

    if (payload.status === 'no_contact' || payload.quality_level === 'no_contact') {
      binding.eegStatusText = '设备在线，等待佩戴'
    } else if (payload.status === 'calibrating') {
      binding.eegStatusText = `校准中 ${Math.round(binding.calibrationProgress * 100)}%`
    } else if (payload.status === 'poor_signal') {
      binding.eegStatusText = '信号质量不佳'
    } else {
      binding.eegStatusText = '在线'
    }

    updateFusionState?.(binding)
    refreshWaveChart(binding)
    refreshBandChart(binding)
    evaluateWarning(binding)
  }

  function resetWaveState(binding) {
    binding.rawWaveBuffer = []
    binding.waveScale = 1
    binding.bandSnapshot = { ...DEFAULT_BAND_SNAPSHOT }
    refreshWaveChart(binding)
    refreshBandChart(binding)
  }

  function getWorkerStream(workerId) {
    return workerStreams.get(workerId)
  }

  function clearWorkerRetry(workerId) {
    const timer = retryTimers.get(workerId)
    if (!timer) return
    window.clearTimeout(timer)
    retryTimers.delete(workerId)
  }

  function scheduleWorkerRetry(workerId) {
    if (retryTimers.has(workerId)) return
    const timer = window.setTimeout(() => {
      retryTimers.delete(workerId)
      ensureWorkerMonitor(workerId)
    }, EEG_RETRY_DELAY_MS)
    retryTimers.set(workerId, timer)
  }

  function resetStreamBindings(streamState, statusText, { retry = true } = {}) {
    let shouldRetry = false
    const bindingIds = Array.from(streamState.bindingIds)
    bindingIds.forEach((bindingId) => {
      const binding = getBindingById(bindingId)
      if (!binding || binding.activeWorkerId !== streamState.workerId) return
      resetEegState(binding, { status: 'error', statusText })
      if (retry) shouldRetry = true
    })
    streamState.bindingIds.clear()
    if (shouldRetry) scheduleWorkerRetry(streamState.workerId)
  }

  async function openWorkerStream(workerId) {
    const controller = new AbortController()
    const streamState = { workerId, controller, bindingIds: new Set(), lastPayload: null }
    workerStreams.set(workerId, streamState)

    try {
      const response = await fetch(`/eeg/stream?workerId=${workerId}`, { method: 'GET', signal: controller.signal })
      if (!response.ok || !response.body) throw new Error(`EEG stream error: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          resetStreamBindings(streamState, '脑电连接已断开')
          break
        }
        buffer += decoder.decode(value, { stream: true })
        while (buffer.includes('\n\n')) {
          const splitIndex = buffer.indexOf('\n\n')
          const block = buffer.slice(0, splitIndex)
          buffer = buffer.slice(splitIndex + 2)
          const dataLine = block.split('\n').map((line) => line.trim()).find((line) => line.startsWith('data:'))
          if (!dataLine) continue
          const payload = JSON.parse(dataLine.slice(5).trim())
          streamState.lastPayload = payload
          streamState.bindingIds.forEach((bindingId) => {
            const binding = getBindingById(bindingId)
            if (binding?.eegRunning) updateEegData(binding, payload)
          })
        }
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        resetStreamBindings(streamState, '脑电连接失败')
      }
    } finally {
      if (workerStreams.get(workerId) === streamState) workerStreams.delete(workerId)
    }
  }

  function subscribeBindingToWorker(binding) {
    let streamState = getWorkerStream(binding.workerId)
    if (!streamState) {
      void openWorkerStream(binding.workerId)
      streamState = getWorkerStream(binding.workerId)
    }
    binding.activeWorkerId = binding.workerId
    binding.eegRunning = true
    clearWorkerRetry(binding.workerId)
    streamState?.bindingIds.add(binding.id)
    if (streamState?.lastPayload) updateEegData(binding, streamState.lastPayload)
  }

  function unsubscribeBindingFromWorker(binding) {
    const targetWorkerId = binding.activeWorkerId ?? binding.workerId
    const streamState = getWorkerStream(targetWorkerId)
    binding.activeWorkerId = null
    if (!streamState) return
    streamState.bindingIds.delete(binding.id)
    if (streamState.bindingIds.size === 0) {
      streamState.controller.abort()
      workerStreams.delete(targetWorkerId)
    }
  }

  function ensureWorkerMonitor(workerId) {
    if (workerId == null) return
    const bindings = state.bindings.filter((binding) => binding.workerId === workerId && binding.personId)
    if (!bindings.length) return

    const existingStream = getWorkerStream(workerId)
    if (existingStream) {
      clearWorkerRetry(workerId)
      bindings.forEach((binding) => {
        binding.activeWorkerId = workerId
        binding.eegRunning = true
        existingStream.bindingIds.add(binding.id)
        if (existingStream.lastPayload) updateEegData(binding, existingStream.lastPayload)
      })
      return
    }

    bindings.forEach((binding) => {
      binding.eegStatus = 'connecting'
      binding.eegStatusText = '连接中'
      binding.activeWorkerId = workerId
      binding.eegRunning = true
      refreshWaveChart(binding)
      refreshBandChart(binding)
    })
    subscribeBindingToWorker(bindings[0])
    const streamState = getWorkerStream(workerId)
    bindings.slice(1).forEach((binding) => {
      binding.activeWorkerId = workerId
      binding.eegRunning = true
      streamState?.bindingIds.add(binding.id)
      if (streamState?.lastPayload) updateEegData(binding, streamState.lastPayload)
    })
  }

  function stopEeg(bindingId, reason = 'manual') {
    const binding = getBindingById(bindingId)
    if (!binding) return
    unsubscribeBindingFromWorker(binding)
    resetEegState(binding, { status: 'idle', statusText: '等待脑电数据' })
  }

  function ensureCharts(bindings) {
    bindings.forEach((binding) => {
      ensureWaveChart(binding)
      ensureBandChart(binding)
    })
  }

  function canAutoStart(binding) {
    return Boolean(binding?.personId && binding.workerId != null)
  }

  function ensureAutoEeg(binding) {
    if (!canAutoStart(binding)) return
    ensureWorkerMonitor(binding.workerId)
  }

  function ensureAllAutoEeg() {
    const workerIds = new Set(state.bindings.filter(canAutoStart).map((binding) => binding.workerId))
    workerIds.forEach((workerId) => ensureWorkerMonitor(workerId))
  }

  function resizeCharts() {
    waveChartInstances.forEach((instance) => instance.resize())
    bandChartInstances.forEach((instance) => instance.resize())
  }

  return {
    setChartRef: setWaveChartRef,
    setBandChartRef,
    stopEeg,
    ensureAutoEeg,
    ensureAllAutoEeg,
    disposeChart,
    ensureCharts,
    resizeCharts
  }
}

