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
const chartRef = ref(null)
const bandChartRef = ref(null)
const uploading = ref(false)
const uploadPercent = ref(0)
const sample = ref(null)
const playbackState = ref('idle')
const rawWaveBuffer = ref([])
const visibleBands = ref([...BAND_NAMES])
let chartInstance = null
let bandChartInstance = null
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
const emotionKey = computed(() => normalizeEmotion(manifest.value.emotion || 'normal'))
const emotionText = computed(() => EMOTION_TEXT[emotionKey.value] || '正常')
const warningText = computed(() => WARNING_TEXT[emotionKey.value] || WARNING_TEXT.normal)
const alertType = computed(() => emotionKey.value === 'normal' ? 'success' : (emotionKey.value === 'fatigue' || emotionKey.value === 'weakness' ? 'error' : 'warning'))
const sampleTitle = computed(() => `${manifest.value.personName || '未绑定人员'} / 脑电设备${manifest.value.workerId || '--'} / ${manifest.value.cameraId || '未配置摄像头'}`)
const sampleTime = computed(() => formatShortTime(manifest.value.timestamp || manifest.value.windowEnd))
const faceStatusText = computed(() => playbackState.value === 'playing' ? '播放中' : (sample.value ? '已加载' : '待加载'))
const eegStatusText = computed(() => playbackState.value === 'playing' ? '播放中' : (sample.value ? '已加载' : '待加载'))
const waveStatusText = computed(() => playbackState.value === 'playing' ? '实时更新' : (rawWaveBuffer.value.length ? '播放结束' : '等待波形'))

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
    if (sample.value?.sampleId) await router.replace({ path: '/samples/upload', query: { sampleId: sample.value.sampleId } })
    await preparePlayback()
  } catch (error) {
    sample.value = null
    await ElMessageBox.alert(`${error.message || '样本上传失败'}\n\n请重新选择系统保存出的完整样本目录。`, '上传失败', { type: 'error', confirmButtonText: '重新上传' })
  } finally {
    uploading.value = false
  }
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
    await preparePlayback()
  } catch (error) {
    sample.value = null
    await ElMessageBox.alert(`${error.message || '样本加载失败'}\n\n请重新上传样本目录。`, '加载失败', { type: 'error', confirmButtonText: '重新上传' })
  } finally {
    uploading.value = false
  }
}

async function preparePlayback() {
  resetPlaybackState()
  await nextTick()
  resetCharts()
  ensureCharts()
  refreshPlaybackCharts()
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
  chartInstance?.dispose()
  bandChartInstance?.dispose()
  chartInstance = null
  bandChartInstance = null
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
    xAxis: { type: 'category', boundaryGap: false, axisLine: { lineStyle: { color: '#9db4c0' } }, data: getTimelineXAxisData() },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' }, axisLine: { show: false }, splitLine: { lineStyle: { color: '#e6eef2' } } },
    series: getVisibleBandNames().map((name) => ({
      name: BAND_LABELS[name],
      type: 'line',
      showSymbol: false,
      smooth: true,
      animation: false,
      lineStyle: { width: 2, color: BAND_COLORS[name] },
      itemStyle: { color: BAND_COLORS[name] },
      data: getBandTrendData(name)
    }))
  }
}

function ensureCharts() {
  ensureWaveChart()
  ensureBandTrendChart()
}

function ensureWaveChart() {
  if (!chartRef.value) return
  if (!chartInstance) chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(getWaveChartOption())
  chartInstance.resize()
}

function ensureBandTrendChart() {
  if (!bandChartRef.value) return
  if (!bandChartInstance) bandChartInstance = echarts.init(bandChartRef.value)
  bandChartInstance.setOption(getBandTrendChartOption())
  bandChartInstance.resize()
}

function refreshPlaybackCharts() {
  refreshWaveChart()
  refreshBandTrendChart()
}

