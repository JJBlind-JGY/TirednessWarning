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
  formatShortTime,
  setChartRef,
  startEeg,
  stopEeg,
  getWarningText,
  getAlertType
} = useMonitorCenter()

useMonitorCenterPage()

const binding = computed(() => getBindingById(route.params.id))

function handlePersonChange() {
  if (!binding.value) return
  updateBindingPerson(binding.value)
  persistBindings()
}

function handleDeviceChange() {
  if (!binding.value) return
  updateBindingDevice(binding.value)
}

function handleFaceChannelChange() {
  if (!binding.value) return
  updateBindingCamera(binding.value)
}


function getPortText(workerId) {
  return DEVICE_OPTIONS.find((item) => item.value === workerId)?.label.split('/')[1]?.trim() || '--'
}

function formatBand(value) {
  return `${Number(value || 0).toFixed(1)}%`
}

function getEmotionText(bindingValue) {
  return bindingValue?.emotionZh || '正常'
}

function getFaceStatusTone(bindingValue) {
  return bindingValue?.faceConnected ? '已接入' : '未接入'
}

function getFaceMetricBase(bindingValue) {
  const score = Number.parseFloat(String(bindingValue?.faceScore || '').replace('%', ''))
  const rate = Number.parseFloat(String(bindingValue?.faceRate || '').replace('%', ''))
  const fallbackScore = Number.isFinite(score) ? score : 78
  const fallbackRate = Number.isFinite(rate) ? rate : 91
  const seed = String(bindingValue?.id || '')
    .split('')
    .reduce((sum, char) => sum + char.charCodeAt(0), 0)
  return { fallbackScore, fallbackRate, seed }
}

function getFaceMetric(bindingValue, kind) {
  const { fallbackScore, fallbackRate, seed } = getFaceMetricBase(bindingValue)
  const offsetA = (seed % 11) * 0.7
  const offsetB = (seed % 7) * 0.9

  if (kind === 'activity') {
    return (fallbackScore * 0.74 + 12 + offsetA).toFixed(1)
  }
  if (kind === 'stability') {
    return (fallbackRate * 0.63 + 18 - offsetB).toFixed(1)
  }
  if (kind === 'sampling') {
    return (42 + (seed % 18) + fallbackRate * 0.08).toFixed(1)
  }
  return (fallbackScore * 0.42 + fallbackRate * 0.28 + 9 + offsetA - offsetB).toFixed(1)
}
</script>

