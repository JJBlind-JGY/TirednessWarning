import { computed, nextTick, onBeforeUnmount, onMounted, reactive } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { createEegMonitor } from './useAlertEeg'
import { createFaceMonitor } from './useAlertFace'

const PERSONNEL_STORAGE_KEY = 'alert-personnel-options'
const DEVICE_STORAGE_KEY = 'alert-device-options'
const CAMERA_STORAGE_KEY = 'alert-camera-options'
const BINDINGS_STORAGE_KEY = 'alert-bindings'
const FACE_SERVICE_BASE = '/face-api/faceDetectService'
const GO2RTC_BASE_URL = import.meta.env.VITE_GO2RTC_BASE_URL || 'http://127.0.0.1:1984'
const VALID_EEG_HOLD_MS = 10000
const VALID_FACE_HOLD_MS = 8000
const ABNORMAL_POPUP_COOLDOWN_MS = 90000
const ABNORMAL_POPUP_STREAK_LIMIT = 6
const ALERT_HISTORY_COOLDOWN_MS = 90000
const ALERT_HISTORY_STREAK_LIMIT = 6
const EEG_FUSION_ABNORMAL_STREAK_LIMIT = 2
const FACE_ASSIST_STREAK_LIMIT = 3
const FACE_ONLY_STREAK_LIMIT = 5
let fusionRefreshTimer = null

const EMOTION_ZH = {
  normal: '正常',
  anxiety: '焦虑',
  stress: '紧张',
  fatigue: '疲劳',
  weakness: '虚弱'
}

const EMOTION_WARNING_TEXT = {
  normal: '预警：当前状态正常',
  anxiety: '预警：检测到焦虑倾向',
  stress: '预警：检测到紧张倾向',
  fatigue: '预警：检测到疲劳倾向',
  weakness: '预警：检测到虚弱倾向'
}

const DEVICE_OPTIONS = reactive([])
const CAMERA_OPTIONS = reactive([])

const state = reactive({ initialized: false, bindings: [], personnelOptions: [], alertHistory: [] })

function readLocalList(storageKey, fallback = []) {
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return [...fallback]
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : [...fallback]
  } catch (error) {
    console.warn(`Failed to read ${storageKey}`, error)
    return [...fallback]
  }
}

function writeLocalList(storageKey, value) {
  localStorage.setItem(storageKey, JSON.stringify(value))
}

function replaceArray(target, values) {
  target.splice(0, target.length, ...values)
}

function normalizePersonnel(item, index = 0) {
  const uid = String(item.uid || item.id || `P${String(index + 1).padStart(3, '0')}`)
  return { id: String(item.id || uid), uid, name: String(item.name || `人员${index + 1}`), type: String(item.type || '值班员') }
}

function normalizeDevice(item, index = 0) {
  const value = Number(item.value ?? item.workerId ?? index + 1)
  const name = String(item.name || `脑电设备${value}`)
  const port = String(item.port || '')
  return { value, name, port, label: port ? `${name} / ${port}` : name }
}

function normalizeCamera(item, index = 0) {
  const id = String(item.id || item.faceChannelId || item.cameraId || `camera_${String(index + 1).padStart(3, '0')}`)
  const name = String(item.name || `摄像头${index + 1}`)
  const rtspUrl = String(item.rtspUrl || '')
  const streamName = String(item.streamName || item.go2rtcStream || id)
  return { id, name, rtspUrl, streamName, streamUrl: `${GO2RTC_BASE_URL}/stream.html?src=${encodeURIComponent(streamName)}&mode=webrtc`, label: `${name} / ${id}` }
}

async function loadPersonnel() {
  const items = []
  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/personnel`)
    if (response.ok) {
      const payload = await response.json()
      const personnel = Array.isArray(payload?.data) ? payload.data : []
      replaceArray(items, personnel.map(normalizePersonnel))
    }
  } catch (error) { console.warn('Failed to load remote personnel config', error) }
  replaceArray(state.personnelOptions, items)
  persistPersonnel()
}

async function loadDevices() {
  const items = []
  try {
    const response = await fetch('/eeg/devices')
    if (response.ok) {
      const payload = await response.json()
      const eegDevices = Array.isArray(payload?.data) ? payload.data : []
      replaceArray(items, eegDevices.map(normalizeDevice))
    }
  } catch (error) { console.warn('Failed to load remote eeg device config', error) }
  replaceArray(DEVICE_OPTIONS, items)
  persistDevices()
}

async function loadCameras() {
  const items = []
  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/cameras`)
    if (response.ok) {
      const payload = await response.json()
      const cameras = Array.isArray(payload?.data) ? payload.data : []
      replaceArray(items, cameras.map(normalizeCamera))
    }
  } catch (error) { console.warn('Failed to load remote camera config', error) }
  replaceArray(CAMERA_OPTIONS, items)
  persistCameras()
}

