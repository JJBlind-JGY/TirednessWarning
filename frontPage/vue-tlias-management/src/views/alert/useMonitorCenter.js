import { computed, nextTick, onBeforeUnmount, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { createEegMonitor } from './useAlertEeg'
import { createFaceMonitor } from './useAlertFace'

const PERSONNEL_STORAGE_KEY = 'alert-personnel-options'
const DEVICE_STORAGE_KEY = 'alert-device-options'
const CAMERA_STORAGE_KEY = 'alert-camera-options'
const BINDINGS_STORAGE_KEY = 'alert-bindings'
const FACE_FATIGUE_USER_ID = 'camera_001'
const FACE_SERVICE_BASE = '/face-api/faceDetectService'

const DEFAULT_PERSONNEL = []
const DEFAULT_DEVICES = []
const DEFAULT_CAMERAS = []

const DEVICE_OPTIONS = reactive([])
const CAMERA_OPTIONS = reactive([])

const state = reactive({
  initialized: false,
  bindings: [],
  personnelOptions: [],
  alertHistory: []
})

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
  return {
    id: String(item.id || uid),
    uid,
    name: String(item.name || `人员 ${index + 1}`),
    type: String(item.type || '未分类')
  }
}

function normalizeDevice(item, index = 0) {
  const value = Number(item.value ?? item.workerId ?? index + 1)
  const name = String(item.name || `设备 ${value}`)
  const port = String(item.port || '')
  return {
    value,
    name,
    port,
    label: port ? `${name} / ${port}` : name
  }
}

function normalizeCamera(item, index = 0) {
  const id = String(item.id || item.faceChannelId || item.cameraId || `camera_${String(index + 1).padStart(3, '0')}`)
  const name = String(item.name || `摄像头 ${index + 1}`)
  const rtspUrl = String(item.rtspUrl || '')
  return {
    id,
    name,
    rtspUrl,
    label: `${name} / ${id}`
  }
}

async function loadPersonnel() {
  const items = DEFAULT_PERSONNEL.map(normalizePersonnel)

  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/personnel`)
    if (response.ok) {
      const payload = await response.json()
      const personnel = Array.isArray(payload?.data) ? payload.data : []
      replaceArray(items, personnel.map(normalizePersonnel))
    }
  } catch (error) {
    console.warn('Failed to load remote personnel config', error)
  }

  replaceArray(state.personnelOptions, items)
  persistPersonnel()
}

async function loadDevices() {
  const items = DEFAULT_DEVICES.map(normalizeDevice)

  try {
    const response = await fetch('/eeg/devices')
    if (response.ok) {
      const payload = await response.json()
      const eegDevices = Array.isArray(payload?.data) ? payload.data : []
      replaceArray(items, eegDevices.map(normalizeDevice))
    }
  } catch (error) {
    console.warn('Failed to load remote eeg device config', error)
  }

  replaceArray(DEVICE_OPTIONS, items)
  persistDevices()
}

async function loadCameras() {
  const items = DEFAULT_CAMERAS.map(normalizeCamera)

  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/cameras`)
    if (response.ok) {
      const payload = await response.json()
      const cameras = Array.isArray(payload?.data) ? payload.data : []
      replaceArray(items, cameras.map(normalizeCamera))
    }
  } catch (error) {
    console.warn('Failed to load remote camera config', error)
  }

  replaceArray(CAMERA_OPTIONS, items)
  persistCameras()
}

function persistPersonnel() {
  writeLocalList(
    PERSONNEL_STORAGE_KEY,
    state.personnelOptions.map(({ id, uid, name, type }) => ({ id, uid, name, type }))
  )
}

function persistDevices() {
  writeLocalList(
    DEVICE_STORAGE_KEY,
    DEVICE_OPTIONS.map(({ value, name, port }) => ({
      value,
      name,
      port
    }))
  )
}

function persistCameras() {
  writeLocalList(
    CAMERA_STORAGE_KEY,
    CAMERA_OPTIONS.map(({ id, name, rtspUrl }) => ({
      id,
      name,
      rtspUrl
    }))
  )
}

