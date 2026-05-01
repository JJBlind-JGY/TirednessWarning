<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useEegStore } from '@/stores/eeg'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

import {
  ElContainer, ElHeader, ElMain,
  ElRow, ElCol, ElCard, ElStatistic,
  ElDivider, ElButton, ElSelect, ElOption, ElTag
} from 'element-plus'

// 路由 & store
const router = useRouter()
const store  = useEegStore()

// ---- 端口选择逻辑 ----
const portList = ref([])
const selectedPort = ref('COM1')

// 初始化时从后端获取端口列表
onMounted(async () => {
  try {
    const res = await request.get('/eeg/ports')
    portList.value = res?.data || ['COM1', 'COM2', 'COM3']
     // ✅ 如果默认值不在返回的列表中，也自动补上 COM1
    if (!portList.value.includes('COM1')) {
      portList.value.unshift('COM1')
    }
  } catch (e) {
    console.error('加载端口失败', e)
    portList.value = ['COM1', 'COM2', 'COM3']
    store.startSse({ mode: 'realtime', workerId, port: selectedPort.value })
  }
})

// ---- 折线图定义 ----
const lineChartRef    = ref(null)
let lineChartInstance = null
const rawWaveCache    = ref([])
const MAX_POINTS      = 512

function initLineChart() {
  if (!lineChartRef.value) return
  lineChartInstance = echarts.init(lineChartRef.value)
  lineChartInstance.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: '5%', right: '5%', bottom: '10%', top: '10%' },
    xAxis: { type: 'category', boundaryGap: false, data: [] },
    yAxis: { type: 'value', min: 'dataMin', max: 'dataMax' },
    series: [{
      name: '脑电波',
      type: 'line',
      smooth: true,
      data: [],
      showSymbol: false,
      lineStyle: { width: 1.5, color: '#3a8ee6' },
      areaStyle: { opacity: 0.1, color: '#3a8ee6' },
    }],
  })
}

function updateLineChart(newSamples) {
  if (!lineChartInstance) return
  ;(Array.isArray(newSamples) ? newSamples : [newSamples])
    .forEach(v => rawWaveCache.value.push(v))
  if (rawWaveCache.value.length > MAX_POINTS) {
    rawWaveCache.value.splice(0, rawWaveCache.value.length - MAX_POINTS)
  }
  lineChartInstance.setOption({
    xAxis: { data: rawWaveCache.value.map((_, i) => i) },
    series: [{ data: rawWaveCache.value }]
  }, false, true)
}

// ---- 控制逻辑 ----
const collecting = ref(false)

function startCollect() {
  if (!selectedPort.value) {
    ElMessage.warning('请选择端口')
    return
  }
  if (collecting.value) {
    ElMessage.info('采集中，请勿重复启动')
    return
  }
  store.startSse({ port: selectedPort.value })
  collecting.value = true
  ElMessage.success(`已启动端口 ${selectedPort.value} 的数据采集`)
}

function stopCollect() {
  if (!collecting.value) return
  store.stopSse?.()
  collecting.value = false
  ElMessage.info('已停止采集')
}

// ---- 波段展示 ----
const bandData = computed(() => [
  { name: 'Delta', value: store.deltaPower },
  { name: 'Theta', value: store.thetaPower },
  { name: 'Alpha', value: store.alphaPower },
  { name: 'Beta',  value: store.betaPower }
])

// ---- 生命周期 ----
onMounted(() => {
  initLineChart()
  watch(() => store.rawWave, val => updateLineChart(val))
  window.addEventListener('resize', () => lineChartInstance?.resize())
})
</script>

<template>
  <el-container class="page-container">
    <!-- 顶部控制栏 -->
    <el-header class="header-bar">
      <div class="header-left">
        <h2>脑电波数据采集系统</h2>
        <el-tag type="info" size="small">实时监控</el-tag>
      </div>

      <div class="header-right">
        <el-select v-model="selectedPort" placeholder="选择端口" size="small" class="port-select">
          <el-option v-for="p in portList" :key="p" :label="p" :value="p" />
        </el-select>
        <el-button type="primary" size="small" @click="startCollect" :disabled="collecting">开始</el-button>
        <el-button type="danger" size="small" @click="stopCollect" :disabled="!collecting">停止</el-button>
        <el-button size="small" @click="router.back()">返回</el-button>
      </div>
    </el-header>

    <el-main class="main">
      <el-row :gutter="20">
        <!-- 左侧图表 -->
        <el-col :span="16">
          <el-card shadow="hover" class="chart-card">
            <div class="chart-title">实时脑电波曲线</div>
            <div ref="lineChartRef" class="line-chart"></div>
          </el-card>
        </el-col>

        <!-- 右侧数据 -->
        <el-col :span="8">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-title">脑电波指数</div>
            <el-statistic
              :value="store.fatigueIndex"
              suffix="%"
              :precision="0"
              value-style="font-size:32px;font-weight:bold;color:#409EFF"
            />
            <div class="level">
              当前等级：
              <el-tag
                :type="store.fatigueLevel==='疲劳' ? 'danger' : (store.fatigueLevel==='紧张' ? 'warning' : 'success')"
              >
                {{ store.fatigueLevel || '无' }}
              </el-tag>
            </div>

            <el-divider />
            <div class="dist-title">波段分布 (%)</div>
            <el-row class="dist-row">
              <el-col :span="12" v-for="item in bandData" :key="item.name" class="dist-col">
                <div class="band">{{ item.name }}</div>
                <div class="value">{{ item.value.toFixed(1) }}%</div>
              </el-col>
            </el-row>
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
  background: #ffffff;
  padding: 14px 24px;
  border-bottom: 1px solid #dcdfe6;
  box-shadow: 0 2px 6px rgba(0,0,0,0.05);
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

/* 图表卡片 */
.chart-card {
  padding: 16px;
  border-radius: 10px;
}
.chart-title {
  font-weight: 600;
  font-size: 16px;
  color: #333;
  margin-bottom: 10px;
}
.line-chart {
  width: 100%;
  height: 400px;
}

/* 指标卡片 */
.stat-card {
  text-align: center;
  border-radius: 10px;
}
.stat-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
}
.level {
  margin-top: 10px;
  font-size: 14px;
}
.dist-row {
  text-align: center;
  margin-top: 10px;
}
.band {
  font-size: 13px;
  color: #666;
}
.value {
  font-size: 15px;
  font-weight: 600;
  color: #409EFF;
}
</style>
