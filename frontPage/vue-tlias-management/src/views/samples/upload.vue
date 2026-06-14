<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'

const FACE_SERVICE_BASE = '/face-api/faceDetectService'
const REQUIRED_FILES = [
  'manifest.json',
  'video/face.mp4',
  'eeg/raw_wave.json',
  'eeg/raw_tgam.json',
  'eeg/predictions.jsonl',
  'face/predictions.jsonl'
]
const DISPLAY_SECONDS = 4
const DEFAULT_RAW_FS = 512
const RENDER_INTERVAL_MS = 50
const BAND_NAMES = ['delta', 'theta', 'alpha', 'beta', 'gamma']
const BAND_LABELS = { delta: 'Delta', theta: 'Theta', alpha: 'Alpha', beta: 'Beta', gamma: 'Gamma' }
const BAND_COLORS = { delta: '#2563eb', theta: '#0891b2', alpha: '#0f766e', beta: '#ea580c', gamma: '#7c3aed' }
const FEATURE_NAMES = ['theta_alpha', 'theta_beta', 'theta_alpha_beta', 'engagement', 'alpha_beta', 'slow_ratio', 'beta_ratio', 'gamma_ratio']
const FEATURE_LABELS = {
  theta_alpha: 'θ/α',
  theta_beta: 'θ/β',
  theta_alpha_beta: '(θ+α)/β',
  engagement: '参与度',
  alpha_beta: 'α/β',
  slow_ratio: '慢波占比',
  beta_ratio: 'β占比',
  gamma_ratio: 'γ占比'
}
const FEATURE_COLORS = ['#22d3ee', '#14b8a6', '#38bdf8', '#f59e0b', '#a78bfa', '#fb7185', '#f97316', '#8b5cf6']
const STATE_KEYS = ['fatigue', 'stress', 'anxiety', 'weakness']
const STATE_COLORS = { fatigue: '#ef4444', stress: '#f97316', anxiety: '#a855f7', weakness: '#3b82f6' }
const STATE_FEATURES = {
  fatigue: ['theta_beta', 'theta_alpha_beta', 'slow_ratio', 'engagement'],
  stress: ['beta_ratio', 'engagement', 'gamma_ratio'],
  anxiety: ['gamma_ratio', 'beta_ratio', 'engagement'],
  weakness: ['slow_ratio', 'theta_alpha_beta', 'alpha_beta', 'engagement'],
  normal: ['theta_beta', 'engagement', 'slow_ratio', 'beta_ratio']
}
const EMOTION_TEXT = { normal: '正常', anxiety: '焦虑', stress: '紧张', fatigue: '疲劳', weakness: '虚弱' }
const WARNING_TEXT = {
  normal: '预警：当前状态正常',
  anxiety: '预警：检测到焦虑倾向',
  stress: '预警：检测到紧张倾向',
  fatigue: '预警：检测到疲劳倾向',
  weakness: '预警：检测到虚弱倾向'
}

const route = useRoute()
const router = useRouter()
const fileInputRef = ref(null)
const videoRef = ref(null)
const bandChartRef = ref(null)
const gaugeChartRef = ref(null)
const featureChartRef = ref(null)
const heatmapChartRef = ref(null)
const radarChartRef = ref(null)
const uploading = ref(false)
const uploadPercent = ref(0)
const sample = ref(null)
const playbackState = ref('idle')
const rawWaveBuffer = ref([])
const visibleBands = ref([...BAND_NAMES])
const featureMode = ref('z')
let bandChartInstance = null
let gaugeChartInstance = null
let featureChartInstance = null
let heatmapChartInstance = null
let radarChartInstance = null
const failedCharts = new Set()
let playbackTimer = null
let playbackStartedAt = 0
let displayAmplitude = 100
let lastWaveRenderAt = 0
let playedSampleCount = 0
let playedTimelineCount = 0

const manifest = computed(() => sample.value?.manifest || {})
const latestEeg = computed(() => sample.value?.latestEeg || {})
const latestFace = computed(() => sample.value?.latestFace || {})
const rawWave = computed(() => sample.value?.rawWave || {})
const rawTgam = computed(() => sample.value?.rawTgam || {})
const rawSamples = computed(() => {
  const original = Array.isArray(rawTgam.value.samples) ? rawTgam.value.samples : []
  return original.length ? original : (Array.isArray(rawWave.value.samples) ? rawWave.value.samples : [])
})
const rawSampleRate = computed(() => {
  const originalFs = Number(rawTgam.value.rawTgamFs || 0)
  return originalFs > 0 && Array.isArray(rawTgam.value.samples) && rawTgam.value.samples.length
    ? originalFs
    : Number(rawWave.value.waveFs || DEFAULT_RAW_FS)
})
const eegTimeline = computed(() => Array.isArray(sample.value?.eegTimeline) ? sample.value.eegTimeline : [])
const currentBandSnapshot = computed(() => {
  const visible = getVisibleTimeline()
  const latestVisible = visible.length ? visible[visible.length - 1] : latestEeg.value
  return getBandSnapshot(latestVisible?.raw_powers)
})
const currentEeg = computed(() => {
  const visible = getVisibleTimeline()
  return visible.length ? visible[visible.length - 1] : latestEeg.value
})
const currentIndices = computed(() => {
  const source = currentEeg.value?.indices || {}
  return {
    fatigue: Number(source.fatigue_idx || 0),
    stress: Number(source.stress_idx || 0),
    anxiety: Number(source.anxiety_idx || 0),
    weakness: Number(source.weakness_idx || 0)
  }
})
const thresholdCounts = computed(() => getWindowSummary('thresholdCounts'))
const dominantVotes = computed(() => getWindowSummary('dominantVotes'))
const validPredictionCount = computed(() => {
  const serverValue = Number(sample.value?.validPredictionCount)
  if (Number.isFinite(serverValue)) return serverValue
  return eegTimeline.value.filter((item) => item?.valid_current === true).length
})
const selectedFeatureNames = computed(() => STATE_FEATURES[emotionKey.value] || STATE_FEATURES.normal)
const hasFeatureData = computed(() => eegTimeline.value.some((item) => Object.keys(item?.features || {}).length > 0))
const featureExplanations = computed(() => [
  { state: '疲劳', color: STATE_COLORS.fatigue, text: 'θ/β、(θ+α)/β、慢波占比升高，参与度和 β 占比下降时，疲劳倾向增强。' },
  { state: '紧张', color: STATE_COLORS.stress, text: 'β 占比、参与度和 γ 占比同步升高时，紧张倾向增强。' },
  { state: '焦虑', color: STATE_COLORS.anxiety, text: 'γ 占比、β 占比和参与度升高时，焦虑倾向增强。' },
  { state: '虚弱', color: STATE_COLORS.weakness, text: '慢波占比、(θ+α)/β、α/β 升高且活跃度下降时，虚弱倾向增强。' }
])
const emotionKey = computed(() => normalizeEmotion(manifest.value.emotion || 'normal'))
const emotionText = computed(() => EMOTION_TEXT[emotionKey.value] || '正常')
const warningText = computed(() => WARNING_TEXT[emotionKey.value] || WARNING_TEXT.normal)
const alertType = computed(() => emotionKey.value === 'normal' ? 'success' : (emotionKey.value === 'fatigue' || emotionKey.value === 'weakness' ? 'error' : 'warning'))
const sampleTitle = computed(() => `${manifest.value.personName || '未绑定人员'} / 脑电设备${manifest.value.workerId || '--'} / ${manifest.value.cameraId || '未配置摄像头'}`)
const sampleTime = computed(() => formatShortTime(manifest.value.timestamp || manifest.value.windowEnd))
const faceStatusText = computed(() => playbackState.value === 'playing' ? '播放中' : (sample.value ? '已加载' : '待加载'))
const eegStatusText = computed(() => playbackState.value === 'playing' ? '播放中' : (sample.value ? '已加载' : '待加载'))