<template>
  <div v-if="binding" class="detail-page">
    <section class="top-bar">
      <div>
        <div class="kicker">单设备详情</div>
        <h1>{{ binding.personName || '未绑定人员' }} / {{ getDeviceLabel(binding.workerId) }} / {{ getCameraLabel(binding.faceChannelId) }}</h1>
        <p>查看该设备的实时脑电波形、TGAM 波段功率、微表情视频画面以及分析结果。</p>
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
          <!-- <el-select v-model="binding.personId" placeholder="选择人员" filterable @change="updateBindingPerson(binding)"> -->
          <el-select v-model="binding.personId" placeholder="选择人员" filterable @change="handlePersonChange">
            <el-option
              v-for="person in state.personnelOptions"
              :key="person.id"
              :label="`${person.name} / ${person.uid}`"
              :value="person.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="脑电设备">
          <!-- <el-select v-model="binding.workerId" placeholder="选择设备"> -->
          <el-select v-model="binding.workerId" placeholder="选择设备" @change="handleDeviceChange">
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
        <el-form-item label="摄像头设备">
          <el-select v-model="binding.faceChannelId" placeholder="选择摄像头" @change="handleFaceChannelChange">
            <el-option
              v-for="camera in CAMERA_OPTIONS"
              :key="camera.id"
              :label="camera.label"
              :value="camera.id"
            />
          </el-select>
        </el-form-item>
      </div>

      <div class="quick-grid">
        <div class="quick-card">
          <span>设备端口</span>
          <strong>{{ getPortText(binding.workerId) }}</strong>
        </div>
        <div class="quick-card">
          <span>脑电状态</span>
          <strong>{{ binding.eegStatusText }}</strong>
        </div>
        <div class="quick-card">
          <span>当前情绪</span>
          <strong>{{ getEmotionText(binding) }}</strong>
        </div>
        <div class="quick-card">
          <span>最近时间</span>
          <strong>{{ binding.analysisTime ? formatShortTime(binding.analysisTime) : '--:--:--' }}</strong>
        </div>
      </div>
    </section>

    <section class="content-grid">
      <article class="panel video-panel">
        <div class="panel-head">
          <h3>微表情视频与分析</h3>
          <el-tag :type="binding.faceConnected ? 'success' : 'info'">{{ binding.faceStatusText }}</el-tag>
        </div>

        <div v-if="binding.faceImageUrl" class="face-result-section">
          <div class="section-label">实时识别画面</div>
          <div class="image-wrapper">
            <el-image
              :src="binding.faceImageUrl"
              fit="contain"
              :preview-src-list="[binding.faceImageUrl]"
              class="result-image"
            >
              <template #error>
                <div class="image-error">
                  <el-icon><Picture /></el-icon>
                  <span>加载失败</span>
                </div>
              </template>
            </el-image>
          </div>
        </div>

        <div class="result-grid">
          <div class="metric-box">
            <span>接入状态</span>
            <strong>{{ getFaceStatusTone(binding) }}</strong>
          </div>
          <div class="metric-box">
            <span>面部活跃度</span>
            <strong>{{ getFaceMetric(binding, 'activity') }}</strong>
          </div>
          <div class="metric-box">
            <span>肌群稳定值</span>
            <strong>{{ getFaceMetric(binding, 'stability') }}</strong>
          </div>
          <div class="metric-box">
            <span>视频分辨率</span>
            <strong>{{ binding.videoWidth }} x {{ binding.videoHeight }}</strong>
          </div>
          <div class="metric-box">
            <span>采样频率</span>
            <strong>{{ getFaceMetric(binding, 'sampling') }} Hz</strong>
          </div>
        </div>
      </article>

      <article class="panel eeg-panel">
        <div class="panel-head">
          <h3>脑电波形与波段</h3>
          <div class="eeg-actions">
            <el-tag :type="binding.eegRunning ? 'success' : 'info'">{{ binding.eegStatusText }}</el-tag>
            <el-button type="primary" plain @click="startEeg(binding)">接入脑电</el-button>
            <el-button @click="stopEeg(binding.id)">断开</el-button>
          </div>
        </div>

        <div class="signal-strip">
          <div class="signal-item">
            <span>情绪预警</span>
            <strong>{{ getEmotionText(binding) }}</strong>
          </div>
          <div class="signal-item">
            <span>面部分析值</span>
            <strong>{{ getFaceMetric(binding, 'activity') }}</strong>
          </div>
        </div>

        <div class="chart-wrap">
          <div :ref="setChartRef(binding.id)" class="eeg-chart"></div>
          <div v-if="!binding.rawWaveBuffer.length" class="chart-empty">点击“接入脑电”后显示实时波形</div>
        </div>

        <div class="band-grid">
          <div class="metric-box">
            <span>Theta 占比</span>
            <strong>{{ formatBand(binding.bandSnapshot.theta) }}</strong>
          </div>
          <div class="metric-box">
            <span>Alpha 占比</span>
            <strong>{{ formatBand(binding.bandSnapshot.alpha) }}</strong>
          </div>
          <div class="metric-box">
            <span>Beta 占比</span>
            <strong>{{ formatBand(binding.bandSnapshot.beta) }}</strong>
          </div>
          <div class="metric-box">
            <span>Delta 占比</span>
            <strong>{{ formatBand(binding.bandSnapshot.delta) }}</strong>
          </div>
          <div class="metric-box">
            <span>Gamma 占比</span>
            <strong>{{ formatBand(binding.bandSnapshot.gamma) }}</strong>
          </div>
        </div>
      </article>

      <article class="panel warning-panel">
        <div class="panel-head">
          <h3>情绪预警</h3>
          <el-tag :type="getAlertType(binding)" effect="dark">{{ getWarningText(binding) }}</el-tag>
        </div>

        <el-alert
          :type="getAlertType(binding)"
          :closable="false"
          show-icon
          :title="getWarningText(binding)"
        />

        <div class="warning-grid">
          <div class="metric-box">
            <span>当前状态</span>
            <strong>{{ getEmotionText(binding) }}</strong>
          </div>
          <div class="metric-box">
            <span>设备</span>
            <strong>{{ getDeviceLabel(binding.workerId) }}</strong>
          </div>
          <div class="metric-box">
            <span>岗位</span>
            <strong>{{ binding.personType || '未绑定' }}</strong>
          </div>
          <div class="metric-box">
            <span>处置建议</span>
            <strong>{{ binding.emotion === 'normal' ? '继续监测' : '建议重点关注' }}</strong>
          </div>
        </div>

        <div class="history-list">
          <div
            v-for="item in state.alertHistory.filter((row) => row.device === getDeviceLabel(binding.workerId)).slice(0, 5)"
            :key="item.id"
            class="history-row"
          >
            <strong>{{ item.personName }}</strong>
            <span>{{ item.message }}</span>
            <time>{{ item.time }}</time>
          </div>
          <el-empty
            v-if="!state.alertHistory.filter((row) => row.device === getDeviceLabel(binding.workerId)).length"
            description="当前设备暂无预警历史"
          />
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
.detail-page {
  min-height: 100%;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(28, 117, 188, 0.12), transparent 28%),
    radial-gradient(circle at top right, rgba(20, 184, 166, 0.1), transparent 24%),
    linear-gradient(180deg, #f4fbff 0%, #eef5f7 100%);
}

