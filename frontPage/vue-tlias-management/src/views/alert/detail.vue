<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMonitorCenter } from './useMonitorCenter'

const route = useRoute()
const router = useRouter()

const {
  state,
  DEVICE_OPTIONS,
  CAMERA_OPTIONS,
  useMonitorCenterPage,
  updateBindingPerson,
  updateBindingDevice,
  updateBindingCamera,
  persistBindings,
  getBindingById,
  getDeviceLabel,
  getCameraLabel,
  getDisplayEmotion,
  getAccessText,
  getEegStatusLabel,
  getFaceStatusLabel,
  formatShortTime,
  setChartRef,
  getWarningText,
  getAlertType
} = useMonitorCenter()

useMonitorCenterPage()

const binding = computed(() => getBindingById(route.params.id))
const selectedCamera = computed(() => CAMERA_OPTIONS.find((item) => item.id === binding.value?.faceChannelId))
const faceStreamUrl = computed(() => selectedCamera.value?.streamUrl || '')

function handlePersonChange() { if (binding.value) { updateBindingPerson(binding.value); persistBindings() } }
function handleDeviceChange() { if (binding.value) updateBindingDevice(binding.value) }
function handleFaceChannelChange() { if (binding.value) updateBindingCamera(binding.value) }
function getPortText(workerId) { return DEVICE_OPTIONS.find((item) => item.value === workerId)?.port || '--' }
function formatBand(value) { return `${Number(value || 0).toFixed(1)}%` }
function formatFaceScore(value) { if (value == null || value === '--' || value === '') return '--'; const numeric = Number.parseFloat(String(value).replace('%', '')); return Number.isFinite(numeric) ? `${numeric.toFixed(1)}%` : String(value) }
function latestTime(bindingValue) { const value = bindingValue?.analysisTime || bindingValue?.lastValidFaceAt; return value ? formatShortTime(value) : '--:--:--' }
function adviceText(bindingValue) { if (!bindingValue?.lastValidEegAt && !bindingValue?.lastValidFaceAt) return '等待有效数据'; return bindingValue.emotion === 'normal' ? '继续监测' : '建议关注' }
</script>

