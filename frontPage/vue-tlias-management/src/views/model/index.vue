<script setup>
import { ref, onMounted, watch, computed, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import request from '@/utils/request'
import { ElMessage } from 'element-plus'
import {
  ElContainer, ElHeader, ElMain, ElRow, ElCol,
  ElCard, ElDivider, ElButton, ElSelect, ElOption, ElTag
} from 'element-plus'
import { useEegStore } from '@/stores/eeg'

// ====== 状态 ======
const router = useRouter()
const store  = useEegStore()

// ====== 端口选择与控制 ======
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

// ====== 本地缓存 ======
const MAX_POINTS   = 100
const indexHistory = ref([])
const levelHistory = ref([])

// ====== 图表引用 ======
let indexChart, levelPieChart, bandBarChart

// ====== 波段功率数据 ======
const bandData = computed(() => [
  { name: 'Delta', value: +(store.deltaPower.toFixed(2)) },
  { name: 'Theta', value: +(store.thetaPower.toFixed(2)) },
  { name: 'Alpha', value: +(store.alphaPower.toFixed(2)) },
  { name: 'Beta',  value: +(store.betaPower.toFixed(2)) }
])

// ====== 初始化：疲劳指数趋势 ======
function initIndexChart() {
  const el = document.getElementById('indexChart')
  if (!el) return
  indexChart = echarts.init(el)
  indexChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: '8%', right: '8%', bottom: '15%' },
    xAxis: { type: 'category', data: [] },
    yAxis: { type: 'value', min: 0, max: 100 },
    series: [{
      name: '疲劳指数',
      type: 'line',
      data: [],
      smooth: true,
      lineStyle: { color: '#409EFF', width: 2 },
      areaStyle: { color: 'rgba(64,158,255,0.1)' }
    }]
  })
}

function updateIndexChart() {
  indexHistory.value.push(store.fatigueIndex)
  if (indexHistory.value.length > MAX_POINTS) indexHistory.value.shift()
  indexChart?.setOption({
    xAxis: { data: indexHistory.value.map((_, i) => i + 1) },
    series: [{ data: indexHistory.value }]
  })
}

// ====== 初始化：疲劳等级分布 ======
function initLevelPie() {
  const el = document.getElementById('levelPie')
  if (!el) return
  levelPieChart = echarts.init(el)
  levelPieChart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: '5%' },
    series: [{
      name: '情绪分布',
      type: 'pie',
      radius: ['45%', '70%'],
      label: { show: false },
      data: []
    }]
  })
}

function updateLevelPie() {
  levelHistory.value.push(store.fatigueLevel)
  if (levelHistory.value.length > MAX_POINTS) levelHistory.value.shift()
  const counts = { '焦躁': 0, '紧张': 0, '疲劳': 0, '虚弱': 0 }
  levelHistory.value.forEach(l => { if (counts[l] !== undefined) counts[l]++ })
  levelPieChart?.setOption({
    series: [{
      data: Object.entries(counts).map(([name, value]) => ({ name, value }))
    }]
  })
}

// ====== 初始化：波段功率分布 ======
function initBandBar() {
  const el = document.getElementById('bandBar')
  if (!el) return
  bandBarChart = echarts.init(el)
  bandBarChart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: bandData.value.map(i => i.name) },
    yAxis: { type: 'value', min: 0, max: 100 },
    grid: { left: '10%', right: '10%', bottom: '15%' },
    series: [{
      name: '功率 (%)',
      type: 'bar',
      barWidth: '50%',
      itemStyle: {
        color: params => ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C'][params.dataIndex]
      },
      data: bandData.value.map(i => i.value)
    }]
  })
}

function updateBandBar() {
  bandBarChart?.setOption({
    series: [{ data: bandData.value.map(i => i.value) }]
  })
}

// ====== 控制逻辑 ======
function startModel() {
  if (!selectedPort.value) return ElMessage.warning('请选择端口')
  if (collecting.value) return ElMessage.info('正在运行中')
  store.startSse({ port: selectedPort.value })
  collecting.value = true
  ElMessage.success(`已启动 ${selectedPort.value} 的模型分析`)
}

function stopModel() {
  if (!collecting.value) return
  store.stopSse?.()
  collecting.value = false
  ElMessage.info('已停止分析')
}

// ====== 生命周期 ======
onMounted(() => {
  initIndexChart()
  initLevelPie()
  initBandBar()
  watch(() => store.fatigueIndex, updateIndexChart)
  watch(() => store.fatigueLevel, updateLevelPie)
  watch(bandData, updateBandBar)
  window.addEventListener('resize', () => {
    indexChart?.resize()
    levelPieChart?.resize()
    bandBarChart?.resize()
  })
})

onActivated(() => {
  updateIndexChart()
  updateLevelPie()
  updateBandBar()
})
</script>

<template>
  <el-container class="page-container">
    <el-header class="header-bar">
  <div class="header-left">
    <h2>脑电波特征分析</h2>
    <el-tag type="info" size="small">模型特征分析</el-tag>
  </div>

  <div class="header-right">
    <el-select
      v-model="selectedPort"
      placeholder="选择端口"
      size="small"
      class="port-select"
    >
      <el-option
        v-for="p in portList"
        :key="p"
        :label="p"
        :value="p"
      />
    </el-select>
    <el-button type="primary" size="small" @click="startModel" :disabled="collecting">
      开始分析
    </el-button>
    <el-button type="danger" size="small" @click="stopModel" :disabled="!collecting">
      停止
    </el-button>
    <el-button size="small" @click="router.back()">返回</el-button>
  </div>
</el-header>


    <el-main class="main">
      <el-row :gutter="20">
        <el-col :span="8">
          <el-card shadow="hover" class="chart-card">
            <div class="card-title">疲劳指数趋势</div>
            <div id="indexChart" class="chart"></div>
          </el-card>
        </el-col>

        <el-col :span="8">
          <el-card shadow="hover" class="chart-card">
            <div class="card-title">危险情绪分布</div>
            <div id="levelPie" class="chart"></div>
          </el-card>
        </el-col>

        <el-col :span="8">
          <el-card shadow="hover" class="chart-card">
            <div class="card-title">波段功率 (%)</div>
            <div id="bandBar" class="chart"></div>
          </el-card>
        </el-col>
      </el-row>
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
  height: 340px;
}
</style>
