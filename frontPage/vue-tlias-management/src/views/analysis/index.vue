<script setup>
import { ref, onMounted, watch, computed, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import request from '@/utils/request'
import { ElMessage } from 'element-plus'
import {
  ElContainer, ElHeader, ElMain, ElRow, ElCol,
  ElCard, ElDivider, ElButton, ElSelect, ElOption,
  ElTable, ElTableColumn, ElTag
} from 'element-plus'
import { useEegStore } from '@/stores/eeg'

// ====== 路由 & 状态 ======
const router = useRouter()
const store  = useEegStore()

// ====== 端口选择 ======
const portList = ref([])
const selectedPort = ref('')
const collecting = ref(false)

onMounted(async () => {
  try {
    const res = await request.get('/eeg/ports')
    portList.value = res?.data || ['COM1', 'COM2', 'COM3']
    // ✅ 如果默认值不在返回的列表中，也自动补上 COM1
    if (!portList.value.includes('COM1')) {
      portList.value.unshift('COM1')
    }
  } catch {
    portList.value = ['COM1', 'COM2', 'COM3']
    // ✅ 自动启动使用默认端口的逻辑（例如启动采集 / SSE）
    store.startSse({ mode: 'realtime', workerId, port: selectedPort.value })
  }
})

// ====== 图表数据 ======
const idxHistory   = ref([])
const levelHistory = ref([])
const MAX_POINTS   = 100

let trendChart = null
let histChart  = null

// ====== 工具函数 ======
function movingAverage(arr, w = 10) {
  return arr.map((_, i) => {
    const slice = arr.slice(Math.max(0, i - w + 1), i + 1)
    return slice.reduce((a, b) => a + b, 0) / slice.length
  })
}

// ====== 初始化趋势图 ======
function initTrendChart() {
  const el = document.getElementById('trendChart')
  if (!el) return
  trendChart = echarts.init(el)
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['原始', '滑动平均'], bottom: '0%' },
    grid: { left: '8%', right: '8%', bottom: '15%' },
    xAxis: { type: 'category', boundaryGap: false, data: [] },
    yAxis: { type: 'value', min: 0, max: 100 },
    series: [
      { name: '原始', type: 'line', data: [], smooth: false, color: '#409EFF' },
      { name: '滑动平均', type: 'line', data: [], smooth: true, color: '#67C23A' }
    ]
  })
}

function updateTrendChart() {
  idxHistory.value.push(store.fatigueIndex)
  if (idxHistory.value.length > MAX_POINTS) idxHistory.value.shift()
  trendChart?.setOption({
    xAxis: { data: idxHistory.value.map((_, i) => i + 1) },
    series: [
      { data: idxHistory.value },
      { data: movingAverage(idxHistory.value) }
    ]
  })
}

// ====== 初始化分布柱状图 ======
function initHistChart() {
  const el = document.getElementById('histChart')
  if (!el) return
  histChart = echarts.init(el)
  histChart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ['焦躁', '紧张', '疲劳', '虚弱'] },
    yAxis: { type: 'value' },
    series: [{
      name: '频次',
      type: 'bar',
      barWidth: '50%',
      itemStyle: { color: '#E6A23C' },
      data: [0, 0, 0, 0]
    }],
    grid: { left: '10%', right: '10%', bottom: '15%' }
  })
}

function updateHistChart() {
  levelHistory.value.push(store.fatigueLevel)
  if (levelHistory.value.length > MAX_POINTS) levelHistory.value.shift()
  const counts = { '焦躁': 0, '紧张': 0, '疲劳': 0, '虚弱': 0 }
  levelHistory.value.forEach(l => { if (counts[l] !== undefined) counts[l]++ })
  histChart?.setOption({
    series: [{ data: ['焦躁', '紧张', '疲劳', '虚弱'].map(k => counts[k]) }]
  })
}