function chooseFolder() {
  fileInputRef.value?.click()
}

async function handleFolderChange(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length) return
  const validation = validateFiles(files)
  if (!validation.ok) {
    await ElMessageBox.alert(validation.message, '样本目录校验失败', { type: 'warning', confirmButtonText: '重新选择' })
    return
  }
  await uploadFiles(files)
}

function validateFiles(files) {
  const names = files.map((file) => normalizePath(file.webkitRelativePath || file.name))
  const root = findRootPrefix(names)
  if (root.includes('/')) return { ok: false, message: '请选择单个系统样本目录，不要选择样本的上层目录。' }
  const relativeNames = names.map((name) => stripRoot(name, root))
  const fileSet = new Set(relativeNames)
  const missing = REQUIRED_FILES.filter((required) => !fileSet.has(required))
  if (missing.length) return { ok: false, message: `当前样本目录缺少以下文件：\n${missing.join('\n')}\n\n请重新选择系统保存出的完整样本目录。` }
  const requiredFiles = files.filter((file) => REQUIRED_FILES.includes(stripRoot(normalizePath(file.webkitRelativePath || file.name), root)))
  const emptyFile = requiredFiles.find((file) => file.size <= 0)
  if (emptyFile) return { ok: false, message: `样本文件不能为空：${stripRoot(normalizePath(emptyFile.webkitRelativePath || emptyFile.name), root)}` }
  return { ok: true }
}

function findRootPrefix(names) {
  if (names.includes('manifest.json')) return ''
  const manifestPath = names.find((name) => name.endsWith('/manifest.json'))
  return manifestPath ? manifestPath.slice(0, -'/manifest.json'.length) : ''
}

function stripRoot(name, root) {
  if (!root) return name
  return name.startsWith(`${root}/`) ? name.slice(root.length + 1) : name
}

function normalizePath(value) {
  return String(value || '').replace(/\\/g, '/').replace(/^\/+/, '')
}