function normalizeBinding(item, index = 0) {
  const binding = createBinding(index + 1)

  Object.assign(binding, {
    id: item.id || binding.id,
    personId: item.personId || '',
    personName: item.personName || '',
    personType: item.personType || '',
    workerId: item.workerId ?? binding.workerId,
    activeWorkerId: null,
    faceChannelId: item.faceChannelId || getDefaultCameraId(),
    eegRunning: false,
    eegStatus: 'idle',
    eegStatusText: '待接入',
    faceConnected: false,
    faceStatusText: '待接入',
    faceSubscription: null
  })

  updateBindingPerson(binding)
  return binding
}

function loadBindings() {
  const stored = readLocalList(BINDINGS_STORAGE_KEY, [])
  state.bindings = stored.map(normalizeBinding)
}

function persistBindings() {
  writeLocalList(
    BINDINGS_STORAGE_KEY,
    state.bindings.map((binding) => ({
      id: binding.id,
      personId: binding.personId,
      personName: binding.personName,
      personType: binding.personType,
      workerId: binding.workerId,
      faceChannelId: binding.faceChannelId
    }))
  )
}


function createBinding(seed = 1) {
  const defaultWorkerId = DEVICE_OPTIONS[(seed - 1) % Math.max(DEVICE_OPTIONS.length, 1)]?.value ?? null
  return reactive({
    id: `binding-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    personId: '',
    personName: '',
    personType: '',
    workerId: defaultWorkerId,
    activeWorkerId: null,
    faceChannelId: getDefaultCameraId(),
    eegRunning: false,
    eegStatus: 'idle',
    eegStatusText: '待接入',
    emotion: 'normal',
    emotionZh: '正常',
    analysisTime: '',
    calibrationProgress: 0,
    indices: {
      anxiety_idx: 0,
      stress_idx: 0,
      fatigue_idx: 0,
      weakness_idx: 0
    },
    probs: {},
    bandSnapshot: {
      delta: 0,
      theta: 0,
      alpha: 0,
      beta: 0,
      gamma: 0
    },
    rawWaveBuffer: [],
    waveScale: 1,
    faceConnected: false,
    faceImageUrl: '',
    faceStatusText: '待接入',
    faceEmotion: '未识别',
    faceScore: '--',
    faceRate: '--',
    faceRank: null,
    faceStopRequired: false,
    videoUploading: false,
    uploadPercent: 0,
    localVideoUrl: '',
    videoWidth: 0,
    videoHeight: 0,
    latestWarningLevel: 'info',
    latestEmotion: 'normal',
    faceSubscription: null
  })
}

function getBindingById(bindingId) {
  return state.bindings.find((item) => item.id === bindingId)
}

function getDeviceLabel(workerId) {
  return DEVICE_OPTIONS.find((item) => item.value === workerId)?.label || '未配置设备'
}

function getCameraLabel(cameraId) {
  return CAMERA_OPTIONS.find((item) => item.id === cameraId)?.label || '未配置摄像头'
}

function getDefaultCameraId() {
  return CAMERA_OPTIONS[0]?.id || ''
}

function updateBindingPerson(binding) {
  const selected = state.personnelOptions.find((item) => item.id === binding.personId || item.uid === binding.personId)
  binding.personName = selected?.name || ''
  binding.personType = selected?.type || ''
}

function getWarningLevel(binding) {
  return binding.emotion === 'normal' ? 'info' : 'warning'
}

function getWarningText(binding) {
  if (binding.eegStatus === 'calibrating') return '脑电正在基线校准，暂不输出最终预警'
  if (binding.emotion === 'anxiety') return '预警：当前状态为焦虑'
  if (binding.emotion === 'stress') return '预警：当前状态为紧张'
  if (binding.emotion === 'fatigue') return '预警：当前状态为疲劳'
  if (binding.emotion === 'weakness') return '预警：当前状态为虚弱'
  return '预警：当前状态正常'
}

function evaluateWarning(binding) {
  const level = getWarningLevel(binding)
  if (binding.latestWarningLevel !== level || binding.emotion !== binding.latestEmotion) {
    state.alertHistory.unshift({
      id: `${binding.id}-${Date.now()}`,
      personName: binding.personName || '未绑定人员',
      device: getDeviceLabel(binding.workerId),
      level,
      time: new Date().toLocaleString('zh-CN', { hour12: false }),
      message: getWarningText(binding)
    })
    if (state.alertHistory.length > 12) {
      state.alertHistory.length = 12
    }
  }
  binding.latestWarningLevel = level
  binding.latestEmotion = binding.emotion
}

const eegMonitor = createEegMonitor({
  state,
  getBindingById,
  getDeviceLabel,
  evaluateWarning
})

const faceMonitor = createFaceMonitor({
  state,
  getBindingById,
  updateBindingPerson,
  evaluateWarning
})

// function syncBindingsWithDevices() {
//   const fallbackWorkerId = DEVICE_OPTIONS[0]?.value ?? null
//   state.bindings.forEach((binding) => {
//     if (!DEVICE_OPTIONS.some((item) => item.value === binding.workerId)) {
//       eegMonitor.stopEeg(binding.id)
//       binding.workerId = fallbackWorkerId
//       binding.activeWorkerId = null
//     }
//   })
// }

function syncBindingsWithDevices() {
  const fallbackWorkerId = DEVICE_OPTIONS[0]?.value ?? null
  state.bindings.forEach((binding) => {
    if (!DEVICE_OPTIONS.some((item) => item.value === binding.workerId)) {
      eegMonitor.stopEeg(binding.id)
      binding.workerId = fallbackWorkerId
      binding.activeWorkerId = null
    }
  })
  persistBindings()
}


// function syncBindingsWithPersonnel() {
//   state.bindings.forEach((binding) => {
//     if (!state.personnelOptions.some((item) => item.id === binding.personId || item.uid === binding.personId)) {
//       binding.personId = ''
//       binding.personName = ''
//       binding.personType = ''
//       return
//     }
//     updateBindingPerson(binding)
//   })
// }

function syncBindingsWithPersonnel() {
  state.bindings.forEach((binding) => {
    if (!state.personnelOptions.some((item) => item.id === binding.personId || item.uid === binding.personId)) {
      binding.personId = ''
      binding.personName = ''
      binding.personType = ''
      return
    }
    updateBindingPerson(binding)
  })
  persistBindings()
}



// async function initMonitorCenter() {
//   if (state.initialized) return
//   loadPersonnel()
//   loadDevices()
//   state.bindings = []
//   faceMonitor.ensureFaceConnection()
//   state.initialized = true
// }

async function initMonitorCenter() {
  if (state.initialized) return
  await Promise.all([loadPersonnel(), loadDevices(), loadCameras()])
  loadBindings()

  faceMonitor.ensureFaceConnection()

  state.bindings.forEach((binding) => {
    faceMonitor.subscribeFace(binding)
  })

  state.initialized = true
}

// function addBinding() {
//   if (state.bindings.length >= 4) {
//     ElMessage.warning('最多支持 4 个设备卡片')
//     return
//   }
//   const binding = createBinding(state.bindings.length + 1)
//   state.bindings.push(binding)
//   faceMonitor.subscribeFace(binding)
// }

function addBinding() {
  if (state.bindings.length >= 4) {
    ElMessage.warning('最多支持 4 个设备卡片')
    return
  }
  const binding = createBinding(state.bindings.length + 1)
  state.bindings.push(binding)
  persistBindings()
  faceMonitor.subscribeFace(binding)
}


// function removeBinding(bindingId) {
//   eegMonitor.stopEeg(bindingId)
//   faceMonitor.unsubscribeFace(bindingId)
//   eegMonitor.disposeChart(bindingId)
//   const index = state.bindings.findIndex((item) => item.id === bindingId)
//   if (index === -1) return
//   const binding = state.bindings[index]
//   if (binding.localVideoUrl) {
//     URL.revokeObjectURL(binding.localVideoUrl)
//   }
//   state.bindings.splice(index, 1)
// }

function removeBinding(bindingId) {
  eegMonitor.stopEeg(bindingId)
  faceMonitor.unsubscribeFace(bindingId)
  eegMonitor.disposeChart(bindingId)

  const index = state.bindings.findIndex((item) => item.id === bindingId)
  if (index === -1) return

  const binding = state.bindings[index]
  if (binding.localVideoUrl) {
    URL.revokeObjectURL(binding.localVideoUrl)
  }

  state.bindings.splice(index, 1)
  persistBindings()
}



async function addPersonnel(record) {
  const normalized = normalizePersonnel({
    id: `person-${Date.now()}`,
    uid: record.uid,
    name: record.name,
    type: record.type
  }, state.personnelOptions.length)
  await syncRemotePersonnel(normalized)
  state.personnelOptions.push(normalized)
  persistPersonnel()
}

async function updatePersonnel(record) {
  const index = state.personnelOptions.findIndex((item) => item.id === record.id)
  if (index === -1) return
  const normalized = normalizePersonnel(record, index)
  await syncRemotePersonnel(normalized)
  state.personnelOptions[index] = normalized
  persistPersonnel()
  syncBindingsWithPersonnel()
}

async function removePersonnel(personId) {
  const index = state.personnelOptions.findIndex((item) => item.id === personId)
  if (index === -1) return
  await removeRemotePersonnel(personId)
  state.personnelOptions.splice(index, 1)
  persistPersonnel()
  syncBindingsWithPersonnel()
}

async function syncRemotePersonnel(personnel) {
  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/personnel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: personnel.id,
        uid: personnel.uid,
        name: personnel.name,
        type: personnel.type
      })
    })
    if (!response.ok) {
      throw new Error(`personnel save failed: ${response.status}`)
    }
  } catch (error) {
    console.warn('Failed to sync remote personnel config', error)
    throw error
  }
}

async function removeRemotePersonnel(personId) {
  try {
    await fetch(`${FACE_SERVICE_BASE}/personnel/${encodeURIComponent(personId)}`, { method: 'DELETE' })
  } catch (error) {
    console.warn('Failed to remove remote personnel config', error)
    throw error
  }
}

function getNextDeviceValue() {
  return DEVICE_OPTIONS.reduce((max, item) => Math.max(max, Number(item.value || 0)), 0) + 1
}

async function addDevice(record) {
  const normalized = normalizeDevice({
    value: getNextDeviceValue(),
    name: record.name,
    port: record.port
  }, DEVICE_OPTIONS.length)
  await syncRemoteDevice(normalized)
  DEVICE_OPTIONS.push(normalized)
  persistDevices()
  state.bindings.forEach((binding) => {
    if (binding.workerId == null) {
      binding.workerId = normalized.value
    }
  })
}

async function updateDevice(record) {
  const index = DEVICE_OPTIONS.findIndex((item) => item.value === Number(record.value))
  if (index === -1) return
  const normalized = normalizeDevice(record, index)
  await syncRemoteDevice(normalized)
  DEVICE_OPTIONS[index] = normalized
  persistDevices()
  persistBindings()
}

function syncBindingsWithCameras() {
  const fallbackCameraId = getDefaultCameraId()
  state.bindings.forEach((binding) => {
    if (!CAMERA_OPTIONS.some((item) => item.id === binding.faceChannelId)) {
      faceMonitor.unsubscribeFace(binding.id)
      binding.faceChannelId = fallbackCameraId
      faceMonitor.subscribeFace(binding)
    }
  })
  persistBindings()
}

async function removeDevice(deviceValue) {
  const index = DEVICE_OPTIONS.findIndex((item) => item.value === Number(deviceValue))
  if (index === -1) return
  await removeRemoteDevice(deviceValue)
  DEVICE_OPTIONS.splice(index, 1)
  persistDevices()
  syncBindingsWithDevices()
}

async function syncRemoteDevice(device) {
  try {
    if (!device.port) return
    const response = await fetch('/eeg/devices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workerId: device.value,
        value: device.value,
        name: device.name,
        port: device.port
      })
    })
    if (!response.ok) {
      throw new Error(`eeg device save failed: ${response.status}`)
    }
  } catch (error) {
    console.warn('Failed to sync remote eeg device config', error)
    throw error
  }
}

async function removeRemoteDevice(deviceValue) {
  try {
    const response = await fetch(`/eeg/devices/${encodeURIComponent(deviceValue)}`, { method: 'DELETE' })
    if (!response.ok && response.status !== 404) {
      throw new Error(`eeg device delete failed: ${response.status}`)
    }
  } catch (error) {
    console.warn('Failed to remove remote eeg device config', error)
    throw error
  }
}

async function addCamera(record) {
  const normalized = normalizeCamera({
    id: record.id || `camera_${Date.now()}`,
    name: record.name,
    rtspUrl: record.rtspUrl
  }, CAMERA_OPTIONS.length)
  await syncRemoteCamera(normalized)
  CAMERA_OPTIONS.push(normalized)
  persistCameras()
  state.bindings.forEach((binding) => {
    if (!binding.faceChannelId) {
      binding.faceChannelId = normalized.id
      faceMonitor.subscribeFace(binding)
    }
  })
}

async function updateCamera(record) {
  const index = CAMERA_OPTIONS.findIndex((item) => item.id === record.id)
  if (index === -1) return
  const normalized = normalizeCamera(record, index)
  await syncRemoteCamera(normalized)
  CAMERA_OPTIONS[index] = normalized
  persistCameras()
  state.bindings.forEach((binding) => {
    if (binding.faceChannelId === record.id) {
      faceMonitor.refreshFaceSubscription(binding.id)
    }
  })
  persistBindings()
}

async function removeCamera(cameraId) {
  const index = CAMERA_OPTIONS.findIndex((item) => item.id === cameraId)
  if (index === -1) return
  await removeRemoteCamera(cameraId)
  CAMERA_OPTIONS.splice(index, 1)
  persistCameras()
  syncBindingsWithCameras()
}

async function syncRemoteCamera(camera) {
  try {
    if (!camera.rtspUrl) return
    const response = await fetch(`${FACE_SERVICE_BASE}/cameras`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: camera.id,
        name: camera.name,
        rtspUrl: camera.rtspUrl
      })
    })
    if (!response.ok) {
      throw new Error(`camera save failed: ${response.status}`)
    }
  } catch (error) {
    console.warn('Failed to sync remote camera config', error)
    throw error
  }
}

async function removeRemoteCamera(cameraId) {
  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/cameras/${encodeURIComponent(cameraId)}`, { method: 'DELETE' })
    if (!response.ok && response.status !== 404) {
      throw new Error(`camera delete failed: ${response.status}`)
    }
  } catch (error) {
    console.warn('Failed to remove remote camera config', error)
    throw error
  }
}