function persistPersonnel() { writeLocalList(PERSONNEL_STORAGE_KEY, state.personnelOptions.map(({ id, uid, name, type }) => ({ id, uid, name, type }))) }
function persistDevices() { writeLocalList(DEVICE_STORAGE_KEY, DEVICE_OPTIONS.map(({ value, name, port }) => ({ value, name, port }))) }
function persistCameras() { writeLocalList(CAMERA_STORAGE_KEY, CAMERA_OPTIONS.map(({ id, name, rtspUrl, streamName }) => ({ id, name, rtspUrl, streamName }))) }
function loadBindings() { state.bindings = readLocalList(BINDINGS_STORAGE_KEY, []).map(normalizeBinding) }
function persistBindings() { writeLocalList(BINDINGS_STORAGE_KEY, state.bindings.map(({ id, personId, personName, personType, workerId, faceChannelId }) => ({ id, personId, personName, personType, workerId, faceChannelId }))) }
function getDefaultCameraId() { return CAMERA_OPTIONS[0]?.id || '' }

function createBinding(seed = 1) {
  const defaultWorkerId = DEVICE_OPTIONS[(seed - 1) % Math.max(DEVICE_OPTIONS.length, 1)]?.value ?? null
  return reactive({
    id: `binding-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    personId: '', personName: '', personType: '', workerId: defaultWorkerId, activeWorkerId: null, faceChannelId: getDefaultCameraId(),
    eegRunning: false, eegStatus: 'idle', eegStatusText: '待接入', eegEmotion: '', eegEmotionZh: '', eegQualityLevel: '', signalQuality: null,
    lastValidEegEmotion: '', lastValidEegAt: 0, eegFusionCandidate: '', eegFusionStreak: 0, reasonCodes: [], features: {},
    emotion: 'normal', emotionZh: EMOTION_ZH.normal, fusionEmotion: 'normal', fusionEmotionZh: EMOTION_ZH.normal, fusionSource: 'waiting',
    analysisTime: '', calibrationProgress: 0,
    indices: { anxiety_idx: 0, stress_idx: 0, fatigue_idx: 0, weakness_idx: 0 }, probs: {},
    bandSnapshot: { delta: 0, theta: 0, alpha: 0, beta: 0, gamma: 0 }, rawWaveBuffer: [], waveScale: 1,
    faceConnected: false, faceImageUrl: '', faceStatusText: '待接入', faceStatus: 'idle', faceEmotion: '未识别', faceEmotionKey: '', faceScore: '--', faceRate: '--', faceRank: null, faceBox: null,
    lastValidFaceEmotion: '', lastValidFaceEmotionZh: '', lastValidFaceAt: 0, lastValidFaceScore: 0, faceAssistStreak: 0, faceStopRequired: false,
    videoUploading: false, uploadPercent: 0, localVideoUrl: '', videoWidth: 0, videoHeight: 0,
    fatigueStreak: 0, abnormalPopupCandidate: '', abnormalPopupStreak: 0, alertHistoryStreak: 0, lastPopupAt: 0, lastAlertHistoryAt: 0, hasPopupWarning: false, popupWarningActive: false, popupWarningEmotion: '', latestWarningLevel: 'info', latestEmotion: 'normal', faceSubscription: null
  })
}

function normalizeBinding(item, index = 0) {
  const binding = createBinding(index + 1)
  Object.assign(binding, {
    id: item.id || binding.id,
    personId: item.personId || '', personName: item.personName || '', personType: item.personType || '',
    workerId: item.workerId ?? binding.workerId, activeWorkerId: null, faceChannelId: item.faceChannelId || getDefaultCameraId(),
    eegRunning: false, eegStatus: 'idle', eegStatusText: '待接入', faceConnected: false, faceStatusText: '待接入', faceSubscription: null
  })
  updateBindingPerson(binding, { auto: false })
  return binding
}

function getBindingById(bindingId) { return state.bindings.find((item) => item.id === bindingId) }
function getDeviceLabel(workerId) { return DEVICE_OPTIONS.find((item) => item.value === workerId)?.label || '未配置脑电设备' }
function getCameraLabel(cameraId) { return CAMERA_OPTIONS.find((item) => item.id === cameraId)?.label || '未配置摄像头' }
function isFresh(timestamp, ttl, now = Date.now()) { return Boolean(timestamp && now - Number(timestamp) <= ttl) }
function hasFreshEeg(binding, now = Date.now()) { return Boolean(binding?.lastValidEegEmotion && binding.eegStatus === 'ok' && isFresh(binding.lastValidEegAt, VALID_EEG_HOLD_MS, now)) }
function hasFreshFace(binding, now = Date.now()) { return Boolean(binding?.lastValidFaceEmotion && isFresh(binding.lastValidFaceAt, VALID_FACE_HOLD_MS, now)) }
function hasPrediction(binding) { return Boolean(binding && (hasFreshEeg(binding) || hasFreshFace(binding))) }
function getDisplayEmotion(binding) { return hasPrediction(binding) ? binding.emotionZh : '等待数据' }
function hasCamera(binding) { return Boolean(binding?.faceChannelId && CAMERA_OPTIONS.some((item) => item.id === binding.faceChannelId)) }
function hasEegSignal(binding) { return Boolean(binding?.eegRunning || (binding?.eegStatus && binding.eegStatus !== 'idle' && binding.eegStatus !== 'error' && (binding?.rawWaveBuffer?.length || binding?.analysisTime))) }
function hasFaceSignal(binding) { return Boolean(binding?.faceConnected || binding?.faceImageUrl || hasFreshFace(binding)) }
function hasAnySignal(binding) { return Boolean(hasPrediction(binding) || hasEegSignal(binding) || hasFaceSignal(binding)) }
function getCurrentStatusText(binding) {
  if (!binding) return '等待数据'
  if (hasPrediction(binding)) return binding.emotionZh
  if (binding.eegQualityLevel === 'no_contact') return binding.eegStatusText || '设备在线，等待佩戴'
  if (binding.eegStatus === 'calibrating') return binding.eegStatusText || '脑电校准中'
  if (binding.eegStatus === 'poor_signal') return '脑电信号质量不佳'
  if (hasEegSignal(binding)) return binding.eegEmotionZh || binding.eegStatusText || '脑电检测中'
  if (hasFaceSignal(binding)) return binding.faceStatusText || '面部检测中'
  return '等待数据'
}
function hasAccess(binding) { return Boolean(binding?.eegRunning || binding?.faceConnected) }
function getAccessText(binding) { return hasAccess(binding) ? '已接入' : '自动接入中' }
function getEegStatusLabel(binding) {
  if (!binding?.workerId) return '未选择脑电设备'
  if (!binding?.eegRunning) return binding?.eegStatusText || '自动接入中'
  if (['connecting', 'online', 'offline', 'error'].includes(binding.eegStatus)) return binding.eegStatusText || '自动接入中'
  return binding.eegStatus === 'calibrating' ? '校准中' : (binding.eegStatusText || '检测中')
}
function getFaceStatusLabel(binding) { if (!hasCamera(binding)) return '未选择摄像头'; return binding.faceStatusText || '等待识别' }

function updateBindingPerson(binding, { auto = true } = {}) {
  const selected = state.personnelOptions.find((item) => item.id === binding.personId || item.uid === binding.personId)
  binding.personName = selected?.name || ''
  binding.personType = selected?.type || ''
  persistBindings()
  if (!auto) return
  if (!binding.personId) eegMonitor.stopEeg(binding.id, 'restart')
  else eegMonitor.ensureAutoEeg(binding)
}

function getWarningLevel(binding) { return binding.emotion === 'normal' ? 'info' : 'warning' }
function getWarningText(binding) { if (!hasPrediction(binding)) return '等待有效数据'; return EMOTION_WARNING_TEXT[binding.emotion] || EMOTION_WARNING_TEXT.normal }
function getIndexScores(binding) { return { fatigue: Number(binding.indices?.fatigue_idx || 0), stress: Number(binding.indices?.stress_idx || 0), anxiety: Number(binding.indices?.anxiety_idx || 0), weakness: Number(binding.indices?.weakness_idx || 0) } }

function getDisplayEmotionText(binding) { return getCurrentStatusText(binding) }
function getWarningTextDisplay(binding) {
  if (!hasPrediction(binding)) return getCurrentStatusText(binding)
  return EMOTION_WARNING_TEXT[binding.emotion] || EMOTION_WARNING_TEXT.normal
}

function addFaceSupport(scores, binding, now) {
  if (!hasFreshFace(binding, now)) return
  const confidence = Math.min(1, Math.max(0, Number(binding.lastValidFaceScore || 0) / 100))
  if (binding.lastValidFaceEmotion === 'normal') scores.normal += 8 * confidence
  else scores[binding.lastValidFaceEmotion] += 4 + 6 * confidence
}

function pushAlertHistory(binding, level, message = getWarningText(binding)) {
  state.alertHistory.unshift({
    id: `${binding.id}-${Date.now()}`,
    personName: binding.personName || 'æœªç»‘å®šäººå‘˜',
    device: getDeviceLabel(binding.workerId),
    level,
    time: new Date().toLocaleString('zh-CN', { hour12: false }),
    message
  })
  if (state.alertHistory.length > 12) state.alertHistory.length = 12
}

function chooseStableEegEmotion(binding) {
  const eegEmotion = binding.lastValidEegEmotion || 'normal'
  if (eegEmotion === 'normal') {
    binding.eegFusionCandidate = ''
    binding.eegFusionStreak = 0
    return 'normal'
  }

  if (binding.eegFusionCandidate === eegEmotion) binding.eegFusionStreak += 1
  else {
    binding.eegFusionCandidate = eegEmotion
    binding.eegFusionStreak = 1
  }

  if (binding.fusionEmotion === eegEmotion) return eegEmotion
  return binding.eegFusionStreak >= EEG_FUSION_ABNORMAL_STREAK_LIMIT ? eegEmotion : 'normal'
}

function chooseFusionEmotion(binding, now = Date.now()) {
  const eegFresh = hasFreshEeg(binding, now)
  const faceFresh = hasFreshFace(binding, now)
  const faceEmotion = faceFresh ? binding.lastValidFaceEmotion : ''
  const faceConfidence = Math.min(1, Math.max(0, Number(binding.lastValidFaceScore || 0) / 100))
  const faceAssistReady = faceFresh &&
    faceEmotion !== 'normal' &&
    Number(binding.faceAssistStreak || 0) >= FACE_ASSIST_STREAK_LIMIT &&
    faceConfidence >= 0.55

  if (eegFresh) {
    const stableEegEmotion = chooseStableEegEmotion(binding)
    if (stableEegEmotion !== 'normal') return stableEegEmotion
    if (faceAssistReady && Number(binding.faceAssistStreak || 0) >= FACE_ONLY_STREAK_LIMIT && faceConfidence >= 0.72) return faceEmotion
    return 'normal'
  }

  binding.eegFusionCandidate = ''
  binding.eegFusionStreak = 0

  if (!faceFresh || faceEmotion === 'normal') return 'normal'
  if (!hasEegSignal(binding)) return faceEmotion
  if (Number(binding.faceAssistStreak || 0) < FACE_ONLY_STREAK_LIMIT || faceConfidence < 0.78) return 'normal'

  const scores = { normal: 42, fatigue: 0, stress: 0, anxiety: 0, weakness: 0 }
  const idx = getIndexScores(binding)
  scores.fatigue += idx.fatigue * 0.25
  scores.stress += idx.stress * 0.2
  scores.anxiety += idx.anxiety * 0.2
  scores.weakness += idx.weakness * 0.22
  addFaceSupport(scores, binding, now)
  const nonNormal = ['fatigue', 'stress', 'anxiety', 'weakness'].map((name) => [name, scores[name]]).sort((a, b) => b[1] - a[1])
  const [topName, topScore] = nonNormal[0]
  return topScore >= 38 && topName === faceEmotion ? topName : 'normal'
}

function maybeShowAbnormalNotification(binding) {
  const now = Date.now()
  if (binding.emotion === 'normal') {
    binding.abnormalPopupCandidate = ''
    binding.abnormalPopupStreak = 0
    return
  }
  if (binding.abnormalPopupCandidate === binding.emotion) binding.abnormalPopupStreak += 1
  else {
    binding.abnormalPopupCandidate = binding.emotion
    binding.abnormalPopupStreak = 1
  }
  if (binding.abnormalPopupStreak < ABNORMAL_POPUP_STREAK_LIMIT) return
  if (binding.popupWarningActive) return
  if (now - Number(binding.lastPopupAt || 0) < ABNORMAL_POPUP_COOLDOWN_MS) return
  binding.lastPopupAt = now
  binding.hasPopupWarning = true
  binding.popupWarningActive = true
  binding.popupWarningEmotion = binding.emotion
  binding.lastAlertHistoryAt = now
  pushAlertHistory(binding, 'warning')
  ElNotification({ title: '状态提醒', message: `${binding.personName || '当前人员'} 检测为${binding.emotionZh}，请关注当前状态。`, type: 'warning', duration: 5000, showClose: true, position: 'top-right' })
}

function shouldRecordAlertHistory(binding, level) {
  const now = Date.now()
  const changed = binding.latestWarningLevel !== level || binding.emotion !== binding.latestEmotion
  if (binding.emotion === 'normal') {
    binding.alertHistoryStreak = 0
    if (!changed || !binding.popupWarningActive) return false
    binding.popupWarningActive = false
    binding.hasPopupWarning = false
    binding.popupWarningEmotion = ''
    binding.abnormalPopupCandidate = ''
    binding.abnormalPopupStreak = 0
    binding.lastPopupAt = 0
    return true
  }
  return false
}

function updateFusionState(binding) {
  if (!binding) return
  const emotion = chooseFusionEmotion(binding)
  binding.fusionEmotion = emotion
  binding.fusionEmotionZh = EMOTION_ZH[emotion] || EMOTION_ZH.normal
  binding.emotion = binding.fusionEmotion
  binding.emotionZh = binding.fusionEmotionZh
  binding.fusionSource = hasAnySignal(binding) ? 'detected' : 'waiting'
  maybeShowAbnormalNotification(binding)
}

function refreshFusionStates() {
  const now = Date.now()
  state.bindings.forEach((binding) => {
    const hadPrediction = hasPrediction(binding)
    if (!hasFreshEeg(binding, now) && binding.eegStatus !== 'ok') {
      binding.lastValidEegEmotion = ''
      binding.lastValidEegAt = 0
    }
    if (!hasFreshFace(binding, now)) {
      binding.lastValidFaceEmotion = ''
      binding.lastValidFaceEmotionZh = ''
      binding.lastValidFaceAt = 0
      binding.lastValidFaceScore = 0
      binding.faceAssistStreak = 0
    }
    updateFusionState(binding)
    if (hadPrediction || hasPrediction(binding)) evaluateWarning(binding)
  })
}

function evaluateWarning(binding) {
  const level = getWarningLevel(binding)
  if (!hasPrediction(binding)) return
  if (shouldRecordAlertHistory(binding, level)) {
    pushAlertHistory(binding, level)
  }
  binding.latestWarningLevel = level
  binding.latestEmotion = binding.emotion
}

const eegMonitor = createEegMonitor({ state, getBindingById, getDeviceLabel, evaluateWarning, updateFusionState })
const faceMonitor = createFaceMonitor({ state, getBindingById, updateBindingPerson, evaluateWarning, updateFusionState })

function syncBindingsWithDevices() {
  const fallbackWorkerId = DEVICE_OPTIONS[0]?.value ?? null
  state.bindings.forEach((binding) => { if (!DEVICE_OPTIONS.some((item) => item.value === binding.workerId)) { eegMonitor.stopEeg(binding.id, 'restart'); binding.workerId = fallbackWorkerId; binding.activeWorkerId = null; eegMonitor.ensureAutoEeg(binding) } })
  persistBindings()
}
function syncBindingsWithPersonnel() { state.bindings.forEach((binding) => { if (!state.personnelOptions.some((item) => item.id === binding.personId || item.uid === binding.personId)) { eegMonitor.stopEeg(binding.id, 'restart'); binding.personId = ''; binding.personName = ''; binding.personType = ''; return } updateBindingPerson(binding) }); persistBindings() }
function syncBindingsWithCameras() { const fallbackCameraId = getDefaultCameraId(); state.bindings.forEach((binding) => { if (!CAMERA_OPTIONS.some((item) => item.id === binding.faceChannelId)) { faceMonitor.unsubscribeFace(binding.id); binding.faceChannelId = fallbackCameraId; faceMonitor.subscribeFace(binding) } }); persistBindings() }

async function initMonitorCenter() {
  if (state.initialized) return
  await Promise.all([loadPersonnel(), loadDevices(), loadCameras()])
  loadBindings(); syncBindingsWithDevices(); syncBindingsWithCameras(); faceMonitor.ensureFaceConnection(); state.bindings.forEach((binding) => faceMonitor.subscribeFace(binding)); eegMonitor.ensureAllAutoEeg(); state.initialized = true
}

function addBinding() { if (state.bindings.length >= 4) { ElMessage.warning('最多同时监测 4 张卡片'); return } const binding = createBinding(state.bindings.length + 1); state.bindings.push(binding); persistBindings(); faceMonitor.subscribeFace(binding); eegMonitor.ensureAutoEeg(binding) }
function removeBinding(bindingId) { eegMonitor.stopEeg(bindingId); faceMonitor.unsubscribeFace(bindingId); eegMonitor.disposeChart(bindingId); const index = state.bindings.findIndex((item) => item.id === bindingId); if (index === -1) return; const binding = state.bindings[index]; if (binding.localVideoUrl) URL.revokeObjectURL(binding.localVideoUrl); state.bindings.splice(index, 1); persistBindings() }

async function syncRemotePersonnel(personnel) { const response = await fetch(`${FACE_SERVICE_BASE}/personnel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: personnel.id, uid: personnel.uid, name: personnel.name, type: personnel.type }) }); if (!response.ok) throw new Error(`personnel save failed: ${response.status}`) }
async function removeRemotePersonnel(personId) { const response = await fetch(`${FACE_SERVICE_BASE}/personnel/${encodeURIComponent(personId)}`, { method: 'DELETE' }); if (!response.ok && response.status !== 404) throw new Error(`personnel delete failed: ${response.status}`) }
async function addPersonnel(record) { const normalized = normalizePersonnel({ id: `person-${Date.now()}`, uid: record.uid, name: record.name, type: record.type }, state.personnelOptions.length); await syncRemotePersonnel(normalized); state.personnelOptions.push(normalized); persistPersonnel() }
async function updatePersonnel(record) { const index = state.personnelOptions.findIndex((item) => item.id === record.id); if (index === -1) return; const normalized = normalizePersonnel(record, index); await syncRemotePersonnel(normalized); state.personnelOptions[index] = normalized; persistPersonnel(); syncBindingsWithPersonnel() }
async function removePersonnel(personId) { const index = state.personnelOptions.findIndex((item) => item.id === personId); if (index === -1) return; await removeRemotePersonnel(personId); state.personnelOptions.splice(index, 1); persistPersonnel(); syncBindingsWithPersonnel() }