async function uploadFiles(files) {
  const formData = new FormData()
  const root = findRootPrefix(files.map((file) => normalizePath(file.webkitRelativePath || file.name)))
  files.forEach((file) => {
    const normalized = normalizePath(file.webkitRelativePath || file.name)
    const relative = stripRoot(normalized, root)
    if (REQUIRED_FILES.includes(relative)) formData.append('files', file, file.webkitRelativePath || file.name)
  })
  stopPlayback()
  uploading.value = true
  uploadPercent.value = 0
  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/demo-samples/upload`, { method: 'POST', body: formData })
    const payload = await response.json()
    if (!response.ok || payload.code !== 0) {
      const details = Array.isArray(payload.missing) && payload.missing.length ? `\n${payload.missing.join('\n')}` : ''
      throw new Error(`${payload.msg || '样本上传失败'}${details}`)
    }
    sample.value = payload.data?.sample || null
    uploadPercent.value = 100
    ElMessage.success('样本上传成功')
  } catch (error) {
    sample.value = null
    await ElMessageBox.alert(`${error.message || '样本上传失败'}\n\n请重新选择系统保存出的完整样本目录。`, '上传失败', { type: 'error', confirmButtonText: '重新上传' })
    return
  } finally {
    uploading.value = false
  }
  if (sample.value?.sampleId) {
    try {
      await router.replace({ path: '/samples/upload', query: { sampleId: sample.value.sampleId } })
    } catch (error) {
      ElMessage.warning(`样本已上传，但页面地址更新失败：${error.message || '未知错误'}`)
    }
  }
  await preparePlayback()
}

async function loadSample(sampleId) {
  if (!sampleId) return
  stopPlayback()
  uploading.value = true
  try {
    const response = await fetch(`${FACE_SERVICE_BASE}/demo-samples/${encodeURIComponent(sampleId)}`)
    const payload = await response.json()
    if (!response.ok || payload.code !== 0) throw new Error(payload.msg || '样本加载失败')
    sample.value = payload.data || null
  } catch (error) {
    sample.value = null
    await ElMessageBox.alert(`${error.message || '样本加载失败'}\n\n请重新上传样本目录。`, '加载失败', { type: 'error', confirmButtonText: '重新上传' })
    return
  } finally {
    uploading.value = false
  }
  await preparePlayback()
}

async function preparePlayback() {
  resetPlaybackState()
  await nextTick()
  resetCharts()
  const failures = ensureCharts()
  if (failures.length) {
    ElMessage.warning(`样本已加载，部分可视化初始化失败：${failures.join('、')}`)
  }
  startPlayback()
}

function resetPlaybackState() {
  stopPlayback()
  rawWaveBuffer.value = []
  visibleBands.value = [...BAND_NAMES]
  displayAmplitude = 100
  lastWaveRenderAt = 0
  playedSampleCount = 0
  playedTimelineCount = 0
  playbackState.value = sample.value ? 'loaded' : 'idle'
}

function resetCharts() {
  bandChartInstance?.dispose()
  bandChartInstance = null
  gaugeChartInstance?.dispose()
  featureChartInstance?.dispose()
  heatmapChartInstance?.dispose()
  radarChartInstance?.dispose()
  gaugeChartInstance = null
  featureChartInstance = null
  heatmapChartInstance = null
  radarChartInstance = null
  failedCharts.clear()
}

function startPlayback() {
  if (!sample.value) return
  if (playbackState.value === 'playing' && playbackTimer) return
  playbackState.value = 'playing'
  playbackStartedAt = Date.now()
  const video = videoRef.value
  if (video) {
    video.currentTime = 0
    video.muted = true
    const playPromise = video.play()
    if (playPromise?.catch) playPromise.catch(() => {})
  }
  ensurePlaybackTimer()
  tickPlayback()
}

function ensurePlaybackTimer() {
  if (!playbackTimer) playbackTimer = window.setInterval(tickPlayback, 80)
}

function stopPlayback() {
  if (playbackTimer) {
    window.clearInterval(playbackTimer)
    playbackTimer = null
  }
}

function getPlaybackElapsedMs() {
  const video = videoRef.value
  if (video && video.readyState >= 1 && Number.isFinite(video.currentTime)) {
    return Math.max(0, video.currentTime * 1000)
  }
  return Math.max(0, Date.now() - playbackStartedAt)
}

function handleVideoPlay() {
  if (!sample.value) return
  playbackState.value = 'playing'
  playbackStartedAt = Date.now() - getPlaybackElapsedMs()
  ensurePlaybackTimer()
  tickPlayback()
}

function handleVideoPause() {
  if (playbackState.value !== 'ended') playbackState.value = 'paused'
  tickPlayback()
}

function syncPlaybackToVideo() {
  const total = rawSamples.value.length
  const timelineTotal = eegTimeline.value.length
  const durationMs = getPlaybackDurationMs()
  const elapsedMs = Math.min(getPlaybackElapsedMs(), durationMs)
  const targetCount = getTargetRawSampleCount(elapsedMs, durationMs, total)
  const waveLimit = Math.max(1, Math.round(rawSampleRate.value * DISPLAY_SECONDS))
  rawWaveBuffer.value = rawSamples.value
    .slice(Math.max(0, targetCount - waveLimit), targetCount)
    .map(Number)
    .filter(Number.isFinite)
  playedSampleCount = targetCount
  playedTimelineCount = Math.min(timelineTotal, Math.floor((elapsedMs / Math.max(durationMs, 1)) * timelineTotal))
  lastWaveRenderAt = 0
  refreshPlaybackCharts()
}

function tickPlayback() {
  const total = rawSamples.value.length
  const timelineTotal = eegTimeline.value.length
  if (!total && !timelineTotal) return
  const durationMs = getPlaybackDurationMs()
  const elapsedMs = Math.min(getPlaybackElapsedMs(), durationMs)
  const targetCount = getTargetRawSampleCount(elapsedMs, durationMs, total)
  if (targetCount < playedSampleCount) {
    syncPlaybackToVideo()
    return
  }
  if (targetCount > playedSampleCount) {
    appendRawWave(rawSamples.value.slice(playedSampleCount, targetCount))
    playedSampleCount = targetCount
  }
  playedTimelineCount = Math.min(timelineTotal, Math.floor((elapsedMs / Math.max(durationMs, 1)) * timelineTotal))
  refreshPlaybackCharts()
  if (elapsedMs >= durationMs || (total ? playedSampleCount >= total : playedTimelineCount >= timelineTotal)) {
    playedTimelineCount = timelineTotal
    refreshPlaybackCharts()
    stopPlayback()
    playbackState.value = 'ended'
  }
}

function getTargetRawSampleCount(elapsedMs, durationMs, total) {
  if (!total) return 0
  const videoDuration = Number(videoRef.value?.duration || 0)
  if (Number.isFinite(videoDuration) && videoDuration > 0) {
    return Math.min(total, Math.floor((elapsedMs / Math.max(durationMs, 1)) * total))
  }
  const waveFs = rawSampleRate.value
  if (Number.isFinite(waveFs) && waveFs > 0) {
    return Math.min(total, Math.floor((elapsedMs / 1000) * waveFs))
  }
  return Math.min(total, Math.floor((elapsedMs / Math.max(durationMs, 1)) * total))
}

function getPlaybackDurationMs() {
  const videoDuration = Number(videoRef.value?.duration || 0)
  if (Number.isFinite(videoDuration) && videoDuration > 0) return videoDuration * 1000
  const windowMs = Number(manifest.value.windowMs || 0)
  if (windowMs > 0) return windowMs
  const source = Array.isArray(rawTgam.value.samples) && rawTgam.value.samples.length ? rawTgam.value : rawWave.value
  const rawDuration = Number(source.windowEnd || 0) - Number(source.windowStart || 0)
  return rawDuration > 0 ? rawDuration : 10000
}

function appendRawWave(chunk = []) {
  const samples = chunk.map(Number).filter(Number.isFinite)
  if (!samples.length) return
  rawWaveBuffer.value.push(...samples)
  const limit = Math.max(1, Math.round(rawSampleRate.value * DISPLAY_SECONDS))
  if (rawWaveBuffer.value.length > limit) rawWaveBuffer.value.splice(0, rawWaveBuffer.value.length - limit)
}

function getWaveXAxisData() {
  const fs = Math.max(1, rawSampleRate.value)
  const count = rawWaveBuffer.value.length
  return rawWaveBuffer.value.map((_, index) => ((index - count + 1) / fs).toFixed(1))
}

function updateDisplayAmplitude() {
  const peak = rawWaveBuffer.value.reduce((max, value) => Math.max(max, Math.abs(value)), 0)
  const targetAmplitude = Math.max(100, peak * 1.15)
  displayAmplitude = targetAmplitude > displayAmplitude
    ? targetAmplitude
    : Math.max(targetAmplitude, displayAmplitude * 0.985)
}

function getWaveChartOption() {
  return {
    color: ['#0f766e'],
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 24, bottom: 28 },
    xAxis: { type: 'category', boundaryGap: false, name: '时间（秒）', axisLine: { lineStyle: { color: '#9db4c0' } }, data: getWaveXAxisData() },
    yAxis: { type: 'value', min: -displayAmplitude, max: displayAmplitude, name: 'TGAM 原始值', axisLine: { show: false }, splitLine: { lineStyle: { color: '#e6eef2' } } },
    series: [{
      name: `原始脑电波形（${rawSampleRate.value}Hz）`,
      type: 'line',
      showSymbol: false,
      smooth: false,
      sampling: 'lttb',
      animation: false,
      lineStyle: { width: 1 },
      data: [...rawWaveBuffer.value]
    }]
  }
}

function getBandTrendChartOption() {
  return {
    color: BAND_NAMES.map((name) => BAND_COLORS[name]),
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${Number(value || 0).toFixed(1)}%` },
    legend: { show: false },
    grid: { left: 42, right: 20, top: 24, bottom: 28 },
    xAxis: { type: 'category', boundaryGap: false, name: '10 秒窗口', axisLine: { lineStyle: { color: '#9db4c0' } }, data: getTimelineXAxisData() },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' }, axisLine: { show: false }, splitLine: { lineStyle: { color: '#e6eef2' } } },
    series: getVisibleBandNames().map((name) => ({
      name: BAND_LABELS[name],
      type: 'line',
      showSymbol: false,
      smooth: true,
      animation: false,
      lineStyle: { width: 2, color: BAND_COLORS[name] },
      itemStyle: { color: BAND_COLORS[name] },
      markLine: getPlaybackMarkLine(),
      data: getBandTrendData(name)
    }))
  }
}

