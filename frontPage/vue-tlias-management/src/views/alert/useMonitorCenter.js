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
const MAX_MONITOR_BINDINGS = Number(import.meta.env.VITE_MAX_MONITOR_BINDINGS || 24)
const ALERT_LOG_DATE_CHECK_MS = 30000
const FACE_ABNORMAL_SAMPLE_HOLD_MS = 6000
const ABNORMAL_SAMPLE_COOLDOWN_MS = 120000
const VALID_EEG_HOLD_MS = 10000
const VALID_FACE_HOLD_MS = 8000
const ABNORMAL_POPUP_COOLDOWN_MS = 90000
const ABNORMAL_POPUP_STREAK_LIMIT = 2
const ALERT_HISTORY_COOLDOWN_MS = 90000
const ALERT_HISTORY_STREAK_LIMIT = 6
const STABLE_STATE_SEGMENT_MS = 20000
const EEG_SAMPLE_WEIGHT = 1
const FACE_SAMPLE_WEIGHT = 0.8
const FACE_FATIGUE_BOOST = 0.2
const FACE_MIN_CONFIDENCE = 0.5
const SEGMENT_MIN_SAMPLES = 3
const ABNORMAL_MIN_COUNT = 2
const ABNORMAL_MIN_RATIO = 0.18
const STABLE_TIE_MARGIN = 0.08
const EMPTY_SEGMENTS_BEFORE_WAITING = 2
const EYE_WINDOW_MS = 20000
const EYE_DETAIL_CONTINUOUS_MS = 6000
const EYE_MAIN_CONTINUOUS_MS = 12000
const EYE_MAIN_ALERT_COOLDOWN_MS = 60000
const EYE_MAX_SAMPLE_GAP_MS = 3500
let fusionRefreshTimer = null
let alertLogDateTimer = null

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

const EYE_TEXT = {
  waiting: '\u7b49\u5f85\u6709\u6548\u4eba\u8138',
  invalid: '\u7b49\u5f85\u6709\u6548\u773c\u90e8\u753b\u9762',
  closed: '\u95ed\u773c',
  open: '\u7741\u773c',
  currentPerson: '\u5f53\u524d\u4eba\u5458',
  mainTitle: '\u95ed\u773c\u544a\u8b66'
}


const ABNORMAL_EMOTIONS = ['fatigue', 'stress', 'anxiety', 'weakness']
const VALID_EMOTIONS = ['normal', ...ABNORMAL_EMOTIONS]

const DEVICE_OPTIONS = reactive([])
const CAMERA_OPTIONS = reactive([])

