// src/stores/eeg.js
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

/*
const legacyUseEegStore = defineStore('eeg-legacy', () => {
  // --- 状态 ---
  const rawWave      = ref([])
  const fatigueIndex = ref(0)
  const deltaPower   = ref(0)
  const thetaPower   = ref(0)
  const alphaPower   = ref(0)
  const betaPower    = ref(0)
  const fatigueLevel = ref('')
  const accuracy     = ref(0)
  const recordHistory = ref([])

  // --- 历史记录 ---
  watch(fatigueIndex, val => {
    recordHistory.value.push({
      timestamp: new Date().toLocaleTimeString(),
      value: val,
      level: fatigueLevel.value
    })
    if (recordHistory.value.length > 10)
      recordHistory.value.shift()
  })

  let evt = null
  let reconnectTimer = null

  // --- 启动 SSE ---
  function startSse({ port }) {
    if (!port) {
      console.warn('[SSE] 缺少 port 参数')
      return
    }

    stopSse() // 避免重复连接
    const url = `/eeg/stream?port=${encodeURIComponent(port)}`
    console.log('[SSE] 连接:', url)

    evt = new EventSource(url)

    evt.onopen = () => {
      console.log('[SSE] 已连接')
      clearTimeout(reconnectTimer)
    }

    evt.onmessage = e => {
      try {
        const d = JSON.parse(e.data)
        rawWave.value      = d.rawWave || []
        fatigueIndex.value = d.fatigueIndex || 0
        deltaPower.value   = (d.deltaPower ?? 0) * 100
        thetaPower.value   = (d.thetaPower ?? 0) * 100
        alphaPower.value   = (d.alphaPower ?? 0) * 100
        betaPower.value    = (d.betaPower  ?? 0) * 100
        fatigueLevel.value = d.fatigueLevel || ''
        accuracy.value     = d.acc ?? 0
      } catch (err) {
        console.warn('[SSE] 数据解析失败:', err)
      }
    }

    evt.onerror = err => {
      console.warn('[SSE] 连接错误:', err)
      evt.close()
      evt = null
      scheduleReconnect(port)
    }
  }

  // --- 自动重连 ---
  function scheduleReconnect(port) {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      console.log('[SSE] 正在重连...')
      startSse({ port })
    }, 5000)
  }

  // --- 关闭 SSE ---
  function stopSse() {
    if (evt) {
      evt.close()
      evt = null
    }
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  return {
    rawWave,
    fatigueIndex,
    deltaPower,
    thetaPower,
    alphaPower,
    betaPower,
    fatigueLevel,
    recordHistory,
    accuracy,
    startSse,
    stopSse
  }
})
*/

const EMOTION_TEXT = {
  normal: '正常',
  anxiety: '焦虑',
  stress: '紧张',
  fatigue: '疲劳',
  weakness: '虚弱'
}

function getBandSnapshot(rawPowers = {}) {
  const delta = Number(rawPowers.delta || 0)
  const theta = Number(rawPowers.theta || 0)
  const alpha = Number(rawPowers.low_alpha || 0) + Number(rawPowers.high_alpha || 0)
  const beta = Number(rawPowers.low_beta || 0) + Number(rawPowers.high_beta || 0)
  const gamma = Number(rawPowers.low_gamma || 0) + Number(rawPowers.mid_gamma || 0)
  const total = delta + theta + alpha + beta + gamma

  if (!total) {
    return { delta: 0, theta: 0, alpha: 0, beta: 0, gamma: 0 }
  }

  return {
    delta: (delta / total) * 100,
    theta: (theta / total) * 100,
    alpha: (alpha / total) * 100,
    beta: (beta / total) * 100,
    gamma: (gamma / total) * 100
  }
}