function getGaugeChartOption() {
  const timeline = eegTimeline.value
  return {
    color: STATE_KEYS.map((key) => STATE_COLORS[key]),
    tooltip: { trigger: 'axis' },
    legend: { top: 4 },
    grid: { left: 48, right: 24, top: 48, bottom: 34 },
    xAxis: { type: 'category', boundaryGap: false, data: getTimelineXAxisData(), name: '秒' },
    yAxis: { type: 'value', min: 0, max: 100, name: '状态指数', splitLine: { lineStyle: { color: '#e8f0f4' } } },
    series: STATE_KEYS.map((key) => ({
      name: EMOTION_TEXT[key],
      type: 'line',
      smooth: true,
      showSymbol: true,
      symbolSize: 6,
      lineStyle: { width: 2.5 },
      markLine: key === 'fatigue' ? {
        silent: true,
        symbol: 'none',
        data: [
          { yAxis: 59, name: '阈值 59', lineStyle: { color: '#dc2626', type: 'dashed' }, label: { formatter: '阈值 59' } },
          ...getPlaybackMarkLineData()
        ]
      } : undefined,
      data: timeline.map((item) => Number(item?.indices?.[`${key}_idx`] || 0).toFixed(2)).map(Number)
    }))
  }
}

function getFeatureValue(item, name) {
  const features = item?.features || {}
  const source = featureMode.value === 'z' ? features.z || {} : features
  return Number(source[name] || 0)
}

function getFeatureTrendOption() {
  return {
    backgroundColor: 'transparent',
    color: FEATURE_COLORS,
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 4 },
    grid: { left: 48, right: 22, top: 54, bottom: 34 },
    xAxis: { type: 'category', boundaryGap: false, data: getTimelineXAxisData(), axisLine: { lineStyle: { color: '#9db4c0' } } },
    yAxis: {
      type: 'value',
      name: featureMode.value === 'z' ? '相对基线 Z-score' : '原始特征比值',
      splitLine: { lineStyle: { color: '#e8f0f4' } }
    },
    series: selectedFeatureNames.value.map((name) => ({
      name: FEATURE_LABELS[name],
      type: 'line',
      smooth: true,
      showSymbol: false,
      animation: false,
      lineStyle: { width: 2 },
      areaStyle: { opacity: 0.04 },
      markLine: name === selectedFeatureNames.value[0] ? {
        silent: true,
        symbol: 'none',
        data: [
          ...(featureMode.value === 'z' ? [{ yAxis: 1, lineStyle: { type: 'dashed', color: '#f59e0b' } }] : []),
          ...getPlaybackMarkLineData()
        ]
      } : undefined,
      data: eegTimeline.value.map((item) => Number(getFeatureValue(item, name).toFixed(3)))
    }))
  }
}