const state = reactive({ initialized: false, bindings: [], personnelOptions: [], alertHistory: [], alertHistoryDate: '' })

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
    lastValidEegEmotion: '', lastValidEegAt: 0, lastRecordedEegSampleAt: 0, eegFusionCandidate: '', eegFusionStreak: 0, reasonCodes: [], features: {},
    emotion: 'normal', emotionZh: EMOTION_ZH.normal, fusionEmotion: 'normal', fusionEmotionZh: EMOTION_ZH.normal, fusionSource: 'waiting',
    stateSamples: [], committedEmotion: '', committedEmotionZh: '', stableEmotion: 'normal', stableEmotionZh: EMOTION_ZH.normal,
    stableSegmentStartedAt: 0, stableUpdatedAt: 0, stableConfidence: 0, stableWindowMs: STABLE_STATE_SEGMENT_MS,
    stableSampleCounts: { eeg: 0, face: 0 }, emptyStableSegments: 0,
    analysisTime: '', calibrationProgress: 0, baselineResetReason: '', baselineResetAt: '',
    indices: { anxiety_idx: 0, stress_idx: 0, fatigue_idx: 0, weakness_idx: 0 }, probs: {},
    bandSnapshot: { delta: 0, theta: 0, alpha: 0, beta: 0, gamma: 0 }, rawWaveBuffer: [], waveScale: 1,
    faceConnected: false, faceImageUrl: '', faceStatusText: '待接入', faceStatus: 'idle', faceEmotion: '未识别', faceEmotionKey: '', faceScore: '--', faceRate: '--', faceRank: null, faceBox: null,
    lastValidFaceEmotion: '', lastValidFaceEmotionZh: '', lastValidFaceAt: 0, lastValidFaceScore: 0, lastRecordedFaceSampleAt: 0, faceAssistStreak: 0, faceStopRequired: false,
    eyeStatus: 'waiting', eyeStatusText: EYE_TEXT.waiting, eyeClosed: null, eyeClosedScore: 0, eyeOpenScore: 0, eyeBoxes: [], eyeLastValidAt: 0,
    eyeSamples: [],
    eyeClosedStartedAt: 0, eyeCurrentClosedStartedAt: 0, eyeMaxContinuousClosedMs: 0, eyeTotalClosedMs: 0, eyeContinuousClosedMs: 0,
    eyeDetailPopupActive: false, eyeDetailPopupWindowId: 0, eyeDetailPopupAt: 0, eyePopupLevel: '', eyePopupDismissedAt: 0,
    eyeOpenStartedAt: 0, eyeContinuousOpenMs: 0, eyeMainAlertActive: false, eyeMainAlertWindowId: 0, eyeLastAlertAt: 0, eyeClosedAlertStage: '',
    videoUploading: false, uploadPercent: 0, localVideoUrl: '', videoWidth: 0, videoHeight: 0,
    fatigueStreak: 0, abnormalPopupCandidate: '', abnormalPopupStreak: 0, alertHistoryStreak: 0, lastPopupAt: 0, lastAlertHistoryAt: 0,
    faceAbnormalStartedAt: 0, lastAbnormalSampleAt: 0, lastAbnormalSampleStatus: '',
    hasPopupWarning: false, popupWarningActive: false, popupWarningEmotion: '', latestWarningLevel: 'info', latestEmotion: 'normal', faceSubscription: null
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
function hasCommittedState(binding) { return Boolean(binding?.stableUpdatedAt) }
function hasPrediction(binding) { return Boolean(binding && hasCommittedState(binding)) }
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
  clearHistorySamples(binding)
  binding.personName = selected?.name || ''
  binding.personType = selected?.type || ''
  persistBindings()
  if (!auto) return
  if (!binding.personId) eegMonitor.stopEeg(binding.id, 'restart')
  else eegMonitor.ensureAutoEeg(binding)
}

function getWarningLevel(binding) { return binding.emotion === 'normal' ? 'info' : 'warning' }
function getWarningText(binding) { if (!hasPrediction(binding)) return '等待有效数据'; return EMOTION_WARNING_TEXT[binding.emotion] || EMOTION_WARNING_TEXT.normal }
function getDisplayEmotionText(binding) { return getCurrentStatusText(binding) }
function getWarningTextDisplay(binding) {
  if (!hasPrediction(binding)) return getCurrentStatusText(binding)
  return EMOTION_WARNING_TEXT[binding.emotion] || EMOTION_WARNING_TEXT.normal
}

function getLocalDateKey(value = Date.now()) {
  const date = new Date(value)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatAlertTime(value) {
  const date = value ? new Date(value) : new Date()
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function normalizeAlertLog(item = {}) {
  const timestamp = Number(item.timestamp || Date.now())
  return {
    id: String(item.id || `alert-${timestamp}-${Math.random().toString(36).slice(2, 8)}`),
    date: item.date || getLocalDateKey(timestamp),
    timestamp,
    personName: item.personName || '未绑定人员',
    personId: item.personId || '',
    device: item.device || '未配置设备',
    level: item.level || 'warning',
    type: item.type || 'abnormal_start',
    time: item.time || formatAlertTime(timestamp),
    message: item.message || ''
  }
}

function sortAlertHistory() {
  state.alertHistory.sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0))
}