<template>
  <div v-if="binding" class="detail-page">
    <section class="top-bar">
      <div>
        <div class="kicker">单设备详情</div>
        <h1>{{ binding.personName || '未绑定人员' }} / {{ getDeviceLabel(binding.workerId) }} / {{ getCameraLabel(binding.faceChannelId) }}</h1>
        <p>展示实时视频、脑电波形、波段占比、面部识别结果和综合状态。</p>
      </div>
      <div class="top-actions">
        <el-tag :type="getAlertType(binding)" effect="dark">{{ getWarningText(binding) }}</el-tag>
        <el-button type="primary" plain @click="router.push(`/alert/device/${binding.id}/eeg`)">脑电界面</el-button>
        <el-button type="primary" plain @click="router.push(`/alert/device/${binding.id}/face`)">面部界面</el-button>
        <el-button @click="router.push('/alert')">返回总界面</el-button>
      </div>
    </section>

    <section class="base-panel">
      <div class="config-grid">
        <el-form-item label="人员">
          <el-select v-model="binding.personId" placeholder="选择人员" filterable @change="handlePersonChange">
            <el-option v-for="person in state.personnelOptions" :key="person.id" :label="`${person.name} / ${person.uid}`" :value="person.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="脑电设备">
          <el-select v-model="binding.workerId" placeholder="选择脑电设备" @change="handleDeviceChange">
            <el-option v-for="device in DEVICE_OPTIONS" :key="device.value" :label="device.label" :value="device.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="岗位">
          <el-input :model-value="binding.personType" disabled placeholder="未配置" />
        </el-form-item>
        <el-form-item label="摄像头设备">
          <el-select v-model="binding.faceChannelId" placeholder="选择摄像头" @change="handleFaceChannelChange">
            <el-option v-for="camera in CAMERA_OPTIONS" :key="camera.id" :label="camera.label" :value="camera.id" />
          </el-select>
        </el-form-item>
      </div>

      <div class="quick-grid">
        <div class="quick-card"><span>设备端口</span><strong>{{ getPortText(binding.workerId) }}</strong></div>
        <div class="quick-card"><span>接入状态</span><strong>{{ getAccessText(binding) }}</strong></div>
        <div class="quick-card"><span>综合状态</span><strong>{{ getDisplayEmotion(binding) }}</strong></div>
        <div class="quick-card"><span>最近时间</span><strong>{{ latestTime(binding) }}</strong></div>
      </div>
    </section>

    <section class="content-grid">
      <article class="panel video-panel">
        <div class="panel-head">
          <h3>微表情视频与识别</h3>
          <el-tag :type="binding.faceConnected ? 'success' : 'info'">{{ getFaceStatusLabel(binding) }}</el-tag>
        </div>
        <div v-if="faceStreamUrl" class="video-box"><iframe class="result-video" :src="faceStreamUrl" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe></div>
        <el-image v-else-if="binding.faceImageUrl" :src="binding.faceImageUrl" fit="contain" class="result-image" />
        <div v-else class="empty-box">等待视频流</div>
        <div class="result-grid">
          <div class="metric-box"><span>面部接入状态</span><strong>{{ getFaceStatusLabel(binding) }}</strong></div>
          <div class="metric-box"><span>视频接入通道</span><strong>{{ getCameraLabel(binding.faceChannelId) }}</strong></div>
          <div class="metric-box"><span>视频更新时间</span><strong>{{ binding.lastValidFaceAt ? formatShortTime(binding.lastValidFaceAt) : '--:--:--' }}</strong></div>
          <div class="metric-box"><span>辅助信号状态</span><strong>{{ getFaceStatusLabel(binding) }}</strong></div>
        </div>
      </article>

      <article class="panel eeg-panel">
        <div class="panel-head">
          <h3>脑电波形与波段</h3>
          <div class="eeg-actions">
            <el-tag :type="binding.eegRunning ? 'success' : 'info'">{{ getEegStatusLabel(binding) }}</el-tag>
          </div>
        </div>
        <div class="signal-strip">
          <div class="signal-item"><span>脑电状态</span><strong>{{ getEegStatusLabel(binding) }}</strong></div>
          <div class="signal-item"><span>波形更新状态</span><strong>{{ binding.rawWaveBuffer.length ? '实时更新' : '等待波形' }}</strong></div>
        </div>
        <div class="chart-wrap">
          <div :ref="setChartRef(binding.id)" class="eeg-chart"></div>
          <div v-if="!binding.rawWaveBuffer.length" class="chart-empty">自动检测脑电设备状态</div>
        </div>
        <div class="band-grid">
          <div class="metric-box"><span>Theta 占比</span><strong>{{ formatBand(binding.bandSnapshot.theta) }}</strong></div>
          <div class="metric-box"><span>Alpha 占比</span><strong>{{ formatBand(binding.bandSnapshot.alpha) }}</strong></div>
          <div class="metric-box"><span>Beta 占比</span><strong>{{ formatBand(binding.bandSnapshot.beta) }}</strong></div>
          <div class="metric-box"><span>Delta 占比</span><strong>{{ formatBand(binding.bandSnapshot.delta) }}</strong></div>
          <div class="metric-box"><span>Gamma 占比</span><strong>{{ formatBand(binding.bandSnapshot.gamma) }}</strong></div>
        </div>
      </article>

      <article class="panel warning-panel">
        <div class="panel-head">
          <h3>状态预警</h3>
          <el-tag :type="getAlertType(binding)" effect="dark">{{ getWarningText(binding) }}</el-tag>
        </div>
        <el-alert :type="getAlertType(binding)" :closable="false" show-icon :title="getWarningText(binding)" />
        <div class="warning-grid">
          <div class="metric-box"><span>当前状态</span><strong>{{ getDisplayEmotion(binding) }}</strong></div>
          <div class="metric-box"><span>接入状态</span><strong>{{ getAccessText(binding) }}</strong></div>
          <div class="metric-box"><span>视频通道</span><strong>{{ getFaceStatusLabel(binding) }}</strong></div>
          <div class="metric-box"><span>脑电通道</span><strong>{{ getEegStatusLabel(binding) }}</strong></div>
          <div class="metric-box"><span>最近时间</span><strong>{{ latestTime(binding) }}</strong></div>
          <div class="metric-box"><span>处理建议</span><strong>{{ adviceText(binding) }}</strong></div>
        </div>
      </article>
    </section>
  </div>
  <div v-else class="empty-wrap"><el-empty description="未找到设备详情"><el-button type="primary" @click="router.push('/alert')">返回总界面</el-button></el-empty></div>
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
.result-video { width: 100%; height: 100%; border: 0; }
.result-image { width: 100%; height: 320px; border-radius: 8px; background: #f5f5f5; }
.empty-box { display: flex; align-items: center; justify-content: center; color: #dbeafe; }
.result-grid, .signal-strip, .warning-grid, .band-grid { margin-top: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.chart-wrap { position: relative; margin-top: 16px; min-height: 320px; border-radius: 8px; background: #fbfeff; border: 1px solid #e4edf2; }
.eeg-chart { height: 320px; width: 100%; }
.chart-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #7b8a97; pointer-events: none; }
.empty-wrap { min-height: 100%; display: flex; align-items: center; justify-content: center; }
@media (max-width: 1440px) { .content-grid { grid-template-columns: 1fr; } .config-grid, .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 960px) { .detail-page { padding: 16px; } .top-bar, .top-actions { flex-direction: column; align-items: flex-start; } .config-grid, .quick-grid, .result-grid, .signal-strip, .warning-grid, .band-grid { grid-template-columns: 1fr; } }
</style>
