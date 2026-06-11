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
const trendRef = ref(null)
const barRef = ref(null)
const history = ref([])
const MAX_POINTS = 120
let trendChart = null
let barChart = null

const statusType = computed(() => {
  if (store.status === 'poor_signal') return 'warning'
  if (store.status === 'ok') return 'success'
  return 'info'
})

const stats = computed(() => {
  const values = history.value.map(item => item.fatigue)
  if (!values.length) {
    return [
      { name: '平均疲劳指数', value: '--' },
      { name: '最高疲劳指数', value: '--' },
      { name: '当前状态', value: store.emotionZh },
      { name: '信号质量', value: store.signalQuality ?? '--' }
    ]
  }
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length
  return [
    { name: '平均疲劳指数', value: avg.toFixed(1) },
    { name: '最高疲劳指数', value: Math.max(...values).toFixed(1) },
    { name: '当前状态', value: store.emotionZh },
    { name: '信号质量', value: store.signalQuality ?? '--' }
  ]
})

async function loadDevices() {
  try {
    const response = await fetch('/eeg/devices', { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const res = await response.json()
    deviceList.value = Array.isArray(res?.data) ? res.data : []
    selectedWorkerId.value = deviceList.value[0]?.workerId ?? null
  } catch (error) {
    console.warn('加载脑电设备失败', error)
  }
}

function initCharts() {
  if (trendRef.value) {
    trendChart = echarts.init(trendRef.value)
    trendChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['疲劳', '紧张', '焦虑', '虚弱'], bottom: 0 },
      grid: { left: 44, right: 18, top: 24, bottom: 48 },
      xAxis: { type: 'category', boundaryGap: false, data: [] },
      yAxis: { type: 'value', min: 0, max: 100 },
      series: ['疲劳', '紧张', '焦虑', '虚弱'].map(name => ({ name, type: 'line', showSymbol: false, smooth: true, data: [] }))
    })
  }
  if (barRef.value) {
    barChart = echarts.init(barRef.value)
    barChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 44, right: 18, top: 24, bottom: 36 },
      xAxis: { type: 'category', data: ['焦虑', '紧张', '疲劳', '虚弱'] },
      yAxis: { type: 'value', min: 0, max: 100 },
      series: [{ type: 'bar', barWidth: '46%', data: [] }]
    })
  }
}

function pushHistory() {
  history.value.push({
    time: new Date().toLocaleTimeString(),
    fatigue: Number(store.indices.fatigue_idx || 0),
    stress: Number(store.indices.stress_idx || 0),
    anxiety: Number(store.indices.anxiety_idx || 0),
    weakness: Number(store.indices.weakness_idx || 0)
  })
  if (history.value.length > MAX_POINTS) history.value.shift()
  updateCharts()
}

function updateCharts() {
  const xData = history.value.map((_, index) => index + 1)
  trendChart?.setOption({
    xAxis: { data: xData },
    series: [
      { data: history.value.map(item => item.fatigue) },
      { data: history.value.map(item => item.stress) },
      { data: history.value.map(item => item.anxiety) },
      { data: history.value.map(item => item.weakness) }
    ]
  })
  barChart?.setOption({
    series: [{ data: [store.indices.anxiety_idx, store.indices.stress_idx, store.indices.fatigue_idx, store.indices.weakness_idx] }]
  })
}

function startAnalysis() {
  if (selectedWorkerId.value == null) return ElMessage.warning('请先选择脑电设备')
  if (collecting.value) return
  store.startSse({ workerId: selectedWorkerId.value })
  collecting.value = true
  ElMessage.success('已接入脑电设备')
}

function stopAnalysis() {
  if (!collecting.value) return
  store.stopSse()
  collecting.value = false
  ElMessage.info('已停止分析')
}

function resizeCharts() {
  trendChart?.resize()
  barChart?.resize()
}

onMounted(async () => {
  await loadDevices()
  initCharts()
  watch(() => store.analysisTime, pushHistory)
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  trendChart?.dispose()
  barChart?.dispose()
})
</script>

<template>
  <el-container class="page-container">
    <el-header class="header-bar">
      <div class="header-left">
        <h2>脑电状态分析</h2>
        <el-tag :type="statusType" size="small">{{ store.statusText }}</el-tag>
      </div>
      <div class="header-right">
        <el-select v-model="selectedWorkerId" placeholder="选择设备" size="small" class="port-select">
          <el-option v-for="device in deviceList" :key="device.workerId" :label="`${device.name} / ${device.baseUrl}`" :value="device.workerId" />
        </el-select>
        <el-button type="primary" size="small" :disabled="collecting" @click="startAnalysis">开始分析</el-button>
        <el-button type="danger" size="small" :disabled="!collecting" @click="stopAnalysis">停止</el-button>
        <el-button size="small" @click="router.back()">返回</el-button>
      </div>
    </el-header>

    <el-main class="main">
      <el-row :gutter="20">
        <el-col :span="14"><el-card class="chart-card"><div class="card-title">四类风险指数趋势</div><div ref="trendRef" class="chart"></div></el-card></el-col>
        <el-col :span="10"><el-card class="chart-card"><div class="card-title">当前指数分布</div><div ref="barRef" class="chart"></div></el-card></el-col>
      </el-row>
      <el-card class="stats-card">
        <div class="card-title">统计摘要</div>
        <el-table :data="stats" size="small" stripe border>
          <el-table-column prop="name" label="指标" width="180" />
          <el-table-column prop="value" label="数值" />
        </el-table>
      </el-card>
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
.chart-card, .stats-card { border-radius: 8px; }
.card-title { font-weight: 600; margin-bottom: 12px; }
.chart { width: 100%; height: 360px; }
.stats-card { margin-top: 20px; }
</style>