export const useEegStore = defineStore('eeg', () => {
  const rawWave = ref([])
  const rawWaveFs = ref(512)
  const indices = ref({
    anxiety_idx: 0,
    stress_idx: 0,
    fatigue_idx: 0,
    weakness_idx: 0
  })
  const rawPowers = ref({})
  const features = ref({})
  const reasonCodes = ref([])
  const status = ref('idle')
  const statusText = ref('待接入')
  const qualityLevel = ref('unknown')
  const signalQuality = ref(null)
  const attention = ref(null)
  const meditation = ref(null)
  const calibrationProgress = ref(0)
  const emotion = ref('normal')
  const emotionZh = ref('正常')
  const analysisTime = ref('')

  const fatigueIndex = ref(0)
  const deltaPower = ref(0)
  const thetaPower = ref(0)
  const alphaPower = ref(0)
  const betaPower = ref(0)
  const gammaPower = ref(0)
  const fatigueLevel = ref('正常')
  const accuracy = ref(0)
  const recordHistory = ref([])

  watch(fatigueIndex, val => {
    recordHistory.value.push({
      timestamp: new Date().toLocaleTimeString(),
      value: val,
      level: fatigueLevel.value,
      status: status.value
    })
    if (recordHistory.value.length > 100) {
      recordHistory.value.shift()
    }
  })

  let evt = null
  let reconnectTimer = null
  let lastParams = null

  function setStatusText(payloadStatus, progress) {
    if (payloadStatus === 'calibrating') {
      statusText.value = `基线校准 ${Math.round(progress * 100)}%`
    } else if (payloadStatus === 'poor_signal') {
      statusText.value = '信号质量差，保留上次有效判断'
    } else if (payloadStatus === 'ok') {
      statusText.value = '在线'
    } else {
      statusText.value = '待接入'
    }
  }

  function applyPayload(d) {
    const shouldApplyWave = d.payload_type === 'raw_wave' || !d.raw_wave_original_live_published
    if (shouldApplyWave) {
      rawWave.value = Array.isArray(d.raw_wave_original) ? d.raw_wave_original : (Array.isArray(d.raw_wave) ? d.raw_wave : [])
      rawWaveFs.value = Number(d.raw_wave_original_fs || d.wave_fs || 512)
    }
    if (d.payload_type === 'raw_wave') {
      status.value = d.status || 'online'
      setStatusText(status.value, calibrationProgress.value)
      return
    }

    const bandSnapshot = getBandSnapshot(d.raw_powers)
    rawPowers.value = d.raw_powers || {}
    indices.value = {
      anxiety_idx: Number(d.indices?.anxiety_idx || 0),
      stress_idx: Number(d.indices?.stress_idx || 0),
      fatigue_idx: Number(d.indices?.fatigue_idx || 0),
      weakness_idx: Number(d.indices?.weakness_idx || 0)
    }
    features.value = d.features || {}
    reasonCodes.value = Array.isArray(d.reason_codes) ? d.reason_codes : []
    status.value = d.status || 'ok'
    qualityLevel.value = d.quality_level || 'unknown'
    signalQuality.value = d.signal_quality ?? null
    attention.value = d.attention ?? null
    meditation.value = d.meditation ?? null
    calibrationProgress.value = Number(d.calibration_progress || 0)
    emotion.value = d.emotion || emotion.value || 'normal'
    emotionZh.value = EMOTION_TEXT[emotion.value] || d.emotion_zh || emotionZh.value || '正常'
    analysisTime.value = d.analysis_time || ''
    setStatusText(status.value, calibrationProgress.value)

    fatigueIndex.value = Number(indices.value.fatigue_idx || 0)
    fatigueLevel.value = emotionZh.value
    deltaPower.value = bandSnapshot.delta
    thetaPower.value = bandSnapshot.theta
    alphaPower.value = bandSnapshot.alpha
    betaPower.value = bandSnapshot.beta
    gammaPower.value = bandSnapshot.gamma
    accuracy.value = status.value === 'ok' ? 100 : 0
  }

  function buildStreamUrl({ workerId } = {}) {
    if (workerId != null && workerId !== '') {
      return `/eeg/stream?workerId=${encodeURIComponent(workerId)}`
    }
    return '/eeg/stream'
  }

  function startSse(params = {}) {
    stopSse()
    lastParams = { ...params }
    const url = buildStreamUrl(params)
    console.log('[SSE] connect:', url)

    evt = new EventSource(url)
    status.value = 'connecting'
    statusText.value = '连接中'

    evt.onopen = () => {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }

    evt.onmessage = e => {
      try {
        applyPayload(JSON.parse(e.data))
      } catch (err) {
        console.warn('[SSE] 数据解析失败:', err)
      }
    }

    evt.onerror = err => {
      console.warn('[SSE] 连接错误:', err)
      evt?.close()
      evt = null
      status.value = 'error'
      statusText.value = '连接失败'
      scheduleReconnect()
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer || !lastParams) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      startSse(lastParams)
    }, 5000)
  }

  function stopSse() {
    if (evt) {
      evt.close()
      evt = null
    }
    clearTimeout(reconnectTimer)
    reconnectTimer = null
    status.value = 'idle'
    statusText.value = '已断开'
  }

  return {
    rawWave,
    rawWaveFs,
    indices,
    rawPowers,
    features,
    reasonCodes,
    status,
    statusText,
    qualityLevel,
    signalQuality,
    attention,
    meditation,
    calibrationProgress,
    emotion,
    emotionZh,
    analysisTime,
    fatigueIndex,
    deltaPower,
    thetaPower,
    alphaPower,
    betaPower,
    gammaPower,
    fatigueLevel,
    recordHistory,
    accuracy,
    startSse,
    stopSse
  }
})