function getHeatmapOption() {
  const data = []
  eegTimeline.value.forEach((item, x) => STATE_KEYS.forEach((key, y) => {
    const value = Number(item?.indices?.[`${key}_idx`] || 0)
    data.push({ value: [x, y, value], itemStyle: { color: value >= 59 ? STATE_COLORS[key] : '#edf3f6' } })
  }))
  return {
    tooltip: { formatter: ({ value }) => `${EMOTION_TEXT[STATE_KEYS[value[1]]]}<br/>第 ${value[0] + 1} 秒：${Number(value[2]).toFixed(1)}${value[2] >= 59 ? '（过阈值）' : ''}` },
    grid: { left: 62, right: 24, top: 18, bottom: 42 },
    xAxis: { type: 'category', data: getTimelineXAxisData(), name: '秒', splitArea: { show: true } },
    yAxis: { type: 'category', data: STATE_KEYS.map((key) => EMOTION_TEXT[key]), splitArea: { show: true } },
    visualMap: {
      show: false,
      min: 0,
      max: 100,
      dimension: 2,
      inRange: { opacity: 1 },
      outOfRange: { opacity: 1 }
    },
    series: [{
      type: 'heatmap',
      data,
      label: { show: true, formatter: ({ value }) => Number(value[2]).toFixed(0), color: '#334155' },
      emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(15,118,110,.35)' } }
    }]
  }
}

function getRadarOption() {
  const values = selectedFeatureNames.value.map((name) => {
    const available = eegTimeline.value.map((item) => getFeatureValue(item, name)).filter(Number.isFinite)
    const raw = available.length ? available.reduce((sum, value) => sum + value, 0) / available.length : 0
    return featureMode.value === 'z' ? Math.max(0, Math.min(100, 50 + raw * 14)) : Math.max(0, Math.min(100, raw * 20))
  })
  const abnormalReferences = {
    fatigue: [82, 86, 80, 32],
    stress: [82, 78, 72],
    anxiety: [85, 80, 76],
    weakness: [82, 78, 75, 30],
    normal: Array(selectedFeatureNames.value.length).fill(50)
  }
  return {
    backgroundColor: 'transparent',
    tooltip: {},
    radar: {
      radius: '64%',
      indicator: selectedFeatureNames.value.map((name) => ({ name: FEATURE_LABELS[name], max: 100 })),
      axisName: { color: '#475569' },
      splitLine: { lineStyle: { color: '#dbe7ec' } },
      splitArea: { areaStyle: { color: ['#fbfdfe', '#f1f7f8'] } },
      axisLine: { lineStyle: { color: '#c7d9df' } }
    },
    series: [{
      type: 'radar',
      data: [
        { value: Array(selectedFeatureNames.value.length).fill(50), name: '个人基线', symbol: 'none', lineStyle: { color: '#64748b', type: 'dashed', width: 1 }, areaStyle: { color: 'transparent' } },
        { value: abnormalReferences[emotionKey.value] || abnormalReferences.normal, name: `${emotionText.value}参考方向`, symbol: 'none', lineStyle: { color: '#f59e0b', type: 'dashed', width: 2 }, areaStyle: { color: 'rgba(245,158,11,.06)' } },
        { value: values, name: '10 秒窗口平均', lineStyle: { color: '#0f766e', width: 3 }, itemStyle: { color: '#0891b2' }, areaStyle: { color: 'rgba(20,184,166,.22)' } }
      ]
    }]
  }
}

function ensureCharts() {
  const failures = []
  renderChartSafely('五波段趋势', ensureBandTrendChart, failures)
  renderChartSafely('状态指数趋势', ensureGaugeChart, failures)
  renderChartSafely('关键特征趋势', ensureFeatureChart, failures)
  renderChartSafely('阈值矩阵', ensureHeatmapChart, failures)
  renderChartSafely('平均特征雷达', ensureRadarChart, failures)
  return failures
}

function renderChartSafely(name, render, failures = []) {
  if (failedCharts.has(name)) return
  try {
    render()
  } catch (error) {
    console.error(`${name}初始化失败`, error)
    failedCharts.add(name)
    failures.push(name)
  }
}

function ensureGaugeChart() {
  if (gaugeChartRef.value && !gaugeChartInstance) gaugeChartInstance = echarts.init(gaugeChartRef.value)
  gaugeChartInstance?.setOption(getGaugeChartOption(), true)
  gaugeChartInstance?.resize()
}

function ensureFeatureChart() {
  if (featureChartRef.value && !featureChartInstance) featureChartInstance = echarts.init(featureChartRef.value)
  featureChartInstance?.setOption(getFeatureTrendOption(), true)
  featureChartInstance?.resize()
}

function ensureHeatmapChart() {
  if (heatmapChartRef.value && !heatmapChartInstance) heatmapChartInstance = echarts.init(heatmapChartRef.value)
  heatmapChartInstance?.setOption(getHeatmapOption(), true)
  heatmapChartInstance?.resize()
}

function ensureRadarChart() {
  if (radarChartRef.value && !radarChartInstance) radarChartInstance = echarts.init(radarChartRef.value)
  radarChartInstance?.setOption(getRadarOption(), true)
  radarChartInstance?.resize()
}

function ensureBandTrendChart() {
  if (!bandChartRef.value) return
  if (!bandChartInstance) bandChartInstance = echarts.init(bandChartRef.value)
  bandChartInstance.setOption(getBandTrendChartOption())
  bandChartInstance.resize()
}

function refreshPlaybackCharts() {
  renderChartSafely('五波段趋势', refreshBandTrendChart)
  renderChartSafely('状态指数趋势', ensureGaugeChart)
  renderChartSafely('关键特征趋势', ensureFeatureChart)
  renderChartSafely('阈值矩阵', ensureHeatmapChart)
  renderChartSafely('平均特征雷达', ensureRadarChart)
}

function refreshBandTrendChart() {
  ensureBandTrendChart()
  if (!bandChartInstance) return
  bandChartInstance.setOption(getBandTrendChartOption(), true)
  bandChartInstance.resize()
}

function getVisibleBandNames() {
  return BAND_NAMES.filter((name) => visibleBands.value.includes(name))
}

function toggleBand(band) {
  if (visibleBands.value.includes(band)) {
    if (visibleBands.value.length <= 1) return
    visibleBands.value = visibleBands.value.filter((name) => name !== band)
  } else {
    visibleBands.value = BAND_NAMES.filter((name) => name === band || visibleBands.value.includes(name))
  }
  refreshBandTrendChart()
}