// ====== 统计摘要 ======
const stats = computed(() => {
  const arr = idxHistory.value
  const mean = arr.length ? (arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(2) : 0
  const sorted = [...arr].sort((a, b) => a - b)
  const n = sorted.length
  const median = n ? (n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2).toFixed(2) : 0
  const std = arr.length ? Math.sqrt(arr.reduce((s, x) => s + (x - mean) ** 2, 0) / arr.length).toFixed(2) : 0
  const min = arr.length ? Math.min(...arr).toFixed(2) : 0
  const max = arr.length ? Math.max(...arr).toFixed(2) : 0
  return [
    { name: '平均值', value: mean },
    { name: '中位数', value: median },
    { name: '标准差', value: std },
    { name: '最小值', value: min },
    { name: '最大值', value: max }
  ]
})

// ====== 控制逻辑 ======
function startAnalysis() {
  if (!selectedPort.value) return ElMessage.warning('请选择端口')
  if (collecting.value) return ElMessage.info('分析中，请勿重复启动')
  store.startSse({ port: selectedPort.value })
  collecting.value = true
  ElMessage.success(`已启动 ${selectedPort.value} 的数据分析`)
}

function stopAnalysis() {
  if (!collecting.value) return
  store.stopSse?.()
  collecting.value = false
  ElMessage.info('已停止分析')
}

// ====== 生命周期 ======
onMounted(() => {
  initTrendChart()
  initHistChart()
  watch(() => store.fatigueIndex, updateTrendChart)
  watch(() => store.fatigueLevel, updateHistChart)
  window.addEventListener('resize', () => {
    trendChart?.resize()
    histChart?.resize()
  })
})

onActivated(() => {
  updateTrendChart()
  updateHistChart()
})
</script>

<template>
  <el-container class="page-container">
    <!-- 顶部控制栏 -->
    <el-header class="header-bar">
      <div class="header-left">
        <h2>脑电波数据分析系统</h2>
        <el-tag type="info" size="small">统计分析</el-tag>
      </div>

      <div class="header-right">
        <el-select v-model="selectedPort" placeholder="选择端口" size="small" class="port-select">
          <el-option v-for="p in portList" :key="p" :label="p" :value="p" />
        </el-select>
        <el-button type="primary" size="small" @click="startAnalysis" :disabled="collecting">开始分析</el-button>
        <el-button type="danger" size="small" @click="stopAnalysis" :disabled="!collecting">停止</el-button>
        <el-button size="small" @click="router.back()">返回</el-button>
      </div>
    </el-header>

    <!-- 主体部分 -->
    <el-main class="main">
      <el-row :gutter="20">
        <el-col :span="12">
          <el-card shadow="hover" class="chart-card">
            <div class="card-title">脑电波指数趋势</div>
            <div id="trendChart" class="chart"></div>
          </el-card>
        </el-col>

        <el-col :span="12">
          <el-card shadow="hover" class="chart-card">
            <div class="card-title">危险情绪分布</div>
            <div id="histChart" class="chart"></div>
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="hover" class="stats-card">
        <div class="card-title">统计摘要</div>
        <el-table :data="stats" size="small" stripe border style="width:100%">
          <el-table-column prop="name" label="指标" width="120" />
          <el-table-column prop="value" label="数值" />
        </el-table>
      </el-card>
    </el-main>
  </el-container>
</template>

<style scoped>
.page-container {
  height: 100%;
  background: #f2f6fc;
}

/* 顶部栏 */
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  padding: 14px 24px;
  border-bottom: 1px solid #dcdfe6;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.port-select {
  width: 140px;
}

.main {
  padding: 24px;
}

.chart-card {
  border-radius: 10px;
  padding: 10px;
}

.card-title {
  text-align: center;
  font-weight: 600;
  font-size: 16px;
  margin-bottom: 12px;
}

.chart {
  width: 100%;
  height: 360px;
}

.stats-card {
  margin-top: 20px;
  border-radius: 10px;
}
</style>
