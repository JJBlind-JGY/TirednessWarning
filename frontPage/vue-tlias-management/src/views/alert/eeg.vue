<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMonitorCenter } from './useMonitorCenter'

const route = useRoute()
const router = useRouter()

const {
  state,
  DEVICE_OPTIONS,
  useMonitorCenterPage,
  updateBindingPerson,
  updateBindingDevice,
  getBindingById,
  getDeviceLabel,
  formatShortTime,
  setChartRef,
  setBandChartRef,
  startEeg,
  stopEeg,
  getWarningText,
  getAlertType
} = useMonitorCenter()

useMonitorCenterPage()

const selectedBindingId = computed(() => route.params.id || route.query.binding || state.bindings[0]?.id || '')
const binding = computed(() => getBindingById(selectedBindingId.value))

function getPortText(workerId) {
  return DEVICE_OPTIONS.find((item) => item.value === workerId)?.label.split('/')[1]?.trim() || '--'
}

function formatBand(value) {
  return `${Number(value || 0).toFixed(1)}%`
}

function formatIndex(value) {
  return Number(value || 0).toFixed(1)
}

function openBinding(bindingId) {
  if (!bindingId) return
  if (route.params.id) {
    router.push(`/alert/device/${bindingId}/eeg`)
    return
  }
  router.push({ name: 'alertEegHome', query: { binding: bindingId } })
}
</script>

<template>
  <div v-if="binding" class="eeg-page">
    <section class="hero-panel">
      <div>
        <div class="hero-kicker">EEG LAB</div>
        <h1>{{ binding.personName || '未绑定人员' }} / {{ getDeviceLabel(binding.workerId) }}</h1>
  
      </div>
      <div class="hero-actions">
        <el-tag :type="getAlertType(binding)" effect="dark">{{ getWarningText(binding) }}</el-tag>
        <el-button type="primary" plain @click="startEeg(binding)">接入脑电</el-button>
        <el-button @click="stopEeg(binding.id)">断开</el-button>
        <el-button @click="router.push(`/alert/device/${binding.id}`)">返回详情</el-button>
      </div>
    </section>

    <section class="base-panel">
      <div v-if="state.bindings.length > 1" class="binding-switcher">
        <el-button
          v-for="item in state.bindings"
          :key="item.id"
          :type="item.id === binding.id ? 'primary' : 'default'"
          plain
          @click="openBinding(item.id)"
        >
          {{ item.personName || getDeviceLabel(item.workerId) }}
        </el-button>
      </div>

      <div class="config-grid">
        <el-form-item label="人员">
          <el-select v-model="binding.personId" placeholder="选择人员" filterable @change="updateBindingPerson(binding)">
            <el-option
              v-for="person in state.personnelOptions"
              :key="person.id"
              :label="`${person.name} / ${person.uid}`"
              :value="person.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="脑电设备">
          <el-select v-model="binding.workerId" placeholder="选择设备" @change="updateBindingDevice(binding)">
            <el-option
              v-for="device in DEVICE_OPTIONS"
              :key="device.value"
              :label="device.label"
              :value="device.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="岗位">
          <el-input :model-value="binding.personType" disabled placeholder="自动带出" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input :model-value="getPortText(binding.workerId)" disabled />
        </el-form-item>
      </div>

      <div class="status-grid">
        <div class="status-card">
          <span>脑电状态</span>
          <strong>{{ binding.eegStatusText }}</strong>
        </div>
        <div class="status-card">
          <span>当前情绪</span>
          <strong>{{ binding.emotionZh }}</strong>
        </div>
        <div class="status-card">
          <span>最近时间</span>
          <strong>{{ binding.analysisTime ? formatShortTime(binding.analysisTime) : '--:--:--' }}</strong>
        </div>
        <div class="status-card">
          <span>预警信息</span>
          <strong>{{ getWarningText(binding) }}</strong>
        </div>
      </div>
    </section>

    <section class="visual-grid">
      <article class="panel wave-panel">
        <div class="panel-head">
          <h3>实时脑电波形</h3>
          <el-tag :type="binding.eegRunning ? 'success' : 'info'">{{ binding.eegStatusText }}</el-tag>
        </div>
        <div class="chart-wrap wave-wrap">
          <div :ref="setChartRef(binding.id)" class="eeg-chart"></div>
          <div v-if="!binding.rawWaveBuffer.length" class="chart-empty">接入脑电后显示实时波形</div>
        </div>
      </article>

      <article class="panel radar-panel">
        <div class="panel-head">
          <h3>频段雷达图</h3>
          <span class="panel-note">动态占比可视化</span>
        </div>
        <div class="chart-wrap radar-wrap">
          <div :ref="setBandChartRef(binding.id)" class="band-chart"></div>
        </div>
      </article>
    </section>

    <section class="metric-grid">
      <article class="panel">
        <div class="panel-head">
          <h3>频段占比</h3>
        </div>
        <div class="band-grid">
          <div class="metric-card"><span>Delta</span><strong>{{ formatBand(binding.bandSnapshot.delta) }}</strong></div>
          <div class="metric-card"><span>Theta</span><strong>{{ formatBand(binding.bandSnapshot.theta) }}</strong></div>
          <div class="metric-card"><span>Alpha</span><strong>{{ formatBand(binding.bandSnapshot.alpha) }}</strong></div>
          <div class="metric-card"><span>Beta</span><strong>{{ formatBand(binding.bandSnapshot.beta) }}</strong></div>
          <div class="metric-card"><span>Gamma</span><strong>{{ formatBand(binding.bandSnapshot.gamma) }}</strong></div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head">
          <h3>风险指标</h3>
        </div>
        <div class="band-grid">
          <div class="metric-card"><span>焦虑指数</span><strong>{{ formatIndex(binding.indices.anxiety_idx) }}</strong></div>
          <div class="metric-card"><span>紧张指数</span><strong>{{ formatIndex(binding.indices.stress_idx) }}</strong></div>
          <div class="metric-card"><span>疲劳指数</span><strong>{{ formatIndex(binding.indices.fatigue_idx) }}</strong></div>
          <div class="metric-card"><span>虚弱指数</span><strong>{{ formatIndex(binding.indices.weakness_idx) }}</strong></div>
        </div>
      </article>
    </section>
  </div>

  <div v-else class="empty-wrap">
    <el-empty description="未找到该设备卡片">
      <el-button type="primary" @click="router.push('/alert')">返回总界面</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