function setFeatureMode(mode) {
  featureMode.value = mode
  renderChartSafely('关键特征趋势', ensureFeatureChart)
  renderChartSafely('平均特征雷达', ensureRadarChart)
}

function getTimelineXAxisData() {
  const total = Math.max(eegTimeline.value.length, 1)
  return Array.from({ length: total }, (_, index) => index + 1)
}

function getVisibleTimeline() {
  if (!eegTimeline.value.length) return []
  const count = Math.max(0, Math.min(playedTimelineCount, eegTimeline.value.length))
  return eegTimeline.value.slice(0, count)
}

function getBandTrendData(name) {
  return eegTimeline.value.map((item) => Number(getBandSnapshot(item?.raw_powers)[name] || 0).toFixed(2)).map(Number)
}

function padTimelineData(values) {
  const total = eegTimeline.value.length
  if (!total) return []
  return [...values, ...Array.from({ length: Math.max(total - values.length, 0) }, () => null)]
}

function getBandSnapshot(rawPowers = {}) {
  const delta = Number(rawPowers?.delta || 0)
  const theta = Number(rawPowers?.theta || 0)
  const alpha = Number(rawPowers?.low_alpha || 0) + Number(rawPowers?.high_alpha || 0)
  const beta = Number(rawPowers?.low_beta || 0) + Number(rawPowers?.high_beta || 0)
  const gamma = Number(rawPowers?.low_gamma || 0) + Number(rawPowers?.mid_gamma || 0)
  const total = delta + theta + alpha + beta + gamma
  if (!total) return { delta: 0, theta: 0, alpha: 0, beta: 0, gamma: 0 }
  return { delta: delta / total * 100, theta: theta / total * 100, alpha: alpha / total * 100, beta: beta / total * 100, gamma: gamma / total * 100 }
}

function normalizeEmotion(value) {
  return ['normal', 'anxiety', 'stress', 'fatigue', 'weakness'].includes(value) ? value : 'normal'
}

function getWindowSummary(field) {
  const serverValue = sample.value?.[field]
  if (serverValue && typeof serverValue === 'object') {
    return Object.fromEntries(STATE_KEYS.map((key) => [key, Number(serverValue[key] || 0)]))
  }
  const counts = Object.fromEntries(STATE_KEYS.map((key) => [key, 0]))
  eegTimeline.value.filter((item) => item?.valid_current === true).forEach((item) => {
    if (field === 'thresholdCounts') {
      STATE_KEYS.forEach((key) => {
        if (Number(item?.indices?.[`${key}_idx`] || 0) >= 59) counts[key] += 1
      })
      return
    }
    const dominant = STATE_KEYS.map((key) => [key, Number(item?.indices?.[`${key}_idx`] || 0)])
      .filter(([, value]) => value >= 59)
      .sort((a, b) => b[1] - a[1])[0]
    if (dominant) counts[dominant[0]] += 1
  })
  return counts
}

function getPlaybackCursorIndex() {
  return Math.max(0, Math.min(eegTimeline.value.length - 1, playedTimelineCount - 1))
}

function getPlaybackMarkLineData() {
  if (!eegTimeline.value.length) return []
  return [{ xAxis: getPlaybackCursorIndex(), name: '播放位置', lineStyle: { color: '#0f766e', width: 2 }, label: { formatter: '播放位置' } }]
}

function getPlaybackMarkLine() {
  return { silent: true, symbol: 'none', data: getPlaybackMarkLineData() }
}

function getFaceStatusLabel() { return sample.value ? faceStatusText.value : '待加载' }
function getEegStatusLabel() { return sample.value ? eegStatusText.value : '待加载' }
function getAccessText() { return sample.value ? '已接入' : '自动接入中' }
function getPortText() { return latestEeg.value.baseUrl || '--' }
function getCameraLabel() { return manifest.value.cameraId || '未配置摄像头' }
function formatBand(value) { return `${Number(value || 0).toFixed(1)}%` }
function latestTime() { return sampleTime.value || '--:--:--' }
function adviceText() { return emotionKey.value === 'normal' ? '继续监测' : '建议关注' }
function formatShortTime(value) {
  const date = value ? new Date(Number(value)) : new Date()
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}
function resizeChart() {
  bandChartInstance?.resize()
  gaugeChartInstance?.resize()
  featureChartInstance?.resize()
  heatmapChartInstance?.resize()
  radarChartInstance?.resize()
}

window.addEventListener('resize', resizeChart)
onMounted(() => { if (route.query.sampleId) void loadSample(String(route.query.sampleId)) })
onBeforeUnmount(() => {
  stopPlayback()
  window.removeEventListener('resize', resizeChart)
  bandChartInstance?.dispose()
  gaugeChartInstance?.dispose()
  featureChartInstance?.dispose()
  heatmapChartInstance?.dispose()
  radarChartInstance?.dispose()
  bandChartInstance = null
})
</script>

