<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  EEG_EMOTION_TEXT as EMOTION_TEXT,
  EEG_FEATURE_EXPLANATIONS,
  EEG_STATE_COLORS as STATE_COLORS,
  EEG_STATE_KEYS as STATE_KEYS,
  getFeatureContributionOption as buildFeatureContributionOption,
  getRadarOption as buildRadarOption,
  getStateFeatureProfiles,
  getStateHeatmapOption,
  getStateTrendOption,
  hasZFeatureData as hasTimelineZFeatureData
} from '@/views/alert/eegVisualHelper'

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
const gaugeChartRef = ref(null)
const featureChartRef = ref(null)
const heatmapChartRef = ref(null)
const radarChartRef = ref(null)
const uploading = ref(false)
const uploadPercent = ref(0)
const sample = ref(null)
const playbackState = ref('idle')
const rawWaveBuffer = ref([])
const visualPage = ref('indices')
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
const thresholdCounts = computed(() => getWindowSummary('thresholdCounts'))
const dominantVotes = computed(() => getWindowSummary('dominantVotes'))
const validPredictionCount = computed(() => {
  const serverValue = Number(sample.value?.validPredictionCount)
  if (Number.isFinite(serverValue)) return serverValue
  return eegTimeline.value.filter((item) => item?.valid_current === true).length
})
const hasZFeatureData = computed(() => hasTimelineZFeatureData(eegTimeline.value))
const featureExplanations = computed(() => EEG_FEATURE_EXPLANATIONS)
const stateFeatureProfiles = computed(() => getStateFeatureProfiles(eegTimeline.value))
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
  visualPage.value = 'indices'
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
  displayAmplitude = 100
  lastWaveRenderAt = 0
  playedSampleCount = 0
  playedTimelineCount = 0
  playbackState.value = sample.value ? 'loaded' : 'idle'
}