function formatShortTime(value) {
  const date = value ? new Date(value) : new Date()
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function getAlertType(binding) {
  if (binding.emotion === 'normal') return 'success'
  if (binding.emotion === 'fatigue' || binding.emotion === 'weakness') return 'error'
  return 'warning'
}

function formatIndex(value) {
  return Number(value || 0).toFixed(1)
}

function refreshFaceSubscription(bindingId) {
  faceMonitor.refreshFaceSubscription(bindingId)
}

function updateBindingDevice(binding) {
  if (!binding) return
  const shouldRestart = binding.eegRunning
  if (shouldRestart) {
    eegMonitor.stopEeg(binding.id)
    eegMonitor.startEeg(binding)
  }
  persistBindings()
}

function updateBindingCamera(binding) {
  if (!binding) return
  faceMonitor.refreshFaceSubscription(binding.id)
  persistBindings()
}

function useMonitorCenterPage() {
  onMounted(async () => {
    await initMonitorCenter()
    await nextTick()
    eegMonitor.ensureCharts(state.bindings)
    window.addEventListener('resize', eegMonitor.resizeCharts)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', eegMonitor.resizeCharts)
  })
}

const overview = computed(() => ({
  total: state.bindings.length,
  onlineCount: state.bindings.filter((item) => item.eegRunning || item.faceConnected).length,
  warningCount: state.bindings.filter((item) => getWarningLevel(item) === 'warning').length,
  dangerCount: state.bindings.filter((item) => item.emotion !== 'normal').length
}))

export function useMonitorCenter() {
  return {
    state,
    DEVICE_OPTIONS,
    CAMERA_OPTIONS,
    overview,
    initMonitorCenter,
    useMonitorCenterPage,
    addBinding,
    removeBinding,
    addPersonnel,
    updatePersonnel,
    removePersonnel,
    addDevice,
    updateDevice,
    removeDevice,
    addCamera,
    updateCamera,
    removeCamera,
    updateBindingPerson,
    updateBindingDevice,
    updateBindingCamera,
    persistBindings,
    getBindingById,
    getDeviceLabel,
    getCameraLabel,
    formatShortTime,
    setChartRef: eegMonitor.setChartRef,
    setBandChartRef: eegMonitor.setBandChartRef,
    startEeg: eegMonitor.startEeg,
    stopEeg: eegMonitor.stopEeg,
    refreshFaceSubscription,
    getWarningLevel,
    getWarningText,
    getAlertType,
    formatIndex
  }
}