.eeg-page {
  min-height: 100%;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.16), transparent 30%),
    radial-gradient(circle at top right, rgba(20, 184, 166, 0.1), transparent 22%),
    linear-gradient(180deg, #eff8f8 0%, #edf4f5 100%);
}

.hero-panel,
.base-panel,
.panel {
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 18px 38px rgba(28, 74, 86, 0.1);
}

.hero-panel {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 28px;
}

.hero-kicker {
  font-size: 12px;
  letter-spacing: 0.16em;
  color: #0f766e;
}

.hero-panel h1 {
  margin: 10px 0 12px;
  color: #163446;
}

.hero-panel p {
  margin: 0;
  max-width: 780px;
  line-height: 1.8;
  color: #627887;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 10px;
}

.base-panel,
.panel {
  margin-top: 20px;
  padding: 20px 24px;
}

.config-grid,
.status-grid,
.visual-grid,
.band-grid,
.metric-grid {
  display: grid;
  gap: 16px;
}

.binding-switcher {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.config-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.config-grid :deep(.el-form-item) {
  margin-bottom: 0;
}

.status-grid {
  margin-top: 16px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.status-card,
.metric-card {
  padding: 16px 18px;
  border-radius: 18px;
  background: #f6fbfb;
}

.status-card span,
.metric-card span,
.panel-note {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  color: #68808e;
}

.status-card strong,
.metric-card strong {
  font-size: 18px;
  color: #183548;
}

.visual-grid {
  grid-template-columns: 1.45fr 1fr;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-head h3 {
  margin: 0;
}

.chart-wrap {
  position: relative;
  margin-top: 16px;
  border-radius: 20px;
  overflow: hidden;
  background: linear-gradient(180deg, #fbfefe 0%, #f3fbfb 100%);
  border: 1px solid #dfedef;
}

.wave-wrap {
  min-height: 360px;
}

.radar-wrap {
  min-height: 360px;
}

.eeg-chart,
.band-chart {
  width: 100%;
  height: 360px;
}

.chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6f8795;
}

.metric-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.band-grid {
  margin-top: 16px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.empty-wrap {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (max-width: 1280px) {
  .visual-grid,
  .metric-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .eeg-page {
    padding: 16px;
  }

  .hero-panel,
  .hero-actions {
    flex-direction: column;
    align-items: flex-start;
  }

  .config-grid,
  .status-grid,
  .band-grid {
    grid-template-columns: 1fr;
  }
}
</style>
