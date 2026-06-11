<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useEegStore } from '@/stores/eeg'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'

const router = useRouter()
const store = useEegStore()
const deviceList = ref([])
const selectedWorkerId = ref(null)
const collecting = ref(false)
const lineChartRef = ref(null)
const rawWaveCache = ref([])
const DISPLAY_SECONDS = 4
const MAX_POINTS = 512 * DISPLAY_SECONDS
const RENDER_INTERVAL_MS = 50
let lineChartInstance = null
let lastRenderAt = 0
let displayAmplitude = 100

const statusType = computed(() => {
  if (store.status === 'poor_signal') return 'warning'
  if (store.status === 'ok') return 'success'
  if (store.status === 'calibrating') return 'info'
  return 'info'
})

const bandData = computed(() => [
  { name: 'Delta', value: store.deltaPower },
  { name: 'Theta', value: store.thetaPower },
  { name: 'Alpha', value: store.alphaPower },
  { name: 'Beta', value: store.betaPower },
  { name: 'Gamma', value: store.gammaPower }
])

const indexData = computed(() => [
  { name: '焦虑', value: store.indices.anxiety_idx },
  { name: '紧张', value: store.indices.stress_idx },
  { name: '疲劳', value: store.indices.fatigue_idx },
  { name: '虚弱', value: store.indices.weakness_idx }
])

async function loadDevices() {
  try {
    const response = await fetch('/eeg/devices', { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const res = await response.json()
    deviceList.value = Array.isArray(res?.data) ? res.data : []
    selectedWorkerId.value = deviceList.value[0]?.workerId ?? null
  } catch (error) {
    console.warn('加载脑电设备失败', error)
    deviceList.value = []
  }
}

function initLineChart() {
  if (!lineChartRef.value) return
  lineChartInstance = echarts.init(lineChartRef.value)
  lineChartInstance.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 44, right: 18, top: 24, bottom: 34 },
    xAxis: { type: 'category', boundaryGap: false, name: '时间（秒）', data: [] },
    yAxis: { type: 'value', min: -displayAmplitude, max: displayAmplitude, name: 'TGAM 原始值' },
    series: [{
      name: '原始脑电波形（512Hz）',
      type: 'line',
      data: [],
      showSymbol: false,
      sampling: 'lttb',
      lineStyle: { width: 1.5, color: '#0f766e' },
      areaStyle: { opacity: 0.08, color: '#0f766e' },
      animation: false
    }]
  })
}

function updateLineChart(newSamples) {
  if (!lineChartInstance || !Array.isArray(newSamples) || !newSamples.length) return
  rawWaveCache.value.push(...newSamples.map(Number).filter(Number.isFinite))
  if (rawWaveCache.value.length > MAX_POINTS) {
    rawWaveCache.value.splice(0, rawWaveCache.value.length - MAX_POINTS)
  }
  const now = performance.now()
  if (now - lastRenderAt < RENDER_INTERVAL_MS) return
  lastRenderAt = now
  const peak = rawWaveCache.value.reduce((max, value) => Math.max(max, Math.abs(value)), 0)
  const targetAmplitude = Math.max(100, peak * 1.15)
  displayAmplitude = targetAmplitude > displayAmplitude
    ? targetAmplitude
    : Math.max(targetAmplitude, displayAmplitude * 0.985)
  const sampleRate = Number(store.rawWaveFs || 512)
  const pointCount = rawWaveCache.value.length
  lineChartInstance.setOption({
    xAxis: { data: rawWaveCache.value.map((_, index) => ((index - pointCount + 1) / sampleRate).toFixed(1)) },
    yAxis: { min: -displayAmplitude, max: displayAmplitude },
    series: [{ data: rawWaveCache.value }]
  })
}

function startCollect() {
  if (selectedWorkerId.value == null) {
    ElMessage.warning('请先选择脑电设备')
    return
  }
  if (collecting.value) return
  store.startSse({ workerId: selectedWorkerId.value })
  collecting.value = true
  ElMessage.success('已接入脑电设备')
}

function stopCollect() {
  if (!collecting.value) return
  store.stopSse()
  collecting.value = false
  ElMessage.info('已停止接入')
}

function handleResize() {
  lineChartInstance?.resize()
}

onMounted(async () => {
  await loadDevices()
  initLineChart()
  watch(() => store.rawWave, updateLineChart)
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  lineChartInstance?.dispose()
})
</script>

<template>
  <el-container class="page-container">
    <el-header class="header-bar">
      <div class="header-left">
        <h2>脑电采集与状态推理</h2>
        <el-tag :type="statusType" size="small">{{ store.statusText }}</el-tag>
      </div>
      <div class="header-right">
        <el-select v-model="selectedWorkerId" placeholder="选择设备" size="small" class="port-select">
          <el-option v-for="device in deviceList" :key="device.workerId" :label="`${device.name} / ${device.baseUrl}`" :value="device.workerId" />
        </el-select>
        <el-button type="primary" size="small" :disabled="collecting" @click="startCollect">开始接入</el-button>
        <el-button type="danger" size="small" :disabled="!collecting" @click="stopCollect">停止</el-button>
        <el-button size="small" @click="router.back()">返回</el-button>
      </div>
    </el-header>

    <el-main class="main">
      <el-row :gutter="20">
        <el-col :span="16">
          <el-card shadow="hover" class="chart-card">
            <div class="card-title">设备原始脑电波形（512Hz，4秒示波器视图，数值未处理）</div>
            <div ref="lineChartRef" class="line-chart"></div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="hover" class="stat-card">
            <div class="state-label">当前状态</div>
            <div class="state-value">{{ store.emotionZh }}</div>
            <el-tag :type="statusType">信号 {{ store.signalQuality ?? '--' }} / {{ store.qualityLevel }}</el-tag>
            <div class="small-row">专注 {{ store.attention ?? '--' }} / 放松 {{ store.meditation ?? '--' }}</div>
            <el-divider />
            <div class="metric-grid">
              <div v-for="item in indexData" :key="item.name" class="metric-item">
                <span>{{ item.name }}</span>
                <strong>{{ Number(item.value || 0).toFixed(1) }}</strong>
              </div>
            </div>
            <el-divider />
            <div class="band-grid">
              <div v-for="item in bandData" :key="item.name" class="metric-item">
                <span>{{ item.name }}</span>
                <strong>{{ Number(item.value || 0).toFixed(1) }}%</strong>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-main>
  </el-container>
</template>

<style scoped>
.page-container { height: 100%; background: #f5f7fa; }
.header-bar { display: flex; justify-content: space-between; align-items: center; padding: 14px 24px; background: #fff; border-bottom: 1px solid #dcdfe6; }
.header-left, .header-right { display: flex; align-items: center; gap: 12px; }
.header-left h2 { margin: 0; font-size: 20px; }
.port-select { width: 150px; }
.main { padding: 24px; }
.chart-card, .stat-card { border-radius: 8px; }
.card-title { font-weight: 600; margin-bottom: 12px; }
.line-chart { width: 100%; height: 420px; }
.stat-card { text-align: center; }
.state-label { color: #64748b; font-size: 13px; }
.state-value { margin: 8px 0 12px; font-size: 34px; font-weight: 700; color: #0f766e; }
.small-row { margin-top: 12px; color: #64748b; }
.metric-grid, .band-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.metric-item { padding: 10px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.metric-item span { display: block; color: #64748b; font-size: 12px; }
.metric-item strong { display: block; margin-top: 4px; font-size: 18px; color: #111827; }
</style>