async function loadAlertHistory(date = getLocalDateKey()) {
  try {
    const endpoint = date === getLocalDateKey()
      ? `${FACE_SERVICE_BASE}/alert-logs/today`
      : `${FACE_SERVICE_BASE}/alert-logs?date=${encodeURIComponent(date)}`
    const response = await fetch(endpoint)
    if (!response.ok) throw new Error(`alert log load failed: ${response.status}`)
    const payload = await response.json()
    const logs = Array.isArray(payload?.data) ? payload.data.map(normalizeAlertLog) : []
    state.alertHistoryDate = date
    state.alertHistory.splice(0, state.alertHistory.length, ...logs)
    sortAlertHistory()
  } catch (error) {
    console.warn('Failed to load alert logs', error)
    state.alertHistoryDate = date
  }
}

function ensureTodayAlertHistory({ reload = true } = {}) {
  const today = getLocalDateKey()
  if (state.alertHistoryDate === today) return
  state.alertHistoryDate = today
  state.alertHistory.splice(0, state.alertHistory.length)
  if (reload) void loadAlertHistory(today)
}

async function persistAlertHistoryItem(item) {
  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/alert-logs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: item.id,
        date: item.date,
        timestamp: item.timestamp,
        personName: item.personName,
        personId: item.personId,
        device: item.device,
        level: item.level,
        type: item.type,
        message: item.message
      })
    })
    if (!response.ok) throw new Error(`alert log save failed: ${response.status}`)
  } catch (error) {
    console.warn('Failed to persist alert log', error)
  }
}

function pushAlertHistory(binding, level, message = getWarningText(binding), type = 'abnormal_start') {
  ensureTodayAlertHistory({ reload: false })
  const timestamp = Date.now()
  const item = normalizeAlertLog({
    id: `${binding.id}-${timestamp}-${type}`,
    date: getLocalDateKey(timestamp),
    timestamp,
    personName: binding.personName || '未绑定人员',
    personId: binding.personId || '',
    device: getDeviceLabel(binding.workerId),
    level,
    type,
    message
  })
  state.alertHistory.unshift(item)
  void persistAlertHistoryItem(item)
}