function getNextDeviceValue() { return DEVICE_OPTIONS.reduce((max, item) => Math.max(max, Number(item.value || 0)), 0) + 1 }
async function syncRemoteDevice(device) { if (!device.port) return; const response = await fetch('/eeg/devices', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workerId: device.value, value: device.value, name: device.name, port: device.port }) }); if (!response.ok) throw new Error(`eeg device save failed: ${response.status}`) }
async function removeRemoteDevice(deviceValue) { const response = await fetch(`/eeg/devices/${encodeURIComponent(deviceValue)}`, { method: 'DELETE' }); if (!response.ok && response.status !== 404) throw new Error(`eeg device delete failed: ${response.status}`) }
async function addDevice(record) { const normalized = normalizeDevice({ value: getNextDeviceValue(), name: record.name, port: record.port }, DEVICE_OPTIONS.length); await syncRemoteDevice(normalized); DEVICE_OPTIONS.push(normalized); persistDevices(); state.bindings.forEach((binding) => { if (binding.workerId == null) binding.workerId = normalized.value }) }
async function updateDevice(record) { const index = DEVICE_OPTIONS.findIndex((item) => item.value === Number(record.value)); if (index === -1) return; const normalized = normalizeDevice(record, index); await syncRemoteDevice(normalized); DEVICE_OPTIONS[index] = normalized; persistDevices(); state.bindings.forEach((binding) => { if (binding.workerId === normalized.value) { eegMonitor.stopEeg(binding.id, 'restart'); eegMonitor.ensureAutoEeg(binding) } }); persistBindings() }
async function removeDevice(deviceValue) { const index = DEVICE_OPTIONS.findIndex((item) => item.value === Number(deviceValue)); if (index === -1) return; await removeRemoteDevice(deviceValue); DEVICE_OPTIONS.splice(index, 1); persistDevices(); syncBindingsWithDevices() }