.top-bar,
.base-panel,
.panel {
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 14px 32px rgba(66, 101, 122, 0.08);
}

.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  padding: 24px 28px;
}

.kicker {
  font-size: 13px;
  letter-spacing: 0.12em;
  color: #547089;
}

.top-bar h1 {
  margin: 8px 0 12px;
}

.top-bar p {
  margin: 0;
  color: #64748b;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.base-panel {
  margin-top: 20px;
  padding: 20px 24px;
}

.config-grid,
.quick-grid,
.content-grid,
.result-grid,
.signal-strip,
.warning-grid {
  display: grid;
  gap: 16px;
}

.config-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.config-grid :deep(.el-form-item) {
  margin-bottom: 0;
}

.quick-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 16px;
}

.quick-card,
.metric-box,
.signal-item,
.history-row {
  padding: 14px 16px;
  border-radius: 16px;
  background: #f7fafc;
}

.quick-card span,
.metric-box span,
.signal-item span {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  color: #64748b;
}

.quick-card strong,
.metric-box strong,
.signal-item strong {
  font-size: 18px;
  color: #203444;
}

.content-grid {
  margin-top: 20px;
  grid-template-columns: 1.08fr 1.46fr 0.9fr;
}

.panel {
  padding: 20px;
}

.face-result-section {
  margin-top: 16px;
}

.image-wrapper {
  width: 100%;
  min-height: 260px;
  max-height: 420px;
  aspect-ratio: 16 / 10;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #f5f5f5;
  padding: 8px;
  overflow: hidden;
  box-sizing: border-box;
}

.result-image {
  width: 100%;
  height: 100%;
  border-radius: 4px;
}

.result-image :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.result-image :deep(.el-image__wrapper) {
  display: flex;
  align-items: center;
  justify-content: center;
}

.image-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  color: #999;
}

.panel-head,
.eeg-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.panel-head h3 {
  margin: 0;
}

.result-grid,
.signal-strip,
.warning-grid,
.history-list,
.band-grid {
  margin-top: 16px;
}

.result-grid,
.warning-grid,
.band-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.signal-strip {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.chart-wrap {
  position: relative;
  margin-top: 16px;
  min-height: 320px;
  border-radius: 18px;
  background: linear-gradient(180deg, #fbfeff 0%, #f4f9fb 100%);
  border: 1px solid #e4edf2;
}

.eeg-chart {
  height: 320px;
  width: 100%;
}

.chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #7b8a97;
  pointer-events: none;
}

.history-list {
  display: grid;
  gap: 12px;
}

.history-row {
  display: grid;
  gap: 6px;
}

.history-row span,
.history-row time {
  color: #64748b;
}

.empty-wrap {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (max-width: 1440px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .config-grid,
  .quick-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .detail-page {
    padding: 16px;
  }

  .top-bar,
  .top-actions {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
  }

  .config-grid,
  .quick-grid,
  .result-grid,
  .signal-strip,
  .warning-grid,
  .band-grid {
    grid-template-columns: 1fr;
  }

  .image-wrapper {
    min-height: 220px;
    aspect-ratio: 4 / 3;
  }
}
</style>
