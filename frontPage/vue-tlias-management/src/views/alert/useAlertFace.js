import SockJS from 'sockjs-client/dist/sockjs.min.js'
import * as Stomp from 'stompjs'

const FACE_FATIGUE_WS_URL = '/wss'
const FACE_FRAME_MIN_INTERVAL = 120
const FACE_STATUS_TEXT = {
  online: '\u89c6\u9891\u6d41\u5df2\u8fde\u63a5\uff0c\u7b49\u5f85\u6a21\u578b\u8bc6\u522b',
  stream_ready: '\u89c6\u9891\u6d41\u5df2\u6062\u590d',
  reconnecting: '\u89c6\u9891\u6d41\u6062\u590d\u4e2d',
  camera_unreachable: '\u6444\u50cf\u5934\u672a\u5c31\u7eea\uff0c\u7b49\u5f85 RTSP \u7aef\u53e3',
  offline: '\u6444\u50cf\u5934\u79bb\u7ebf',
  no_frame: '\u6444\u50cf\u5934\u65e0\u753b\u9762',
  model_offline: '\u9762\u90e8\u6a21\u578b\u79bb\u7ebf'
}
const STREAM_REFRESH_STATUSES = new Set(['stream_ready', 'reconnecting', 'online'])

function guessImageMime(base64) {
  if (base64.startsWith('/9j/')) return 'image/jpeg'
  if (base64.startsWith('iVBORw0KGgo')) return 'image/png'
  if (base64.startsWith('R0lGOD')) return 'image/gif'
  if (base64.startsWith('UklGR')) return 'image/webp'
  return 'image/jpeg'
}

function normalizeFaceImage(image) {
  if (typeof image !== 'string') return ''
  const trimmed = image.trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('data:image/')) return trimmed
  if (/^(https?:|blob:|file:)/i.test(trimmed)) return trimmed
  const base64 = trimmed.replace(/\s+/g, '')
  return base64 ? `data:${guessImageMime(base64)};base64,${base64}` : ''
}

function normalizeScore(value) {
  if (value == null || value === '') return 0
  const numeric = Number.parseFloat(String(value).replace('%', ''))
  return Number.isFinite(numeric) ? numeric : 0
}

