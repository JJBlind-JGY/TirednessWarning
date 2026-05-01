import SockJS from 'sockjs-client/dist/sockjs.min.js'
import * as Stomp from 'stompjs'

const FACE_FATIGUE_WS_URL = '/wss'
const FACE_FRAME_MIN_INTERVAL = 120

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
  if (!base64) return ''

  return `data:${guessImageMime(base64)};base64,${base64}`
}

export function createFaceMonitor({ state, getBindingById, evaluateWarning }) {
  let stompClient = null
  let stompSocket = null
  let stompConnected = false
  let stompConnecting = false
  let reconnectTimer = null

  const topicSubscriptions = new Map()
  const topicStates = new Map()

  function getTopicState(topic) {
    if (!topicStates.has(topic)) {
      topicStates.set(topic, {
        lastTimestamp: 0,
        lastRenderedAt: 0,
        pendingPayload: null,
        animationFrameId: 0,
        timeoutId: 0
      })
    }
    return topicStates.get(topic)
  }

  function getBindingTopic(binding) {
    const topic = String(binding?.faceChannelId || '').trim()
    return topic
  }

  function getTopicBindings(topic) {
    return state.bindings.filter((binding) => getBindingTopic(binding) === topic)
  }

  function setBindingState(binding, { connected, statusText }) {
    if (!binding) return
    binding.faceConnected = connected
    binding.faceStatusText = statusText
  }

  function markBindingsWaiting(statusText) {
    state.bindings.forEach((binding) => {
      if (binding.faceSubscription) {
        setBindingState(binding, { connected: false, statusText })
      }
    })
  }

  function clearTopicState(topic) {
    const topicState = topicStates.get(topic)
    if (!topicState) return
    if (topicState.animationFrameId) {
      window.cancelAnimationFrame(topicState.animationFrameId)
    }
    if (topicState.timeoutId) {
      window.clearTimeout(topicState.timeoutId)
    }
    topicStates.delete(topic)
  }

  function detachBindingFromTopic(binding, topic) {
    if (!topic) return
    binding.faceSubscription = null

    if (getTopicBindings(topic).length) {
      return
    }

    topicSubscriptions.get(topic)?.unsubscribe()
    topicSubscriptions.delete(topic)
    clearTopicState(topic)
  }

  function applyPayloadToBinding(binding, payload) {
    binding.faceConnected = true
    binding.faceStatusText = '识别中'
    binding.faceEmotion = payload.emotionCat || '未识别'
    binding.faceScore = payload.score || '--'
    binding.faceRate = payload.rate || '--'
    binding.faceRank = payload.fatigueRank == null ? null : Number(payload.fatigueRank)
    binding.faceStopRequired = binding.faceEmotion !== '其他' && binding.faceEmotion !== '未识别'
    binding.faceImageUrl = normalizeFaceImage(
      payload.image ?? payload.image_b64 ?? payload.imageBase64 ?? payload.base64Image
    )
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
    if (timestamp && timestamp < topicState.lastTimestamp) {
      return
    }
    if (timestamp) {
      topicState.lastTimestamp = timestamp
    }

    topicState.pendingPayload = payload
    if (topicState.animationFrameId || topicState.timeoutId) return

    topicState.animationFrameId = window.requestAnimationFrame(() => {
      topicState.animationFrameId = 0
      const elapsed = Date.now() - topicState.lastRenderedAt
      if (elapsed >= FACE_FRAME_MIN_INTERVAL) {
        flushTopicPayload(topic)
        return
      }

      topicState.timeoutId = window.setTimeout(() => {
        flushTopicPayload(topic)
      }, FACE_FRAME_MIN_INTERVAL - elapsed)
    })
  }

  function subscribeTopic(topic) {
    if (!stompConnected || !stompClient || topicSubscriptions.has(topic)) return

    const subscription = stompClient.subscribe(`/topic/face_fatigue/${topic}`, (message) => {
      if (!message.body) return

      let payload = {}
      try {
        payload = JSON.parse(message.body)
      } catch (error) {
        console.error('Failed to parse face fatigue payload:', error)
        return
      }

      scheduleTopicRender(topic, payload)
    })

    topicSubscriptions.set(topic, subscription)
  }

  function handleDisconnect(statusText = '重连中') {
    stompConnected = false
    stompConnecting = false
    stompClient = null
    stompSocket = null
    markBindingsWaiting(statusText)

    if (reconnectTimer) return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      ensureFaceConnection()
    }, 1500)
  }

  function ensureFaceConnection() {
    if (stompConnected || stompConnecting || stompClient) return

    stompConnecting = true
    markBindingsWaiting('连接中')

    stompSocket = new SockJS(FACE_FATIGUE_WS_URL)
    stompClient = Stomp.over(stompSocket)
    stompClient.debug = () => {}

    if (typeof stompSocket.onclose !== 'undefined') {
      stompSocket.onclose = () => {
        handleDisconnect('连接断开，重连中')
      }
    }

    stompClient.connect(
      {},
      () => {
        stompConnected = true
        stompConnecting = false
        state.bindings.forEach((binding) => {
          if (binding.faceSubscription || binding.faceChannelId) {
            subscribeFace(binding)
          }
        })
      },
      () => {
        handleDisconnect('连接失败，重试中')
      }
    )
  }

  function subscribeFace(binding) {
    if (!binding) return

    const nextTopic = getBindingTopic(binding)
    if (!nextTopic) {
      setBindingState(binding, { connected: false, statusText: '未选择摄像头' })
      return
    }
    const prevTopic = binding.faceSubscription

    if (prevTopic && prevTopic !== nextTopic) {
      detachBindingFromTopic(binding, prevTopic)
    }

    binding.faceSubscription = nextTopic

    if (!stompConnected || !stompClient) {
      setBindingState(binding, { connected: false, statusText: '连接中' })
      ensureFaceConnection()
      return
    }

    subscribeTopic(nextTopic)
    setBindingState(binding, { connected: true, statusText: '已连接，等待画面' })
  }

  function refreshFaceSubscription(bindingId) {
    const binding = getBindingById(bindingId)
    if (!binding) return
    subscribeFace(binding)
  }

  function unsubscribeFace(bindingId) {
    const binding = getBindingById(bindingId)
    if (!binding?.faceSubscription) return

    const topic = binding.faceSubscription
    detachBindingFromTopic(binding, topic)
    setBindingState(binding, { connected: false, statusText: '未接入' })
  }

  return {
    ensureFaceConnection,
    subscribeFace,
    refreshFaceSubscription,
    unsubscribeFace
  }
}