async function syncRemoteCamera(camera) { if (!camera.rtspUrl) return; const response = await fetch(`${FACE_SERVICE_BASE}/cameras`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: camera.id, name: camera.name, rtspUrl: camera.rtspUrl, streamName: camera.streamName }) }); if (!response.ok) throw new Error(`camera save failed: ${response.status}`) }
async function removeRemoteCamera(cameraId) { const response = await fetch(`${FACE_SERVICE_BASE}/cameras/${encodeURIComponent(cameraId)}`, { method: 'DELETE' }); if (!response.ok && response.status !== 404) throw new Error(`camera delete failed: ${response.status}`) }
async function addCamera(record) { const normalized = normalizeCamera({ id: record.id || `camera_${Date.now()}`, name: record.name, rtspUrl: record.rtspUrl, streamName: record.streamName }, CAMERA_OPTIONS.length); await syncRemoteCamera(normalized); CAMERA_OPTIONS.push(normalized); persistCameras(); state.bindings.forEach((binding) => { if (!binding.faceChannelId) { binding.faceChannelId = normalized.id; faceMonitor.subscribeFace(binding) } }) }
async function updateCamera(record) { const index = CAMERA_OPTIONS.findIndex((item) => item.id === record.id); if (index === -1) return; const normalized = normalizeCamera(record, index); await syncRemoteCamera(normalized); CAMERA_OPTIONS[index] = normalized; persistCameras(); state.bindings.forEach((binding) => { if (binding.faceChannelId === record.id) faceMonitor.refreshFaceSubscription(binding.id) }); persistBindings() }
async function removeCamera(cameraId) { const index = CAMERA_OPTIONS.findIndex((item) => item.id === cameraId); if (index === -1) return; await removeRemoteCamera(cameraId); CAMERA_OPTIONS.splice(index, 1); persistCameras(); syncBindingsWithCameras() }