function refreshWaveChart() {
  const now = performance.now()
  if (now - lastWaveRenderAt < RENDER_INTERVAL_MS) return
  lastWaveRenderAt = now
  updateDisplayAmplitude()
  ensureWaveChart()
  if (!chartInstance) return
  chartInstance.setOption(getWaveChartOption(), true)
  chartInstance.resize()
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
  const visible = getVisibleTimeline()
  const values = visible.map((item) => Number(getBandSnapshot(item?.raw_powers)[name] || 0).toFixed(2)).map(Number)
  return padTimelineData(values)
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
  chartInstance?.resize()
  bandChartInstance?.resize()
}

window.addEventListener('resize', resizeChart)
onMounted(() => { if (route.query.sampleId) void loadSample(String(route.query.sampleId)) })
onBeforeUnmount(() => {
  stopPlayback()
  window.removeEventListener('resize', resizeChart)
  chartInstance?.dispose()
  bandChartInstance?.dispose()
  chartInstance = null
  bandChartInstance = null
})
</script>

<template>
  <div class="detail-page">
    <section class="top-bar">
      <div>
        <div class="kicker">样本数据上传</div>
        <h1>{{ sample ? sampleTitle : '上传已保存样本进行演示' }}</h1>
        <p>展示样本视频、脑电波形、波段占比、面部识别结果和综合状态。</p>
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
        <div class="quick-card"><span>设备地址</span><strong>{{ getPortText() }}</strong></div>
        <div class="quick-card"><span>接入状态</span><strong>{{ getAccessText() }}</strong></div>
        <div class="quick-card"><span>综合状态</span><strong>{{ emotionText }}</strong></div>
        <div class="quick-card"><span>最近时间</span><strong>{{ latestTime() }}</strong></div>
      </div>
    </section>

    <section v-if="sample" class="content-grid">
      <article class="panel video-panel">
        <div class="panel-head">
          <h3>微表情视频与识别</h3>
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
        <div class="result-grid">
          <div class="metric-box"><span>面部接入状态</span><strong>{{ getFaceStatusLabel() }}</strong></div>
          <div class="metric-box"><span>视频接入通道</span><strong>{{ getCameraLabel() }}</strong></div>
          <div class="metric-box"><span>视频更新时间</span><strong>{{ latestTime() }}</strong></div>
          <div class="metric-box"><span>辅助信号状态</span><strong>{{ getFaceStatusLabel() }}</strong></div>
        </div>
      </article>

      <article class="panel eeg-panel">
        <div class="panel-head">
          <h3>脑电波形与特征波段</h3>
          <div class="eeg-actions"><el-tag :type="sample ? 'success' : 'info'">{{ getEegStatusLabel() }}</el-tag></div>
        </div>
        <div class="signal-strip">
          <div class="signal-item"><span>脑电状态</span><strong>{{ getEegStatusLabel() }}</strong></div>
          <div class="signal-item"><span>波形更新状态</span><strong>{{ waveStatusText }}</strong></div>
        </div>
        <div class="chart-title">原始脑电波形（{{ rawSampleRate }}Hz，4秒示波器视图，数值未处理）</div>
        <div class="chart-wrap wave-chart-wrap">
          <div ref="chartRef" class="eeg-chart"></div>
          <div v-if="!rawWaveBuffer.length" class="chart-empty">等待波形回放</div>
        </div>
        <div class="chart-title">特征波段时序</div>
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
          <div class="metric-box"><span>Theta 占比</span><strong>{{ formatBand(currentBandSnapshot.theta) }}</strong></div>
          <div class="metric-box"><span>Alpha 占比</span><strong>{{ formatBand(currentBandSnapshot.alpha) }}</strong></div>
          <div class="metric-box"><span>Beta 占比</span><strong>{{ formatBand(currentBandSnapshot.beta) }}</strong></div>
          <div class="metric-box"><span>Delta 占比</span><strong>{{ formatBand(currentBandSnapshot.delta) }}</strong></div>
          <div class="metric-box"><span>Gamma 占比</span><strong>{{ formatBand(currentBandSnapshot.gamma) }}</strong></div>
        </div>
      </article>

      <article class="panel warning-panel">
        <div class="panel-head">
          <h3>状态预警</h3>
          <el-tag :type="alertType" effect="dark">{{ warningText }}</el-tag>
        </div>
        <el-alert :type="alertType" :closable="false" show-icon :title="warningText" />
        <div class="warning-grid">
          <div class="metric-box"><span>当前状态</span><strong>{{ emotionText }}</strong></div>
          <div class="metric-box"><span>接入状态</span><strong>{{ getAccessText() }}</strong></div>
          <div class="metric-box"><span>视频通道</span><strong>{{ getFaceStatusLabel() }}</strong></div>
          <div class="metric-box"><span>脑电通道</span><strong>{{ getEegStatusLabel() }}</strong></div>
          <div class="metric-box"><span>最近时间</span><strong>{{ latestTime() }}</strong></div>
          <div class="metric-box"><span>处理建议</span><strong>{{ adviceText() }}</strong></div>
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
.top-bar, .base-panel, .panel { border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: 0 14px 32px rgba(66,101,122,.08); }
.top-bar { display: flex; justify-content: space-between; gap: 20px; padding: 24px 28px; }
.kicker { font-size: 13px; color: #547089; }
.top-bar h1 { margin: 8px 0 12px; }
.top-bar p { margin: 0; color: #64748b; }
.top-actions, .panel-head, .eeg-actions { display: flex; align-items: center; gap: 12px; }
.top-actions, .panel-head { justify-content: space-between; }
.folder-input { display: none; }
.base-panel { margin-top: 20px; padding: 20px 24px; }
.config-grid, .quick-grid, .content-grid, .result-grid, .signal-strip, .warning-grid, .band-grid { display: grid; gap: 16px; }
.config-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.config-grid :deep(.el-form-item) { margin-bottom: 0; }
.quick-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 16px; }
.quick-card, .metric-box, .signal-item { padding: 14px 16px; border-radius: 8px; background: #f7fafc; }
.quick-card span, .metric-box span, .signal-item span { display: block; margin-bottom: 6px; font-size: 12px; color: #64748b; }
.quick-card strong, .metric-box strong, .signal-item strong { font-size: 18px; color: #203444; }
.content-grid { margin-top: 20px; grid-template-columns: 1.08fr 1.46fr .9fr; }
.panel { padding: 20px; }
.video-box, .empty-box { margin-top: 16px; height: 320px; border-radius: 8px; overflow: hidden; background: #07121f; }
.result-video { width: 100%; height: 100%; border: 0; background: #07121f; }
.empty-box { display: flex; align-items: center; justify-content: center; color: #dbeafe; }
.result-grid, .signal-strip, .warning-grid, .band-grid { margin-top: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.chart-title { margin: 18px 0 8px; font-weight: 700; color: #203444; }
.band-switch { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 10px; }
.chart-wrap { position: relative; border-radius: 8px; background: #fbfeff; border: 1px solid #e4edf2; }
.wave-chart-wrap { min-height: 260px; }
.trend-chart-wrap { min-height: 240px; }
.eeg-chart { height: 320px; width: 100%; }
.trend-chart { height: 240px; width: 100%; }
.chart-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #7b8a97; pointer-events: none; }
.empty-wrap { min-height: 420px; display: flex; align-items: center; justify-content: center; }
@media (max-width: 1440px) { .content-grid { grid-template-columns: 1fr; } .config-grid, .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 960px) { .detail-page { padding: 16px; } .top-bar, .top-actions { flex-direction: column; align-items: flex-start; } .config-grid, .quick-grid, .result-grid, .signal-strip, .warning-grid, .band-grid { grid-template-columns: 1fr; } }
</style>