<template>
  <div class="detail-page">
    <section class="top-bar">
      <div>
        <div class="kicker">样本数据上传</div>
        <h1>{{ sample ? sampleTitle : '上传已保存样本进行演示' }}</h1>
        <p>以完整 10 秒窗口展示脑电阈值票数、关键推理特征和最终演示状态。</p>
      </div>
      <div class="top-actions">
        <input ref="fileInputRef" class="folder-input" type="file" webkitdirectory multiple @change="handleFolderChange" />
        <el-tag v-if="sample" :type="alertType" effect="dark">{{ warningText }}</el-tag>
        <el-button type="primary" :loading="uploading" @click="chooseFolder">选择样本文件夹</el-button>
      </div>
    </section>

    <section v-if="uploading" class="base-panel">
      <el-progress :percentage="uploadPercent" :indeterminate="uploadPercent < 100" />
    </section>

    <section v-if="sample" class="base-panel">
      <div class="config-grid">
        <el-form-item label="人员"><el-input :model-value="manifest.personName || '未绑定人员'" disabled /></el-form-item>
        <el-form-item label="脑电设备"><el-input :model-value="manifest.workerId || '--'" disabled /></el-form-item>
        <el-form-item label="岗位"><el-input model-value="样本回放" disabled /></el-form-item>
        <el-form-item label="摄像头设备"><el-input :model-value="getCameraLabel()" disabled /></el-form-item>
      </div>

      <div class="quick-grid">
        <div class="quick-card"><span>样本窗口</span><strong>10 秒</strong></div>
        <div class="quick-card"><span>有效 EEG 点数</span><strong>{{ validPredictionCount }}</strong></div>
        <div class="quick-card"><span>综合状态</span><strong>{{ emotionText }}</strong></div>
        <div class="quick-card"><span>最近时间</span><strong>{{ latestTime() }}</strong></div>
      </div>
    </section>

    <section v-if="sample" class="top-content-grid">
      <article class="panel video-panel">
        <div class="panel-head">
          <h3>样本视频</h3>
          <el-tag :type="sample ? 'success' : 'info'">{{ getFaceStatusLabel() }}</el-tag>
        </div>
        <div class="video-box">
          <video
            ref="videoRef"
            class="result-video"
            :src="sample.videoUrl"
            autoplay
            muted
            playsinline
            controls
            preload="metadata"
            @loadedmetadata="startPlayback"
            @play="handleVideoPlay"
            @pause="handleVideoPause"
            @seeked="syncPlaybackToVideo"
          ></video>
        </div>
      </article>

      <article class="panel conclusion-panel">
        <div class="panel-head">
          <h3>10 秒判定结论</h3>
          <el-tag :type="alertType" effect="dark">{{ emotionText }}</el-tag>
        </div>
        <div class="final-state">
          <span>完整窗口演示标签</span>
          <strong>{{ emotionText }}</strong>
          <small>有效 EEG 点数：{{ validPredictionCount }}</small>
        </div>
        <div class="vote-table">
          <div v-for="key in STATE_KEYS" :key="key" class="vote-row">
            <span><i :style="{ background: STATE_COLORS[key] }"></i>{{ EMOTION_TEXT[key] }}</span>
            <strong>过阈值 {{ thresholdCounts[key] }}/{{ validPredictionCount }}</strong>
            <em>主导 {{ dominantVotes[key] }} 票</em>
          </div>
        </div>
        <p class="window-note">最终状态由完整 10 秒窗口特征和演示标签共同展示，动态动画仅用于回放数据变化。</p>
      </article>

      <article class="panel warning-panel">
        <div class="panel-head">
          <h3>状态预警与建议</h3>
          <el-tag :type="alertType" effect="dark">{{ warningText }}</el-tag>
        </div>
        <el-alert :type="alertType" :closable="false" show-icon :title="warningText" />
        <div class="warning-grid">
          <div class="metric-box"><span>当前状态</span><strong>{{ emotionText }}</strong></div>
          <div class="metric-box"><span>处理建议</span><strong>{{ adviceText() }}</strong></div>
          <div class="metric-box"><span>视频通道</span><strong>{{ getFaceStatusLabel() }}</strong></div>
          <div class="metric-box"><span>脑电通道</span><strong>{{ getEegStatusLabel() }}</strong></div>
        </div>
        <div class="advice-copy">
          {{ emotionKey === 'normal' ? '当前窗口未显示明显异常，建议继续保持监测。' : '当前窗口存在异常倾向，建议结合视频表现、阈值票数和关键特征趋势进行说明。' }}
        </div>
      </article>
    </section>

    <section v-if="sample" class="visual-section">
      <div class="section-heading">
        <div>
          <h2>10 秒脑电推理证据</h2>
          <p>所有图表展示完整窗口，绿色竖线仅表示当前视频播放位置。</p>
        </div>
        <el-button-group>
          <el-button size="small" :type="featureMode === 'z' ? 'primary' : 'default'" @click="setFeatureMode('z')">基线 Z-score</el-button>
          <el-button size="small" :type="featureMode === 'raw' ? 'primary' : 'default'" @click="setFeatureMode('raw')">原始比值</el-button>
        </el-button-group>
      </div>

      <div class="visual-grid">
        <article class="visual-card matrix-card">
          <div class="visual-title"><span>四状态阈值矩阵</span><small>指数 ≥ 59 的格子按状态色高亮</small></div>
          <div ref="heatmapChartRef" class="heatmap-chart"></div>
        </article>
        <article class="visual-card state-card">
          <div class="visual-title"><span>四状态指数趋势</span><small>红色虚线为阈值 59</small></div>
          <div ref="gaugeChartRef" class="gauge-chart"></div>
        </article>
        <article class="visual-card feature-card">
          <div class="visual-title"><span>{{ emotionText }}关键特征趋势</span><small>仅展示与当前演示标签相关的特征</small></div>
          <div ref="featureChartRef" class="feature-chart"></div>
          <div v-if="!hasFeatureData" class="chart-empty">旧样本未包含推理特征，仍可查看状态指数和五波段</div>
        </article>
        <article class="visual-card radar-card">
          <div class="visual-title"><span>10 秒平均特征雷达</span><small>对比个人基线与异常参考方向</small></div>
          <div ref="radarChartRef" class="radar-chart"></div>
        </article>
      </div>

      <div class="explain-grid">
        <article v-for="item in featureExplanations" :key="item.state" class="explain-card" :style="{ '--state-color': item.color }">
          <strong>{{ item.state }}</strong>
          <p>{{ item.text }}</p>
        </article>
      </div>

      <article class="visual-card band-card">
        <div class="visual-title">
          <span>五波段占比趋势</span>
          <small>可独立选择显示波段</small>
        </div>
        <div class="band-switch">
          <el-button
            v-for="band in BAND_NAMES"
            :key="band"
            size="small"
            :type="visibleBands.includes(band) ? 'primary' : 'default'"
            @click="toggleBand(band)"
          >
            {{ BAND_LABELS[band] }}
          </el-button>
        </div>
        <div class="chart-wrap trend-chart-wrap">
          <div ref="bandChartRef" class="trend-chart"></div>
          <div v-if="!eegTimeline.length" class="chart-empty">等待波段数据</div>
        </div>
        <div class="band-grid">
          <div v-for="band in BAND_NAMES" :key="band" class="metric-box">
            <span>{{ BAND_LABELS[band] }} 占比</span>
            <strong>{{ formatBand(currentBandSnapshot[band]) }}</strong>
          </div>
        </div>
      </article>
    </section>

    <div v-else-if="!uploading" class="empty-wrap">
      <el-empty description="请选择一个系统保存出的样本目录"><el-button type="primary" @click="chooseFolder">选择样本文件夹</el-button></el-empty>
    </div>
  </div>