async function captureAbnormalSample(binding, payload = {}) {
  const timestamp = Date.now()
  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/abnormal-samples`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        eventId: `${binding.id}-${timestamp}-face-abnormal`,
        timestamp,
        personId: binding.personId || '',
        personName: binding.personName || '未绑定人员',
        workerId: binding.workerId,
        cameraId: binding.faceChannelId || payload.userId || '',
        alertType: 'face_abnormal',
        emotion: payload.emotion5 || binding.faceEmotionKey || '',
        message: `${binding.personName || '当前人员'} 面部状态持续异常`
      })
    })
    if (!response.ok) throw new Error(`abnormal sample capture failed: ${response.status}`)
    const result = await response.json()
    binding.lastAbnormalSampleStatus = result?.data?.captureStatus || 'ok'
  } catch (error) {
    binding.lastAbnormalSampleStatus = 'failed'
    console.warn('Failed to capture abnormal sample', error)
  }
}

function maybeTriggerAbnormalSample(binding, payload = {}) {
  if (!binding) return
  const emotion = payload.emotion5 || ''
  const now = Date.now()
  if (!ABNORMAL_EMOTIONS.includes(emotion)) {
    binding.faceAbnormalStartedAt = 0
    return
  }
  if (!binding.faceAbnormalStartedAt) binding.faceAbnormalStartedAt = now
  if (now - Number(binding.faceAbnormalStartedAt || 0) < FACE_ABNORMAL_SAMPLE_HOLD_MS) return
  if (now - Number(binding.lastAbnormalSampleAt || 0) < ABNORMAL_SAMPLE_COOLDOWN_MS) return
  binding.lastAbnormalSampleAt = now
  void captureAbnormalSample(binding, payload)
}

function parsePercent(value) {
  if (value == null || value === '') return 0
  const numeric = Number.parseFloat(String(value).replace('%', ''))
  return Number.isFinite(numeric) ? numeric : 0
}

function getEyeStatusText(payload) {
  if (!payload || payload.eyeStatus === 'no_face') return EYE_TEXT.waiting
  if (payload.eyeStatus === 'invalid' || payload.eyeStatus === 'invalid_eye') return EYE_TEXT.invalid
  if (payload.eyeClosed === true) return EYE_TEXT.closed
  if (payload.eyeClosed === false) return EYE_TEXT.open
  return EYE_TEXT.waiting
}

function stopEyeTiming(binding) {
  binding.eyeClosedStartedAt = 0
  binding.eyeCurrentClosedStartedAt = 0
  binding.eyeOpenStartedAt = 0
  binding.eyeContinuousClosedMs = 0
  binding.eyeContinuousOpenMs = 0
}

function resetEyeAlertStage(binding) {
  binding.eyeDetailPopupActive = false
  binding.eyeMainAlertActive = false
  binding.eyePopupLevel = ''
  binding.eyeClosedAlertStage = ''
}

function trimEyeSamples(binding, now = Date.now()) {
  const cutoff = now - EYE_WINDOW_MS
  binding.eyeSamples.splice(0, binding.eyeSamples.length, ...binding.eyeSamples.filter((sample) => Number(sample.ts || 0) >= cutoff))
}

function summarizeEyeWindow(binding, now = Date.now()) {
  trimEyeSamples(binding, now)
  const samples = [...binding.eyeSamples].sort((a, b) => Number(a.ts || 0) - Number(b.ts || 0))
  let totalClosedMs = 0
  let maxContinuousClosedMs = 0
  let currentClosedMs = 0
  let currentClosedStartedAt = 0
  let previousClosedTs = 0
  let latestOpenStartedAt = 0

  samples.forEach((sample) => {
    const ts = Number(sample.ts || 0)
    if (!ts) return
    if (!sample.closed) {
      currentClosedMs = 0
      currentClosedStartedAt = 0
      previousClosedTs = 0
      latestOpenStartedAt = ts
      return
    }
    if (!currentClosedStartedAt || !previousClosedTs || ts - previousClosedTs > EYE_MAX_SAMPLE_GAP_MS) {
      currentClosedStartedAt = ts
      currentClosedMs = 0
    } else {
      const gap = Math.max(0, ts - previousClosedTs)
      currentClosedMs += gap
      totalClosedMs += gap
      maxContinuousClosedMs = Math.max(maxContinuousClosedMs, currentClosedMs)
    }
    previousClosedTs = ts
  })

  const latestSample = samples[samples.length - 1]
  if (latestSample?.closed && previousClosedTs && now - previousClosedTs <= EYE_MAX_SAMPLE_GAP_MS) {
    const tailGap = Math.max(0, now - previousClosedTs)
    currentClosedMs += tailGap
    totalClosedMs += tailGap
    maxContinuousClosedMs = Math.max(maxContinuousClosedMs, currentClosedMs)
  }

  binding.eyeCurrentClosedStartedAt = currentClosedStartedAt
  binding.eyeClosedStartedAt = currentClosedStartedAt
  binding.eyeOpenStartedAt = latestSample && !latestSample.closed ? latestOpenStartedAt : 0
  binding.eyeContinuousClosedMs = latestSample?.closed ? currentClosedMs : 0
  binding.eyeContinuousOpenMs = latestSample && !latestSample.closed ? Math.max(0, now - latestOpenStartedAt) : 0
  binding.eyeMaxContinuousClosedMs = maxContinuousClosedMs
  binding.eyeTotalClosedMs = totalClosedMs
}

function maybeTriggerEyeAlerts(binding, now = Date.now()) {
  if (binding.eyeMaxContinuousClosedMs < EYE_DETAIL_CONTINUOUS_MS) {
    resetEyeAlertStage(binding)
    return
  }

  if (binding.eyeMaxContinuousClosedMs < EYE_MAIN_CONTINUOUS_MS) {
    binding.eyeDetailPopupWindowId = now
    binding.eyeDetailPopupActive = true
    binding.eyeDetailPopupAt = now
    binding.eyePopupLevel = 'warning'
    binding.eyeClosedAlertStage = 'detail'
    binding.eyeMainAlertActive = false
    return
  }

  binding.eyeMainAlertWindowId = now
  binding.eyeDetailPopupActive = true
  binding.eyeDetailPopupAt = now
  binding.eyePopupLevel = 'danger'
  binding.eyeMainAlertActive = true
  const shouldNotifyMain = binding.eyeClosedAlertStage !== 'danger' && now - Number(binding.eyeLastAlertAt || 0) >= EYE_MAIN_ALERT_COOLDOWN_MS
  binding.eyeClosedAlertStage = 'danger'
  if (!shouldNotifyMain) return
  binding.eyeLastAlertAt = now
  const personName = binding.personName || EYE_TEXT.currentPerson
  const message = `\u68c0\u6d4b\u5230 ${personName} \u8fde\u7eed\u95ed\u773c\u8d85\u8fc712\u79d2\uff0c\u8bf7\u6ce8\u610f\u5f53\u524d\u72b6\u6001`
  pushAlertHistory(binding, 'warning', message, 'eye_closed_danger')
  ElNotification({ title: EYE_TEXT.mainTitle, message, type: 'error', duration: 5000, showClose: true, position: 'top-right', customClass: 'strong-alert-notification danger' })
}

function updateEyeState(binding, payload = {}) {
  if (!binding) return
  const now = Number(payload.timestamp || payload.eyeCheckedAt || Date.now())
  const closedScore = parsePercent(payload.eyeClosedScore)
  const openScore = parsePercent(payload.eyeOpenScore)
  const hasValidEye = payload.status === 'ok' && (payload.eyeClosed === true || payload.eyeClosed === false) && ['open', 'closed'].includes(payload.eyeStatus)

  binding.eyeStatus = payload.eyeStatus || 'waiting'
  binding.eyeStatusText = getEyeStatusText(payload)
  if (hasValidEye) binding.eyeClosed = payload.eyeClosed === true
  binding.eyeClosedScore = closedScore
  binding.eyeOpenScore = openScore
  binding.eyeBoxes = Array.isArray(payload.eyeBoxes) ? payload.eyeBoxes : []

  if (!hasValidEye) {
    summarizeEyeWindow(binding, Date.now())
    maybeTriggerEyeAlerts(binding, Date.now())
    return
  }

  const isClosedSample = payload.eyeClosed === true
  binding.eyeLastValidAt = now
  binding.eyeSamples.push({ ts: now, closed: isClosedSample, closedScore, openScore })
  summarizeEyeWindow(binding, now)
  maybeTriggerEyeAlerts(binding, now)
}

function normalizeEmotionKey(emotion) {
  return VALID_EMOTIONS.includes(emotion) ? emotion : 'normal'
}

function clearHistorySamples(binding, source = '') {
  if (!binding) return
  if (!source) binding.stateSamples.splice(0, binding.stateSamples.length)
  else binding.stateSamples.splice(0, binding.stateSamples.length, ...binding.stateSamples.filter((sample) => sample.source !== source))
  if (!binding.stateSamples.length) {
    binding.committedEmotion = ''
    binding.committedEmotionZh = ''
    binding.stableEmotion = 'normal'
    binding.stableEmotionZh = EMOTION_ZH.normal
    binding.stableSegmentStartedAt = 0
    binding.stableUpdatedAt = 0
    binding.stableConfidence = 0
    binding.stableSampleCounts = { eeg: 0, face: 0 }
    binding.emptyStableSegments = 0
    binding.emotion = 'normal'
    binding.emotionZh = EMOTION_ZH.normal
    binding.fusionEmotion = 'normal'
    binding.fusionEmotionZh = EMOTION_ZH.normal
    binding.fusionSource = 'waiting'
  }
  if (!source || source === 'eeg') binding.lastRecordedEegSampleAt = 0
  if (!source || source === 'face') {
    binding.lastRecordedFaceSampleAt = 0
    binding.eyeSamples.splice(0, binding.eyeSamples.length)
    binding.eyeStatus = 'waiting'
    binding.eyeStatusText = EYE_TEXT.waiting
    binding.eyeClosed = null
    binding.eyeClosedScore = 0
    binding.eyeOpenScore = 0
    binding.eyeBoxes = []
    binding.eyeLastValidAt = 0
    binding.eyeClosedStartedAt = 0
    binding.eyeCurrentClosedStartedAt = 0
    binding.eyeMaxContinuousClosedMs = 0
    binding.eyeTotalClosedMs = 0
    binding.eyeContinuousClosedMs = 0
    binding.eyeDetailPopupActive = false
    binding.eyePopupLevel = ''
    binding.eyePopupDismissedAt = 0
    binding.eyeOpenStartedAt = 0
    binding.eyeContinuousOpenMs = 0
    binding.eyeMainAlertActive = false
    binding.eyeClosedAlertStage = ''
  }
}

function pushStateSample(binding, sample) {
  if (!binding) return
  const emotion = normalizeEmotionKey(sample.emotion)
  const baseWeight = Number(sample.weight || 1)
  const weight = sample.source === 'face' && emotion === 'fatigue' ? baseWeight + FACE_FATIGUE_BOOST : baseWeight
  binding.stateSamples.push({
    source: sample.source,
    emotion,
    ts: Number(sample.ts || Date.now()),
    weight,
    confidence: Number(sample.confidence || 1)
  })
}

function recordLatestSensorSamples(binding, now = Date.now()) {
  if (hasFreshEeg(binding, now) && binding.lastValidEegAt !== binding.lastRecordedEegSampleAt) {
    pushStateSample(binding, {
      source: 'eeg',
      emotion: binding.lastValidEegEmotion,
      ts: binding.lastValidEegAt,
      weight: EEG_SAMPLE_WEIGHT,
      confidence: 1
    })
    binding.lastRecordedEegSampleAt = binding.lastValidEegAt
  }

  const faceConfidence = Math.min(1, Math.max(0, Number(binding.lastValidFaceScore || 0) / 100))
  if (hasFreshFace(binding, now) && binding.lastValidFaceAt !== binding.lastRecordedFaceSampleAt && faceConfidence >= FACE_MIN_CONFIDENCE) {
    pushStateSample(binding, {
      source: 'face',
      emotion: binding.lastValidFaceEmotion,
      ts: binding.lastValidFaceAt,
      weight: FACE_SAMPLE_WEIGHT,
      confidence: faceConfidence
    })
    binding.lastRecordedFaceSampleAt = binding.lastValidFaceAt
  }
}

function summarizeSamples(samples) {
  return samples.reduce((summary, sample) => {
    const emotion = normalizeEmotionKey(sample.emotion)
    summary.totalWeight += Number(sample.weight || 0)
    summary.counts[emotion] = (summary.counts[emotion] || 0) + 1
    summary.weights[emotion] = (summary.weights[emotion] || 0) + Number(sample.weight || 0)
    return summary
  }, { totalWeight: 0, counts: {}, weights: {} })
}

function keepPreviousOnCloseRace(binding, ranked) {
  if (!ranked.length) return null
  if (ranked.length < 2) return ranked[0]
  const [first, second] = ranked
  if (first.ratio - second.ratio >= STABLE_TIE_MARGIN) return first
  return ranked.find((item) => item.emotion === binding.stableEmotion) || first
}

function getSampleCounts(samples) {
  return samples.reduce((counts, sample) => {
    if (sample.source === 'eeg') counts.eeg += 1
    if (sample.source === 'face') counts.face += 1
    return counts
  }, { eeg: 0, face: 0 })
}

function chooseStableSegmentEmotion(binding, samples) {
  const counts = getSampleCounts(samples)
  if (samples.length < SEGMENT_MIN_SAMPLES) {
    return { commit: false, counts, emotion: binding.stableEmotion || 'normal', confidence: binding.stableConfidence / 100, source: 'insufficient' }
  }

  const summary = summarizeSamples(samples)
  const denominator = Math.max(summary.totalWeight, 1)
  const ranked = ABNORMAL_EMOTIONS.map((emotion) => ({
    emotion,
    score: Number(summary.weights[emotion] || 0),
    count: Number(summary.counts[emotion] || 0),
    ratio: Number(summary.weights[emotion] || 0) / denominator
  })).filter((item) => item.count >= ABNORMAL_MIN_COUNT && item.ratio >= ABNORMAL_MIN_RATIO)
    .sort((a, b) => b.ratio - a.ratio || b.score - a.score)
  const selected = keepPreviousOnCloseRace(binding, ranked)
  if (selected) return { commit: true, counts, emotion: selected.emotion, confidence: selected.ratio, source: 'segment' }
  return {
    commit: true,
    counts,
    emotion: 'normal',
    confidence: Number(summary.weights.normal || 0) / denominator,
    source: 'segment'
  }
}

function commitStableSegment(binding, result, now) {
  const emotion = normalizeEmotionKey(result.emotion)
  binding.committedEmotion = emotion
  binding.committedEmotionZh = EMOTION_ZH[emotion] || EMOTION_ZH.normal
  binding.stableEmotion = emotion
  binding.stableEmotionZh = binding.committedEmotionZh
  binding.stableUpdatedAt = now
  binding.stableConfidence = Math.round(Math.min(1, Math.max(0, Number(result.confidence || 0))) * 100)
  binding.stableSampleCounts = result.counts || { eeg: 0, face: 0 }
  binding.fusionEmotion = binding.stableEmotion
  binding.fusionEmotionZh = binding.stableEmotionZh
  binding.emotion = binding.stableEmotion
  binding.emotionZh = binding.stableEmotionZh
  binding.fusionSource = result.source || 'segment'
}

function resetCommittedStateToWaiting(binding) {
  binding.committedEmotion = ''
  binding.committedEmotionZh = ''
  binding.stableEmotion = 'normal'
  binding.stableEmotionZh = EMOTION_ZH.normal
  binding.stableUpdatedAt = 0
  binding.stableConfidence = 0
  binding.stableSampleCounts = { eeg: 0, face: 0 }
  binding.fusionEmotion = 'normal'
  binding.fusionEmotionZh = EMOTION_ZH.normal
  binding.emotion = 'normal'
  binding.emotionZh = EMOTION_ZH.normal
  binding.fusionSource = 'waiting'
}

function ensureStableSegment(binding, now = Date.now()) {
  if (!binding.stableSegmentStartedAt) binding.stableSegmentStartedAt = now
}

function settleStableSegments(binding, now = Date.now()) {
  ensureStableSegment(binding, now)
  let committed = false
  while (now - Number(binding.stableSegmentStartedAt || now) >= STABLE_STATE_SEGMENT_MS) {
    const segmentEnd = Number(binding.stableSegmentStartedAt) + STABLE_STATE_SEGMENT_MS
    const segmentSamples = binding.stateSamples.filter((sample) => Number(sample.ts || 0) < segmentEnd)
    const remainingSamples = binding.stateSamples.filter((sample) => Number(sample.ts || 0) >= segmentEnd)
    const result = chooseStableSegmentEmotion(binding, segmentSamples)

    if (!segmentSamples.length) {
      binding.emptyStableSegments = Number(binding.emptyStableSegments || 0) + 1
      if (binding.emptyStableSegments >= EMPTY_SEGMENTS_BEFORE_WAITING) resetCommittedStateToWaiting(binding)
    } else {
      binding.emptyStableSegments = 0
      if (result.commit) {
        commitStableSegment(binding, result, segmentEnd)
        committed = true
      }
    }

    binding.stateSamples.splice(0, binding.stateSamples.length, ...remainingSamples)
    binding.stableSegmentStartedAt = segmentEnd
  }
  return committed
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
  pushAlertHistory(binding, 'warning', getWarningText(binding), 'abnormal_start')
  ElNotification({ title: '状态提醒', message: `${binding.personName || '当前人员'} 检测为${binding.emotionZh}，请关注当前状态。`, type: 'warning', duration: 7000, showClose: true, position: 'top-right', customClass: 'strong-alert-notification' })
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
  const now = Date.now()
  const committed = settleStableSegments(binding, now)
  recordLatestSensorSamples(binding, now)
  if (committed) maybeShowAbnormalNotification(binding)
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
    // Eye detection alerts are disabled on main; develop keeps this workflow.
    // summarizeEyeWindow(binding, now)
    // maybeTriggerEyeAlerts(binding, now)
    updateFusionState(binding)
    if (hadPrediction || hasPrediction(binding)) evaluateWarning(binding)
  })
}

function evaluateWarning(binding) {
  const level = getWarningLevel(binding)
  if (!hasPrediction(binding)) return
  if (shouldRecordAlertHistory(binding, level)) {
    pushAlertHistory(binding, level, getWarningText(binding), binding.emotion === 'normal' ? 'recovered' : 'abnormal_start')
  }
  binding.latestWarningLevel = level
  binding.latestEmotion = binding.emotion
}

const eegMonitor = createEegMonitor({ state, getBindingById, getDeviceLabel, evaluateWarning, updateFusionState })
const faceMonitor = createFaceMonitor({
  state,
  getBindingById,
  updateBindingPerson,
  evaluateWarning,
  updateFusionState,
  // Eye detection alerts are disabled on main; develop keeps updateEyeState wired in.
  // updateEyeState,
  maybeTriggerAbnormalSample
})

function syncBindingsWithDevices() {
  const fallbackWorkerId = DEVICE_OPTIONS[0]?.value ?? null
  state.bindings.forEach((binding) => { if (!DEVICE_OPTIONS.some((item) => item.value === binding.workerId)) { eegMonitor.stopEeg(binding.id, 'restart'); binding.workerId = fallbackWorkerId; binding.activeWorkerId = null; eegMonitor.ensureAutoEeg(binding) } })
  persistBindings()
}
function syncBindingsWithPersonnel() { state.bindings.forEach((binding) => { if (!state.personnelOptions.some((item) => item.id === binding.personId || item.uid === binding.personId)) { eegMonitor.stopEeg(binding.id, 'restart'); binding.personId = ''; binding.personName = ''; binding.personType = ''; return } updateBindingPerson(binding) }); persistBindings() }
function syncBindingsWithCameras() { const fallbackCameraId = getDefaultCameraId(); state.bindings.forEach((binding) => { if (!CAMERA_OPTIONS.some((item) => item.id === binding.faceChannelId)) { faceMonitor.unsubscribeFace(binding.id); binding.faceChannelId = fallbackCameraId; faceMonitor.subscribeFace(binding) } }); persistBindings() }

async function initMonitorCenter() {
  if (state.initialized) return
  await Promise.all([loadPersonnel(), loadDevices(), loadCameras(), loadAlertHistory()])
  loadBindings(); syncBindingsWithDevices(); syncBindingsWithCameras(); faceMonitor.ensureFaceConnection(); state.bindings.forEach((binding) => faceMonitor.subscribeFace(binding)); eegMonitor.ensureAllAutoEeg(); state.initialized = true
}

function addBinding() { if (state.bindings.length >= MAX_MONITOR_BINDINGS) { ElMessage.warning(`最多同时监测 ${MAX_MONITOR_BINDINGS} 张卡片`); return } const binding = createBinding(state.bindings.length + 1); state.bindings.push(binding); persistBindings(); faceMonitor.subscribeFace(binding); eegMonitor.ensureAutoEeg(binding) }
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
function updateBindingDevice(binding) { if (!binding) return; clearHistorySamples(binding, 'eeg'); eegMonitor.stopEeg(binding.id, 'restart'); persistBindings(); eegMonitor.ensureAutoEeg(binding) }
function updateBindingCamera(binding) { if (!binding) return; clearHistorySamples(binding, 'face'); faceMonitor.refreshFaceSubscription(binding.id); persistBindings() }
function startAlertLogDateWatcher() {
  ensureTodayAlertHistory()
  if (!alertLogDateTimer) alertLogDateTimer = window.setInterval(ensureTodayAlertHistory, ALERT_LOG_DATE_CHECK_MS)
}
function useMonitorCenterPage() {
  onMounted(async () => {
    await initMonitorCenter()
    startAlertLogDateWatcher()
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
