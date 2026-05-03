<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useEegStore } from '@/stores/eeg'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

const router = useRouter()
const store = useEegStore()
const portList = ref([])
const selectedPort = ref('')
const collecting = ref(false)
const lineChartRef = ref(null)
const rawWaveCache = ref([])
const MAX_POINTS = 512
let lineChartInstance = null

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

async function loadPorts() {
  try {
    const res = await request.get('/eeg/ports')
    portList.value = Array.isArray(res?.data) ? res.data : []
    selectedPort.value = portList.value[0] || ''
  } catch (error) {
    console.warn('加载脑电端口失败', error)
    portList.value = []
  }
}

function initLineChart() {
  if (!lineChartRef.value) return
  lineChartInstance = echarts.init(lineChartRef.value)
  lineChartInstance.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 44, right: 18, top: 24, bottom: 34 },
    xAxis: { type: 'category', boundaryGap: false, data: [] },
    yAxis: { type: 'value', min: 'dataMin', max: 'dataMax' },
    series: [{
      name: '脑电波形',
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
  lineChartInstance.setOption({
    xAxis: { data: rawWaveCache.value.map((_, index) => index) },
    series: [{ data: rawWaveCache.value }]
  })
}

function startCollect() {
  if (!selectedPort.value) {
    ElMessage.warning('请先选择脑电端口')
    return
  }
  if (collecting.value) return
  store.startSse({ port: selectedPort.value })
  collecting.value = true
  ElMessage.success(`已接入 ${selectedPort.value}`)
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
  await loadPorts()
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
        <el-select v-model="selectedPort" placeholder="选择端口" size="small" class="port-select">
          <el-option v-for="port in portList" :key="port" :label="port" :value="port" />
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
            <div class="card-title">1-40Hz 滤波后实时波形</div>
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