function resetCharts() {
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

function getGaugeChartOption() {
  return getStateTrendOption(eegTimeline.value, {
    cursorIndex: getPlaybackCursorIndex(),
    cursorLabel: '播放位置'
  })
}

function getFeatureContributionOption() {
  return buildFeatureContributionOption(eegTimeline.value)
}

function getHeatmapOption() {
  return getStateHeatmapOption(eegTimeline.value)
}

function getRadarOption() {
  return buildRadarOption(eegTimeline.value)
}

function ensureCharts() {
  const failures = []
  renderChartSafely('状态指数趋势', ensureGaugeChart, failures)
  renderChartSafely('特征贡献', ensureFeatureChart, failures)
  renderChartSafely('阈值矩阵', ensureHeatmapChart, failures)
  renderChartSafely('特征轮廓雷达', ensureRadarChart, failures)
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
  if (!hasZFeatureData.value) {
    featureChartInstance?.clear()
    return
  }
  if (featureChartRef.value && !featureChartInstance) featureChartInstance = echarts.init(featureChartRef.value)
  featureChartInstance?.setOption(getFeatureContributionOption(), true)
  featureChartInstance?.resize()
}

function ensureHeatmapChart() {
  if (heatmapChartRef.value && !heatmapChartInstance) heatmapChartInstance = echarts.init(heatmapChartRef.value)
  heatmapChartInstance?.setOption(getHeatmapOption(), true)
  heatmapChartInstance?.resize()
}

function ensureRadarChart() {
  if (!hasZFeatureData.value) {
    radarChartInstance?.clear()
    return
  }
  if (radarChartRef.value && !radarChartInstance) radarChartInstance = echarts.init(radarChartRef.value)
  radarChartInstance?.setOption(getRadarOption(), true)
  radarChartInstance?.resize()
}

function refreshPlaybackCharts() {
  renderChartSafely('状态指数趋势', ensureGaugeChart)
  renderChartSafely('阈值矩阵', ensureHeatmapChart)
  if (hasZFeatureData.value) {
    renderChartSafely('特征贡献', ensureFeatureChart)
    renderChartSafely('特征轮廓雷达', ensureRadarChart)
  }
}

async function setVisualPage(page) {
  visualPage.value = page
  await nextTick()
  resizeChart()
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

function getFaceStatusLabel() { return sample.value ? faceStatusText.value : '待加载' }
function getEegStatusLabel() { return sample.value ? eegStatusText.value : '待加载' }
function getAccessText() { return sample.value ? '已接入' : '自动接入中' }
function getPortText() { return latestEeg.value.baseUrl || '--' }
function getCameraLabel() { return manifest.value.cameraId || '未配置摄像头' }
function latestTime() { return sampleTime.value || '--:--:--' }
function adviceText() { return emotionKey.value === 'normal' ? '继续监测' : '建议关注' }
function formatShortTime(value) {
  const date = value ? new Date(Number(value)) : new Date()
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}
function resizeChart() {
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
  gaugeChartInstance?.dispose()
  featureChartInstance?.dispose()
  heatmapChartInstance?.dispose()
  radarChartInstance?.dispose()
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
          <p>第一页看异常状态强弱，第二页解释脑电特征为什么支持当前样本标签。</p>
        </div>
        <div class="visual-actions">
          <el-button-group class="page-switch">
            <el-button :type="visualPage === 'indices' ? 'primary' : 'default'" @click="setVisualPage('indices')">异常状态指数</el-button>
            <el-button :type="visualPage === 'features' ? 'primary' : 'default'" @click="setVisualPage('features')">脑电特征解释</el-button>
          </el-button-group>
        </div>
      </div>

      <div v-show="visualPage === 'indices'" class="visual-page">
        <div class="page-note">
          <strong>状态指数说明：</strong>
          10 秒窗口内每秒计算四类状态指数，超过 59 表示该秒出现对应异常证据；主导票表示这一秒四类指数中最高的状态。
        </div>
        <div class="visual-grid index-grid">
          <article class="visual-card matrix-card">
            <div class="visual-title">
              <span>四状态阈值热力图</span>
              <small>颜色越深指数越高，过 59 的格子加粗高亮</small>
            </div>
            <div ref="heatmapChartRef" class="heatmap-chart large-chart"></div>
            <div class="soft-legend">
              <span>低指数</span>
              <i class="legend-gradient"></i>
              <span>高指数</span>
              <em>超过 59 的格子会加粗标边</em>
            </div>
          </article>
          <article class="visual-card state-card">
            <div class="visual-title">
              <span>四状态指数趋势</span>
              <small>红色虚线为阈值 59，绿色竖线为播放位置</small>
            </div>
            <div ref="gaugeChartRef" class="gauge-chart large-chart"></div>
          </article>
        </div>
      </div>

      <div v-show="visualPage === 'features'" class="visual-page">
        <div class="page-note feature-note">
          <strong>相对基线 Z-score 说明：</strong>
          <span v-if="hasZFeatureData">只展示个人基线换算后的相对强度；图中 50 是显示中线，表示接近个人基线，70 以上表示对应状态特征明显增强。</span>
          <span v-else>该样本缺少个人基线 Z-score，无法展示特征解释；第一页状态指数仍可正常查看。</span>
        </div>
        <div v-if="hasZFeatureData" class="visual-grid feature-grid">
          <article class="visual-card contribution-card">
            <div class="visual-title">
              <span>四状态特征贡献柱状图</span>
              <small>越高表示该状态相关脑电特征越明显</small>
            </div>
            <div ref="featureChartRef" class="feature-chart large-chart"></div>
          </article>
          <article class="visual-card radar-card">
            <div class="visual-title">
              <span>四状态特征轮廓雷达图</span>
              <small>看当前窗口整体更偏向哪一类异常</small>
            </div>
            <div ref="radarChartRef" class="radar-chart large-chart"></div>
          </article>
          <article class="visual-card evidence-card">
            <div class="visual-title">
              <span>脑电特征花瓣图</span>
              <small>每根花瓣对应一个中间特征，花瓣越长说明该特征越明显</small>
            </div>
            <div class="flower-chart">
              <svg class="flower-svg" viewBox="0 0 560 560" aria-hidden="true">
                <circle class="flower-ring" cx="280" cy="280" r="82"></circle>
                <circle class="flower-ring" cx="280" cy="280" r="160"></circle>
                <circle class="flower-ring strong" cx="280" cy="280" r="240"></circle>
                <text class="flower-axis-label fatigue" x="102" y="104">疲劳特征</text>
                <text class="flower-axis-label stress" x="394" y="104">紧张特征</text>
                <text class="flower-axis-label anxiety" x="392" y="468">焦虑特征</text>
                <text class="flower-axis-label weakness" x="88" y="468">虚弱特征</text>
                <g
                  v-for="profile in stateFeatureProfiles"
                  :key="profile.key"
                  :class="['flower-group', profile.key, { active: profile.active }]"
                  :style="{ '--state-color': profile.color }"
                >
                  <line
                    v-for="petal in profile.petals"
                    :key="`${profile.key}-${petal.label}`"
                    class="flower-petal"
                    :x1="petal.x1"
                    :y1="petal.y1"
                    :x2="petal.x2"
                    :y2="petal.y2"
                  ></line>
                  <circle
                    v-for="petal in profile.petals"
                    :key="`${profile.key}-${petal.label}-dot`"
                    class="flower-dot"
                    :cx="petal.x2"
                    :cy="petal.y2"
                    r="5"
                  ></circle>
                </g>
                <circle class="flower-center" cx="280" cy="280" r="56"></circle>
                <text class="flower-center-title" x="280" y="274">10秒</text>
                <text class="flower-center-subtitle" x="280" y="300">特征指纹</text>
              </svg>
              <div class="flower-legend">
              <article
                v-for="profile in stateFeatureProfiles"
                :key="profile.key"
                class="flower-legend-item"
                :class="{ active: profile.active }"
                :style="{ '--state-color': profile.color }"
              >
                <strong>{{ profile.name }}</strong>
                <span>{{ profile.topFeatures }}</span>
              </article>
              </div>
            </div>
          </article>
        </div>
        <div v-else class="evidence-empty z-empty">当前样本没有 features.z 字段，特征解释页不做原始值回退，避免与个人基线口径混用。</div>

        <div v-if="hasZFeatureData" class="explain-grid">
          <article v-for="item in featureExplanations" :key="item.state" class="explain-card" :style="{ '--state-color': item.color }">
            <strong>{{ item.state }}</strong>
            <p>{{ item.text }}</p>
          </article>
        </div>
      </div>
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
.top-actions, .panel-head { display: flex; align-items: center; gap: 12px; }
.top-actions, .panel-head { justify-content: space-between; }
.folder-input { display: none; }
.base-panel { margin-top: 20px; padding: 20px 24px; }
.config-grid, .quick-grid, .top-content-grid, .warning-grid, .visual-grid { display: grid; gap: 16px; }
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
.warning-grid { margin-top: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
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
.visual-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: flex-end; }
.page-switch :deep(.el-button) { min-width: 136px; height: 40px; font-size: 15px; font-weight: 700; }
.visual-page { margin-top: 18px; }
.page-note { padding: 14px 16px; border-radius: 10px; border: 1px solid #cfe9ed; background: linear-gradient(135deg, #eefafa, #f8fcff); color: #476275; font-size: 15px; line-height: 1.75; }
.page-note strong { color: #0f766e; }
.feature-note { margin-bottom: 16px; }
.visual-grid { margin-top: 18px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.visual-card { position: relative; border-radius: 12px; border: 1px solid #dce9ee; background: #fff; box-shadow: 0 8px 22px rgba(61,101,120,.07); }
.visual-title { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 16px 18px 0; color: #203444; font-weight: 800; }
.visual-title span { font-size: 18px; }
.visual-title small { color: #718696; font-weight: 500; font-size: 13px; }
.large-chart { height: 470px; }
.evidence-card { grid-column: 1 / -1; padding-bottom: 18px; }
.soft-legend { display: flex; align-items: center; gap: 10px; margin: -22px 18px 16px; color: #64748b; font-size: 13px; }
.soft-legend em { margin-left: auto; font-style: normal; color: #7a8b99; }
.legend-gradient { width: 180px; height: 12px; border-radius: 999px; background: linear-gradient(90deg, #f7fbff, #dbeafe, #93c5fd, #5eead4, #fbbf24, #f97316); border: 1px solid #d7e4ea; }
.flower-chart { display: grid; grid-template-columns: minmax(420px, .92fr) 1fr; gap: 18px; align-items: center; margin: 18px; padding: 18px; border-radius: 18px; border: 1px solid #d7e8ee; background: radial-gradient(circle at 32% 50%, #ffffff 0%, #f6fbfd 58%, #eef7fa 100%); }
.flower-svg { width: 100%; max-height: 620px; min-height: 520px; overflow: visible; }
.flower-ring { fill: none; stroke: #dbe8ee; stroke-width: 1.2; }
.flower-ring.strong { stroke: #c6dbe3; stroke-width: 1.6; stroke-dasharray: 6 7; }
.flower-axis-label { fill: #64748b; font-size: 18px; font-weight: 900; letter-spacing: .5px; }
.flower-group { color: var(--state-color); }
.flower-petal { stroke: currentColor; stroke-width: 18; stroke-linecap: round; opacity: .46; filter: drop-shadow(0 8px 12px rgba(39,73,89,.16)); }
.flower-dot { fill: #fff; stroke: currentColor; stroke-width: 3; opacity: .95; }
.flower-group.active .flower-petal { stroke-width: 24; opacity: .82; filter: drop-shadow(0 12px 18px rgba(15,118,110,.2)); }
.flower-group.active .flower-dot { r: 6; }
.flower-center { fill: #0f766e; filter: drop-shadow(0 12px 22px rgba(15,118,110,.28)); }
.flower-center-title, .flower-center-subtitle { fill: #fff; text-anchor: middle; font-weight: 900; }
.flower-center-title { font-size: 22px; }
.flower-center-subtitle { font-size: 17px; opacity: .9; }
.flower-legend { display: grid; gap: 12px; }
.flower-legend-item { border-left: 5px solid var(--state-color); border-radius: 12px; padding: 14px 16px; background: rgba(255,255,255,.86); box-shadow: 0 8px 18px rgba(61,101,120,.06); }
.flower-legend-item.active { background: #eefafa; box-shadow: 0 12px 24px rgba(15,118,110,.14); }
.flower-legend-item strong { display: block; color: var(--state-color); font-size: 20px; margin-bottom: 6px; }
.flower-legend-item span { color: #64748b; font-size: 13px; line-height: 1.5; }
.evidence-empty { display: flex; align-items: center; justify-content: center; min-height: 220px; color: #7b8a97; }
.explain-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.explain-card { position: relative; padding: 16px; border-radius: 10px; border: 1px solid #e1ebef; background: #f9fcfd; }
.explain-card::before { content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px; border-radius: 4px; background: var(--state-color); }
.explain-card strong { color: var(--state-color); font-size: 17px; }
.explain-card p { margin: 8px 0 0; color: #607483; font-size: 13px; line-height: 1.65; }
.chart-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #7b8a97; pointer-events: none; }
.empty-wrap { min-height: 420px; display: flex; align-items: center; justify-content: center; }
@media (max-width: 1440px) { .top-content-grid { grid-template-columns: 1fr 1fr; } .warning-panel { grid-column: 1 / -1; } .config-grid, .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .explain-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 960px) { .detail-page { padding: 16px; } .top-bar, .top-actions, .panel-head, .visual-title, .section-heading, .visual-actions { flex-direction: column; align-items: flex-start; } .config-grid, .quick-grid, .top-content-grid, .warning-grid, .visual-grid, .explain-grid { grid-template-columns: 1fr; } .warning-panel, .evidence-card { grid-column: auto; } .large-chart { height: 420px; } .soft-legend { flex-wrap: wrap; margin-top: -8px; } .soft-legend em { margin-left: 0; } .flower-chart { grid-template-columns: 1fr; } .flower-svg { min-height: 420px; } }
</style>