</template>

<style scoped>
.detail-page { min-height: 100%; padding: 24px; background: linear-gradient(180deg, #f4fbff 0%, #eef5f7 100%); }
.top-bar, .base-panel, .panel, .visual-section { border-radius: 12px; background: rgba(255,255,255,.96); box-shadow: 0 14px 32px rgba(66,101,122,.08); }
.top-bar { display: flex; justify-content: space-between; gap: 20px; padding: 24px 28px; }
.kicker { font-size: 13px; color: #547089; }
.top-bar h1 { margin: 8px 0 12px; }
.top-bar p { margin: 0; color: #64748b; }
.top-actions, .panel-head, .eeg-actions { display: flex; align-items: center; gap: 12px; }
.top-actions, .panel-head { justify-content: space-between; }
.folder-input { display: none; }
.base-panel { margin-top: 20px; padding: 20px 24px; }
.config-grid, .quick-grid, .top-content-grid, .warning-grid, .band-grid, .visual-grid { display: grid; gap: 16px; }
.config-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.config-grid :deep(.el-form-item) { margin-bottom: 0; }
.quick-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 16px; }
.quick-card, .metric-box { padding: 14px 16px; border-radius: 9px; background: #f6fafc; border: 1px solid #e7eff3; }
.quick-card span, .metric-box span { display: block; margin-bottom: 6px; font-size: 12px; color: #64748b; }
.quick-card strong, .metric-box strong { font-size: 18px; color: #203444; }
.top-content-grid { margin-top: 20px; grid-template-columns: 1.05fr 1.15fr .9fr; align-items: stretch; }
.panel { padding: 20px; }
.panel h3 { margin: 0; color: #203444; }
.video-box, .empty-box { margin-top: 16px; height: 300px; border-radius: 9px; overflow: hidden; background: #07121f; }
.result-video {
  width: 100%;
  height: 100%;
  border: 0;
  background: #07121f;
  object-fit: contain;
  filter: none !important;
  mix-blend-mode: normal;
  opacity: 1;
}
.empty-box { display: flex; align-items: center; justify-content: center; color: #dbeafe; }
.warning-grid, .band-grid { margin-top: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.final-state { margin-top: 16px; padding: 16px; border-radius: 10px; color: #fff; background: linear-gradient(135deg, #0f766e, #0891b2); }
.final-state span, .final-state small { display: block; opacity: .84; }
.final-state strong { display: block; margin: 5px 0; font-size: 32px; }
.vote-table { margin-top: 14px; display: grid; gap: 8px; }
.vote-row { display: grid; grid-template-columns: 72px 1fr 74px; gap: 8px; align-items: center; padding: 9px 10px; border-radius: 8px; background: #f6fafc; font-size: 13px; }
.vote-row span { display: flex; align-items: center; gap: 7px; }
.vote-row i { width: 8px; height: 8px; border-radius: 50%; }
.vote-row em { color: #64748b; font-style: normal; text-align: right; }
.window-note, .advice-copy { margin: 14px 0 0; padding: 12px 14px; border-radius: 8px; background: #eef8f8; color: #476275; font-size: 13px; line-height: 1.65; }
.visual-section { margin-top: 20px; padding: 22px; }
.section-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.section-heading h2 { margin: 0; color: #203444; }
.section-heading p { margin: 7px 0 0; color: #64748b; }
.visual-grid { margin-top: 18px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.visual-card { position: relative; border-radius: 12px; border: 1px solid #dce9ee; background: #fff; box-shadow: 0 8px 22px rgba(61,101,120,.07); }
.visual-title { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 16px 18px 0; color: #203444; font-weight: 800; }
.visual-title small { color: #718696; font-weight: 500; }
.gauge-chart, .radar-chart { height: 360px; }
.feature-chart, .heatmap-chart { height: 330px; }
.explain-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.explain-card { position: relative; padding: 16px; border-radius: 10px; border: 1px solid #e1ebef; background: #f9fcfd; }
.explain-card::before { content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px; border-radius: 4px; background: var(--state-color); }
.explain-card strong { color: var(--state-color); font-size: 17px; }
.explain-card p { margin: 8px 0 0; color: #607483; font-size: 13px; line-height: 1.65; }
.band-card { margin-top: 16px; padding-bottom: 18px; }
.band-switch { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 18px 10px; }
.chart-wrap { position: relative; border-radius: 8px; background: #fbfeff; border: 1px solid #e4edf2; }
.band-card .chart-wrap { margin: 0 18px; }
.trend-chart-wrap { min-height: 240px; }
.trend-chart { height: 240px; width: 100%; }
.band-card .band-grid { margin: 16px 18px 0; grid-template-columns: repeat(5, minmax(0, 1fr)); }
.chart-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #7b8a97; pointer-events: none; }
.empty-wrap { min-height: 420px; display: flex; align-items: center; justify-content: center; }
@media (max-width: 1440px) { .top-content-grid { grid-template-columns: 1fr 1fr; } .warning-panel { grid-column: 1 / -1; } .config-grid, .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .explain-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 960px) { .detail-page { padding: 16px; } .top-bar, .top-actions, .panel-head, .visual-title, .section-heading { flex-direction: column; align-items: flex-start; } .config-grid, .quick-grid, .top-content-grid, .warning-grid, .visual-grid, .explain-grid, .band-card .band-grid { grid-template-columns: 1fr; } .warning-panel { grid-column: auto; } }
</style>