export function createFaceMonitor({ state, getBindingById, evaluateWarning, updateFusionState, updateEyeState, maybeTriggerAbnormalSample }) {
  let stompClient = null
  let stompSocket = null
  let stompConnected = false
  let stompConnecting = false
  let reconnectTimer = null
  const topicSubscriptions = new Map()
  const topicStates = new Map()

  function getTopicState(topic) {
    if (!topicStates.has(topic)) topicStates.set(topic, { lastTimestamp: 0, lastRenderedAt: 0, pendingPayload: null, animationFrameId: 0, timeoutId: 0 })
    return topicStates.get(topic)
  }

  function getBindingTopic(binding) { return String(binding?.faceChannelId || '').trim() }
  function getTopicBindings(topic) { return state.bindings.filter((binding) => getBindingTopic(binding) === topic) }
  function setBindingState(binding, { connected, statusText }) { if (binding) { binding.faceConnected = connected; binding.faceStatusText = statusText } }
  function bumpStreamVersion(binding) { if (binding) binding.faceStreamVersion = Number(binding.faceStreamVersion || 0) + 1 }
  function isCameraStatus(status) { return Object.prototype.hasOwnProperty.call(FACE_STATUS_TEXT, status) }
  function clearCurrentFacePrediction(binding) {
    if (!binding) return
    binding.lastValidFaceEmotion = ''
    binding.lastValidFaceEmotionZh = ''
    binding.lastValidFaceAt = 0
    binding.lastValidFaceScore = 0
    binding.faceAssistStreak = 0
    binding.faceStopRequired = false
    binding.eyeStatus = 'waiting'
    binding.eyeStatusText = '\u7b49\u5f85\u6709\u6548\u4eba\u8138'
    binding.eyeClosed = null
    binding.eyeClosedScore = 0
    binding.eyeOpenScore = 0
    binding.eyeBoxes = []
    binding.eyeSamples?.splice(0, binding.eyeSamples.length)
    binding.eyeLastValidAt = 0
    binding.eyeClosedStartedAt = 0
    binding.eyeCurrentClosedStartedAt = 0
    binding.eyeContinuousClosedMs = 0
    binding.eyeOpenStartedAt = 0
    binding.eyeContinuousOpenMs = 0
    binding.eyeDetailPopupActive = false
    binding.eyeMainAlertActive = false
    binding.eyePopupLevel = ''
    binding.eyeClosedAlertStage = ''
  }
  function applyCameraStatus(binding, payload) {
    const status = payload.status || 'offline'
    binding.faceStatus = status
    binding.faceStatusText = FACE_STATUS_TEXT[status] || '摄像头状态未知'
    binding.faceConnected = status === 'online' || status === 'stream_ready'
    if (STREAM_REFRESH_STATUSES.has(status)) bumpStreamVersion(binding)
    if (status !== 'online' && status !== 'stream_ready') {
      binding.faceImageUrl = ''
      binding.faceEmotionKey = ''
      binding.faceEmotion = '未识别'
      binding.faceScore = '--'
      binding.faceRate = '--'
      binding.faceRank = null
      binding.faceBox = null
    }
    clearCurrentFacePrediction(binding)
    updateFusionState?.(binding)
    evaluateWarning(binding)
  }
  function markBindingsWaiting(statusText) {
    state.bindings.forEach((binding) => {
      if (!binding.faceSubscription) return
      setBindingState(binding, { connected: false, statusText })
      clearCurrentFacePrediction(binding)
      updateFusionState?.(binding)
      evaluateWarning(binding)
    })
  }

  function clearTopicState(topic) {
    const topicState = topicStates.get(topic)
    if (!topicState) return
    if (topicState.animationFrameId) window.cancelAnimationFrame(topicState.animationFrameId)
    if (topicState.timeoutId) window.clearTimeout(topicState.timeoutId)
    topicStates.delete(topic)
  }

  function detachBindingFromTopic(binding, topic) {
    if (!topic) return
    binding.faceSubscription = null
    if (getTopicBindings(topic).length) return
    topicSubscriptions.get(topic)?.unsubscribe()
    topicSubscriptions.delete(topic)
    clearTopicState(topic)
  }

  function applyPayloadToBinding(binding, payload) {
    binding.faceStatus = payload.status || 'ok'
    if (isCameraStatus(binding.faceStatus)) {
      applyCameraStatus(binding, payload)
      return
    }
    binding.faceConnected = true
    binding.faceImageUrl = normalizeFaceImage(payload.image ?? payload.image_b64 ?? payload.imageBase64 ?? payload.base64Image)

    if (binding.faceStatus !== 'ok' || !payload.emotion5) {
      binding.faceStatusText = binding.faceStatus === 'no_face' ? '未检测到人脸' : '等待有效识别'
      binding.faceEmotionKey = ''
      binding.faceEmotion = '未识别'
      binding.faceScore = '--'
      binding.faceRate = '--'
      binding.faceRank = null
      clearCurrentFacePrediction(binding)
      updateEyeState?.(binding, payload)
      binding.faceStopRequired = false
      updateFusionState?.(binding)
      evaluateWarning(binding)
      return
    }

    binding.faceStatusText = '检测中'
    binding.faceEmotionKey = payload.emotion5
    binding.faceEmotion = payload.emotionCat || '未识别'
    binding.faceScore = payload.score == null ? '--' : payload.score
    binding.faceRate = payload.rate || '--'
    binding.faceRank = payload.fatigueRank == null ? null : Number(payload.fatigueRank)
    binding.faceBox = payload.faceBox || null
    binding.lastValidFaceEmotion = payload.emotion5
    binding.lastValidFaceEmotionZh = binding.faceEmotion
    binding.lastValidFaceAt = Date.now()
    binding.lastValidFaceScore = normalizeScore(payload.score)
    binding.faceAssistStreak = payload.emotion5 === 'normal' ? 0 : Number(binding.faceAssistStreak || 0) + 1
    binding.faceStopRequired = payload.emotion5 !== 'normal'
    updateEyeState?.(binding, payload)
    maybeTriggerAbnormalSample?.(binding, payload)
    updateFusionState?.(binding)
    evaluateWarning(binding)
  }

  function flushTopicPayload(topic) {
    const topicState = getTopicState(topic)
    const payload = topicState.pendingPayload
    topicState.pendingPayload = null
    topicState.timeoutId = 0
    topicState.animationFrameId = 0
    if (!payload) return
    topicState.lastRenderedAt = Date.now()
    getTopicBindings(topic).forEach((binding) => applyPayloadToBinding(binding, payload))
  }

  function scheduleTopicRender(topic, payload) {
    const topicState = getTopicState(topic)
    const timestamp = Number(payload.timestamp || 0)
    if (timestamp && timestamp < topicState.lastTimestamp) return
    if (timestamp) topicState.lastTimestamp = timestamp
    topicState.pendingPayload = payload
    if (topicState.animationFrameId || topicState.timeoutId) return
    topicState.animationFrameId = window.requestAnimationFrame(() => {
      topicState.animationFrameId = 0
      const elapsed = Date.now() - topicState.lastRenderedAt
      if (elapsed >= FACE_FRAME_MIN_INTERVAL) flushTopicPayload(topic)
      else topicState.timeoutId = window.setTimeout(() => flushTopicPayload(topic), FACE_FRAME_MIN_INTERVAL - elapsed)
    })
  }

  function subscribeTopic(topic) {
    if (!stompConnected || !stompClient || topicSubscriptions.has(topic)) return
    const subscription = stompClient.subscribe(`/topic/face_fatigue/${topic}`, (message) => {
      if (!message.body) return
      try { scheduleTopicRender(topic, JSON.parse(message.body)) }
      catch (error) { console.error('Failed to parse face fatigue payload:', error) }
    })
    topicSubscriptions.set(topic, subscription)
  }

  function handleDisconnect(statusText = '连接中') {
    stompConnected = false
    stompConnecting = false
    stompClient = null
    stompSocket = null
    markBindingsWaiting(statusText)
    if (reconnectTimer) return
    reconnectTimer = window.setTimeout(() => { reconnectTimer = null; ensureFaceConnection() }, 1500)
  }

  function ensureFaceConnection() {
    if (stompConnected || stompConnecting || stompClient) return
    stompConnecting = true
    markBindingsWaiting('连接中')
    stompSocket = new SockJS(FACE_FATIGUE_WS_URL)
    stompClient = Stomp.over(stompSocket)
    stompClient.debug = () => {}
    if (typeof stompSocket.onclose !== 'undefined') stompSocket.onclose = () => handleDisconnect('连接中')
    stompClient.connect({}, () => {
      stompConnected = true
      stompConnecting = false
      state.bindings.forEach((binding) => { if (binding.faceSubscription || binding.faceChannelId) subscribeFace(binding) })
    }, () => handleDisconnect('连接中'))
  }

  function subscribeFace(binding) {
    if (!binding) return
    const nextTopic = getBindingTopic(binding)
    if (!nextTopic) { setBindingState(binding, { connected: false, statusText: '未选择摄像头' }); return }
    const prevTopic = binding.faceSubscription
    if (prevTopic && prevTopic !== nextTopic) detachBindingFromTopic(binding, prevTopic)
    binding.faceSubscription = nextTopic
    if (!stompConnected || !stompClient) { setBindingState(binding, { connected: false, statusText: '等待识别' }); ensureFaceConnection(); return }
    subscribeTopic(nextTopic)
    setBindingState(binding, { connected: true, statusText: '等待识别' })
  }

  function refreshFaceSubscription(bindingId) { const binding = getBindingById(bindingId); if (binding) subscribeFace(binding) }
  function unsubscribeFace(bindingId) { const binding = getBindingById(bindingId); if (!binding?.faceSubscription) return; const topic = binding.faceSubscription; detachBindingFromTopic(binding, topic); setBindingState(binding, { connected: false, statusText: '待接入' }) }

  function unsubscribeFaceSafe(bindingId) {
    const binding = getBindingById(bindingId)
    if (!binding?.faceSubscription) return
    const topic = binding.faceSubscription
    detachBindingFromTopic(binding, topic)
    clearCurrentFacePrediction(binding)
    setBindingState(binding, { connected: false, statusText: '待接入' })
    updateFusionState?.(binding)
    evaluateWarning(binding)
  }

  return { ensureFaceConnection, subscribeFace, refreshFaceSubscription, unsubscribeFace: unsubscribeFaceSafe }
}