function formatShortTime(value) { const date = value ? new Date(value) : new Date(); if (Number.isNaN(date.getTime())) return '--:--:--'; return date.toLocaleTimeString('zh-CN', { hour12: false }) }
function getAlertType(binding) { if (!hasPrediction(binding)) return 'info'; if (binding.emotion === 'normal') return 'success'; if (binding.emotion === 'fatigue' || binding.emotion === 'weakness') return 'error'; return 'warning' }
function formatIndex(value) { return Number(value || 0).toFixed(1) }
function refreshFaceSubscription(bindingId) { faceMonitor.refreshFaceSubscription(bindingId) }
function updateBindingDevice(binding) { if (!binding) return; eegMonitor.stopEeg(binding.id, 'restart'); persistBindings(); eegMonitor.ensureAutoEeg(binding) }
function updateBindingCamera(binding) { if (!binding) return; faceMonitor.refreshFaceSubscription(binding.id); persistBindings() }
function useMonitorCenterPage() {
  onMounted(async () => {
    await initMonitorCenter()
    await nextTick()
    eegMonitor.ensureCharts(state.bindings)
    if (!fusionRefreshTimer) fusionRefreshTimer = window.setInterval(refreshFusionStates, 1000)
    window.addEventListener('resize', eegMonitor.resizeCharts)
  })
  onBeforeUnmount(() => window.removeEventListener('resize', eegMonitor.resizeCharts))
}

const overview = computed(() => ({ total: state.bindings.length, onlineCount: state.bindings.filter(hasAccess).length, warningCount: state.bindings.filter((item) => hasPrediction(item) && getWarningLevel(item) === 'warning').length, dangerCount: state.bindings.filter((item) => hasPrediction(item) && item.emotion !== 'normal').length }))

export function useMonitorCenter() {
  return { state, DEVICE_OPTIONS, CAMERA_OPTIONS, overview, initMonitorCenter, useMonitorCenterPage, addBinding, removeBinding, addPersonnel, updatePersonnel, removePersonnel, addDevice, updateDevice, removeDevice, addCamera, updateCamera, removeCamera, updateBindingPerson, updateBindingDevice, updateBindingCamera, persistBindings, getBindingById, getDeviceLabel, getCameraLabel, getDisplayEmotion: getDisplayEmotionText, getAccessText, getEegStatusLabel, getFaceStatusLabel, formatShortTime, setChartRef: eegMonitor.setChartRef, setBandChartRef: eegMonitor.setBandChartRef, refreshFaceSubscription, getWarningLevel, getWarningText: getWarningTextDisplay, getAlertType, formatIndex }
}
