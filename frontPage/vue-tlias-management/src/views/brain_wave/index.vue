<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useEegStore } from '@/stores/eeg'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

import {
  ElContainer, ElHeader, ElMain,
  ElRow, ElCol, ElCard, ElStatistic, ElDivider, ElButton, ElSelect, ElOption
} from 'element-plus'

// 路由 & store
const router = useRouter()
const store  = useEegStore()

// ---- 端口选择逻辑 ----
const portList = ref([])
const selectedPort = ref('')

// 初始化时从后端获取端口列表
onMounted(async () => {
  try {
    const res = await request.get('/api/ports')   // 后端提供接口
    portList.value = res || []
  } catch (e) {
    portList.value = ['COM1', 'COM2', 'COM3'] // fallback
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
    xAxis: { type: 'category', data: [], boundaryGap: false },
    yAxis: { type: 'value', min: 'dataMin', max: 'dataMax' },
    series: [{
      name: '脑电波',
      type: 'line',
      data: [],
      showSymbol: false,
      sampling: 'lttb',
      lineStyle: { width: 1 },
      animation: false
    }],
    grid: { left: '5%', right: '5%', bottom: '10%' }
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

// ---- 采集控制 ----
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
    <el-header class="header">
      <h2>脑电波数据采集</h2>
      <el-divider />
      <div class="header-info">
        <span>选择端口：</span>
        <el-select v-model="selectedPort" placeholder="请选择端口" size="small" style="width:160px;">
          <el-option v-for="p in portList" :key="p" :label="p" :value="p" />
        </el-select>
        <el-button type="primary" size="small" @click="startCollect">开始采集</el-button>
        <el-button size="small" type="danger" @click="stopCollect">停止</el-button>
        <el-button size="small" @click="router.back()">返回</el-button>
      </div>
    </el-header>

    <el-main class="main">
      <el-row :gutter="20">
        <!-- 折线图 -->
        <el-col :span="16">
          <el-card shadow="hover" class="chart-card">
            <div class="chart-title">实时脑电波曲线</div>
            <div ref="lineChartRef" class="line-chart"></div>
          </el-card>
        </el-col>

        <!-- 右侧数据 -->
        <el-col :span="8">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-title">疲劳指数</div>
            <el-statistic :value="store.fatigueIndex" suffix="%" />
            <div class="level">等级：<strong>{{ store.fatigueLevel }}</strong></div>
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
.page-container { height:100%; background:#f5f7fa; }
.header {
  background:#fff; padding:16px 24px;
  border-bottom:1px solid #ebeef5;
  display:flex; flex-direction:column;
}
.header-info {
  display:flex; align-items:center; gap:10px; margin-top:10px;
}
.line-chart { width:100%; height:400px; }
.stat-card { text-align:center; }
.band { font-size:13px; color:#666; }
.value { font-size:15px; font-weight:600; }
</style>
