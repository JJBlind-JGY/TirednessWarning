<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import { useMonitorCenter } from './useMonitorCenter'
import {
  EEG_FEATURE_EXPLANATIONS,
  getFeatureContributionOption,
  getRadarOption,
  getStateFeatureProfiles,
  getStateHeatmapOption,
  getStateTrendOption,
  hasZFeatureData as hasTimelineZFeatureData
} from './eegVisualHelper'

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
  resetEegBaseline,
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
const eegBaselineResetting = ref(false)
const eegBaselineResetDisabled = computed(() => {
  const current = binding.value
  if (!current || current.workerId == null || !current.eegRunning) return true
  return ['calibrating', 'connecting', 'offline', 'error', 'reconnecting'].includes(current.eegStatus) || eegBaselineResetting.value
})
const selectedCamera = computed(() => CAMERA_OPTIONS.find((item) => item.id === binding.value?.faceChannelId))
const faceStreamUrl = computed(() => selectedCamera.value?.streamUrl || '')
const versionedFaceStreamUrl = computed(() => {
  if (!faceStreamUrl.value) return ''
  const separator = faceStreamUrl.value.includes('?') ? '&' : '?'
  return `${faceStreamUrl.value}${separator}v=${binding.value?.faceStreamVersion || 0}`
})

const eegVisualPage = ref('indices')
const visualHeatmapRef = ref(null)
const visualTrendRef = ref(null)
const visualFeatureRef = ref(null)
const visualRadarRef = ref(null)
let visualHeatmapInstance = null
let visualTrendInstance = null
let visualFeatureInstance = null
let visualRadarInstance = null
const eegVisualTimeline = computed(() => Array.isArray(binding.value?.eegVisualTimeline) ? binding.value.eegVisualTimeline : [])
const eegFeatureWindow = computed(() => Array.isArray(binding.value?.eegFeatureWindow) ? binding.value.eegFeatureWindow : [])
const hasEegVisualData = computed(() => eegVisualTimeline.value.length > 0)
const hasFeatureWindowZFeatureData = computed(() => hasTimelineZFeatureData(eegFeatureWindow.value))
const realtimeFeatureProfiles = computed(() => getStateFeatureProfiles(eegFeatureWindow.value))
const featureExplanations = computed(() => EEG_FEATURE_EXPLANATIONS)
const eegVisualPrompt = computed(() => {
  const status = binding.value?.eegStatus || 'idle'
  const statusText = binding.value?.eegStatusText || getEegStatusLabel(binding.value || {})
  if (status === 'no_contact') return { title: '等待头盔佩戴', text: '脑电设备在线，但当前没有检测到有效佩戴。重新佩戴并产生有效 EEG 后，下方图表会继续显示。' }
  if (status === 'poor_signal') return { title: '脑电信号质量不佳', text: '当前信号不足以展示可靠数值，请调整头盔接触状态。视频和综合预警区域不受影响。' }
  if (status === 'calibrating') return { title: '脑电基线校准中', text: '校准完成并产生有效推理点后，将展示最近 20 秒状态指数；特征详情每满 20 秒刷新一次。' }
  if (status === 'offline' || status === 'error' || status === 'reconnecting') return { title: '脑电连接未就绪', text: statusText || '等待脑电设备重新连接。' }
  if (status === 'online' || binding.value?.eegRunning) return { title: '等待有效 EEG 推理数据', text: '脑电通道已接入，正在等待校准完成或有效推理点。' }
  return { title: '脑电未接入', text: '请选择并接入脑电设备后展示实时状态指数和 20 秒特征详情。' }
})

function handlePersonChange() { if (binding.value) { updateBindingPerson(binding.value); persistBindings() } }
function handleDeviceChange() { if (binding.value) updateBindingDevice(binding.value) }
function handleFaceChannelChange() { if (binding.value) updateBindingCamera(binding.value) }
async function handleResetEegBaseline() {
  if (!binding.value || eegBaselineResetting.value) return
  try {
    await ElMessageBox.confirm(
      '重置后脑电将重新采集约 30 秒基线，期间暂停有效脑电推理。同一脑电设备的其他详情卡片也会同步重新校准。',
      '重置脑电基线',
      { confirmButtonText: '确认重置', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (_) {
    return
  }

  eegBaselineResetting.value = true
  try {
    await resetEegBaseline(binding.value)
    ElMessage.success('已重置脑电基线，正在重新校准')
  } catch (error) {
    ElMessage.error(error?.message || '脑电基线重置失败')
  } finally {
    eegBaselineResetting.value = false
  }
}
function getPortText(workerId) { return DEVICE_OPTIONS.find((item) => item.value === workerId)?.baseUrl || '--' }
function formatFaceScore(value) { if (value == null || value === '--' || value === '') return '--'; const numeric = Number.parseFloat(String(value).replace('%', '')); return Number.isFinite(numeric) ? `${numeric.toFixed(1)}%` : String(value) }
function latestTime(bindingValue) { const value = bindingValue?.analysisTime || bindingValue?.lastValidFaceAt; return value ? formatShortTime(value) : '--:--:--' }
function adviceText(bindingValue) { if (!bindingValue?.lastValidEegAt && !bindingValue?.lastValidFaceAt) return '等待有效数据'; return bindingValue.emotion === 'normal' ? '继续监测' : '建议关注' }
function getRealtimeCursorIndex() { return Math.max(0, eegVisualTimeline.value.length - 1) }
function renderVisualChart(instanceRef, element, option) {
  if (!element || !hasEegVisualData.value) return instanceRef
  let instance = instanceRef
  if (!instance || instance.getDom() !== element) {
    instance?.dispose()
    instance = echarts.init(element)
  }
  instance.setOption(option, true)
  instance.resize()
  return instance
}
function refreshEegVisualCharts() {
  if (!hasEegVisualData.value) {
    visualHeatmapInstance?.clear()
    visualTrendInstance?.clear()
    visualFeatureInstance?.clear()
    visualRadarInstance?.clear()
    return
  }
  visualHeatmapInstance = renderVisualChart(visualHeatmapInstance, visualHeatmapRef.value, getStateHeatmapOption(eegVisualTimeline.value))
  visualTrendInstance = renderVisualChart(visualTrendInstance, visualTrendRef.value, getStateTrendOption(eegVisualTimeline.value, { cursorIndex: getRealtimeCursorIndex(), cursorLabel: '最新秒' }))
  if (hasFeatureWindowZFeatureData.value) {
    visualFeatureInstance = renderVisualChart(visualFeatureInstance, visualFeatureRef.value, getFeatureContributionOption(eegFeatureWindow.value))
    visualRadarInstance = renderVisualChart(visualRadarInstance, visualRadarRef.value, getRadarOption(eegFeatureWindow.value))
  } else {
    visualFeatureInstance?.clear()
    visualRadarInstance?.clear()
  }
}
async function setEegVisualPage(page) {
  eegVisualPage.value = page
  await nextTick()
  refreshEegVisualCharts()
}
function resizeEegVisualCharts() {
  visualHeatmapInstance?.resize()
  visualTrendInstance?.resize()
  visualFeatureInstance?.resize()
  visualRadarInstance?.resize()
}
function disposeEegVisualCharts() {
  visualHeatmapInstance?.dispose()
  visualTrendInstance?.dispose()
  visualFeatureInstance?.dispose()
  visualRadarInstance?.dispose()
  visualHeatmapInstance = null
  visualTrendInstance = null
  visualFeatureInstance = null
  visualRadarInstance = null
}
watch(
  () => [
    binding.value?.eegStatus || '',
    eegVisualTimeline.value.map((item) => item.ts || item.time).join('|'),
    eegFeatureWindow.value.map((item) => item.ts || item.time).join('|')
  ].join('::'),
  async () => {
    await nextTick()
    refreshEegVisualCharts()
  }
)
watch(() => route.params.id, async () => {
  eegVisualPage.value = 'indices'
  disposeEegVisualCharts()
  await nextTick()
  refreshEegVisualCharts()
})
window.addEventListener('resize', resizeEegVisualCharts)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeEegVisualCharts)
  disposeEegVisualCharts()
})
const eyePopupLevel = computed(() => binding.value?.eyePopupLevel || 'warning')
const eyePopupDanger = computed(() => eyePopupLevel.value === 'danger')
const eyePopupTitle = computed(() => eyePopupDanger.value ? '\u7ea2\u8272\u95ed\u773c\u544a\u8b66' : '\u9ec4\u8272\u95ed\u773c\u63d0\u793a')
const eyePopupMessage = computed(() => {
  const personName = binding.value?.personName || '\u5f53\u524d\u4eba\u5458'
  return eyePopupDanger.value
    ? `${personName} \u8fde\u7eed\u95ed\u773c\u5df2\u8d85\u8fc712\u79d2\uff0c\u5df2\u540c\u6b65\u4e3b\u9875\u9762\u544a\u8b66\uff0c\u8bf7\u7acb\u5373\u5173\u6ce8\u3002`
    : `${personName} \u8fde\u7eed\u95ed\u773c\u5df2\u8d85\u8fc76\u79d2\uff0c\u8bf7\u5173\u6ce8\u5f53\u524d\u72b6\u6001\u3002`
})
function closeEyePopup() {
  if (!binding.value) return
  binding.value.eyeDetailPopupActive = false
  binding.value.eyePopupDismissedAt = Date.now()
}
</script>

<template>
  <div v-if="binding" class="detail-page">
    <!-- Eye detection popup is disabled on main; develop keeps the full eye-alert workflow.
    <div v-if="binding.eyeDetailPopupActive" class="eye-alert-mask">
      <section class="eye-alert-card" :class="eyePopupLevel">
        <div class="eye-alert-icon">{{ eyePopupDanger ? '!' : 'i' }}</div>
        <div class="eye-alert-content">
          <strong>{{ eyePopupTitle }}</strong>
          <p>{{ eyePopupMessage }}</p>
          <span>{{ '\u8fde\u7eed\u7741\u773c3\u79d2\u540e\u5c06\u81ea\u52a8\u5173\u95ed\uff0c\u4e5f\u53ef\u624b\u52a8\u5173\u95ed\u3002' }}</span>
        </div>
        <button class="eye-alert-close" type="button" @click="closeEyePopup">{{ '\u5173\u95ed' }}</button>
      </section>
    </div>
    -->
    <section class="top-bar">
      <div>
        <div class="kicker">单设备详情</div>
        <h1>{{ binding.personName || '未绑定人员' }} / {{ getDeviceLabel(binding.workerId) }} / {{ getCameraLabel(binding.faceChannelId) }}</h1>
        <p>展示实时视频、脑电波形、脑电状态指数、面部识别结果和综合状态。</p>
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
        <div class="quick-card"><span>设备地址</span><strong>{{ getPortText(binding.workerId) }}</strong></div>
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
        <div v-if="versionedFaceStreamUrl" class="video-box"><iframe :key="versionedFaceStreamUrl" class="result-video" :src="versionedFaceStreamUrl" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe></div>
        <el-image v-else-if="binding.faceImageUrl" :src="binding.faceImageUrl" fit="contain" class="result-image" />
        <div v-else class="empty-box">等待视频流</div>
        <div class="result-grid">
          <div class="metric-box"><span>面部接入状态</span><strong>{{ getFaceStatusLabel(binding) }}</strong></div>
          <div class="metric-box"><span>视频接入通道</span><strong>{{ getCameraLabel(binding.faceChannelId) }}</strong></div>
          <div class="metric-box"><span>视频更新时间</span><strong>{{ binding.lastValidFaceAt ? formatShortTime(binding.lastValidFaceAt) : '--:--:--' }}</strong></div>
          <div class="metric-box"><span>辅助信号状态</span><strong>{{ getFaceStatusLabel(binding) }}</strong></div>
          <!-- Eye status display is disabled on main; develop keeps this metric.
          <div class="metric-box"><span>{{ '\u95ed\u773c\u72b6\u6001' }}</span><strong>{{ binding.eyeStatusText || '\u7b49\u5f85\u6709\u6548\u4eba\u8138' }}</strong></div>
          -->
        </div>
      </article>

      <article class="panel eeg-panel">
        <div class="panel-head">
          <h3>脑电波形与状态指数</h3>
          <div class="eeg-actions">
            <el-tag :type="binding.eegRunning ? 'success' : 'info'">{{ getEegStatusLabel(binding) }}</el-tag>
            <el-button type="warning" plain :loading="eegBaselineResetting" :disabled="eegBaselineResetDisabled" @click="handleResetEegBaseline">重置脑电基线</el-button>
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
      </article>

      <section class="eeg-visual-section">
        <div class="eeg-visual-head">
          <div>
            <h4>实时脑电推理证据</h4>
            <p>状态指数实时滚动；特征详情直接读取上一段参与融合 voting 的 20 秒 EEG 样本。</p>
          </div>
          <el-button-group class="page-switch">
            <el-button :type="eegVisualPage === 'indices' ? 'primary' : 'default'" @click="setEegVisualPage('indices')">实时状态指数</el-button>
            <el-button :type="eegVisualPage === 'features' ? 'primary' : 'default'" @click="setEegVisualPage('features')">特征详情</el-button>
          </el-button-group>
        </div>
        <div v-if="!hasEegVisualData" class="eeg-visual-empty status-empty">
          <strong>{{ eegVisualPrompt.title }}</strong>
          <span>{{ eegVisualPrompt.text }}</span>
        </div>
        <template v-else>
            <div v-show="eegVisualPage === 'indices'" class="eeg-visual-page">
              <div class="page-note">最近约 20 秒内，每个有效点计算四类状态指数；超过 59 表示该秒出现异常证据，绿色竖线表示最新推理点。</div>
              <div class="visual-grid realtime-index-grid">
                <article class="visual-card">
                  <div class="visual-title"><span>状态指数热力图</span><small>颜色越深，指数越高</small></div>
                  <div ref="visualHeatmapRef" class="mini-chart"></div>
                </article>
                <article class="visual-card">
                  <div class="visual-title"><span>四状态趋势曲线</span><small>红色虚线为阈值 59</small></div>
                  <div ref="visualTrendRef" class="mini-chart"></div>
                </article>
              </div>
            </div>
            <div v-show="eegVisualPage === 'features'" class="eeg-visual-page">
              <div class="page-note">
                <strong>融合窗口 Z-score：</strong>
                <span v-if="hasFeatureWindowZFeatureData">这里展示的是上一段 20 秒融合 voting 中实际参与判定的 EEG 样本；50 表示接近个人基线，70 以上表示对应状态特征明显增强。</span>
                <span v-else>等待算法完成一个 20 秒融合 voting 窗口，或该窗口缺少个人基线 Z-score；状态指数页仍可查看。</span>
              </div>
              <div v-if="hasFeatureWindowZFeatureData" class="visual-grid realtime-feature-grid">
                <article class="visual-card">
                  <div class="visual-title"><span>四状态特征贡献</span><small>越高表示对应状态越明显</small></div>
                  <div ref="visualFeatureRef" class="mini-chart"></div>
                </article>
                <article class="visual-card">
                  <div class="visual-title"><span>四状态轮廓</span><small>观察是否单一方向突出</small></div>
                  <div ref="visualRadarRef" class="mini-chart"></div>
                </article>
                <article class="visual-card evidence-card">
                  <div class="visual-title"><span>脑电特征花瓣图</span><small>花瓣越长表示该组特征越明显</small></div>
                  <div class="flower-chart">
                    <svg class="flower-svg" viewBox="0 0 560 560" aria-hidden="true">
                      <circle class="flower-ring" cx="280" cy="280" r="82"></circle>
                      <circle class="flower-ring" cx="280" cy="280" r="160"></circle>
                      <circle class="flower-ring strong" cx="280" cy="280" r="240"></circle>
                      <text class="flower-axis-label fatigue" x="102" y="104">疲劳特征</text>
                      <text class="flower-axis-label stress" x="394" y="104">紧张特征</text>
                      <text class="flower-axis-label anxiety" x="392" y="468">焦虑特征</text>
                      <text class="flower-axis-label weakness" x="88" y="468">虚弱特征</text>
                      <g
                        v-for="profile in realtimeFeatureProfiles"
                        :key="profile.key"
                        :class="['flower-group', profile.key, { active: profile.active }]"
                        :style="{ '--state-color': profile.color }"
                      >
                        <line
                          v-for="petal in profile.petals"
                          :key="`${profile.key}-${petal.label}`"
                          class="flower-petal"
                          :x1="petal.x1"
                          :y1="petal.y1"
                          :x2="petal.x2"
                          :y2="petal.y2"
                        ></line>
                        <circle
                          v-for="petal in profile.petals"
                          :key="`${profile.key}-${petal.label}-dot`"
                          class="flower-dot"
                          :cx="petal.x2"
                          :cy="petal.y2"
                          r="5"
                        ></circle>
                      </g>
                      <circle class="flower-center" cx="280" cy="280" r="56"></circle>
                      <text class="flower-center-title" x="280" y="274">20秒</text>
                      <text class="flower-center-subtitle" x="280" y="300">特征指纹</text>
                    </svg>
                    <div class="flower-legend">
                      <article
                        v-for="profile in realtimeFeatureProfiles"
                        :key="profile.key"
                        class="flower-legend-item"
                        :class="{ active: profile.active }"
                        :style="{ '--state-color': profile.color }"
                      >
                        <strong>{{ profile.name }}</strong>
                        <span>{{ profile.topFeatures }}</span>
                      </article>
                    </div>
                  </div>
                </article>
              </div>
              <div v-if="hasFeatureWindowZFeatureData" class="explain-grid">
                <article v-for="item in featureExplanations" :key="item.state" class="explain-card" :style="{ '--state-color': item.color }">
                  <strong>{{ item.state }}</strong>
                  <p>{{ item.text }}</p>
                </article>
              </div>
              <div v-else class="eeg-visual-empty">特征详情会在算法完成一个 20 秒融合 voting 窗口后刷新，展示这段窗口内实际参与融合的 EEG 特征。</div>
            </div>
        </template>
      </section>

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
.top-bar, .base-panel, .panel, .eeg-visual-section { border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: 0 14px 32px rgba(66,101,122,.08); }
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
.video-panel { order: 1; }
.eeg-panel { order: 2; }
.warning-panel { order: 3; }
.eeg-visual-section { order: 4; grid-column: 1 / -1; }
.panel { padding: 20px; }
.video-box, .empty-box { margin-top: 16px; height: 320px; border-radius: 8px; overflow: hidden; background: #07121f; }
.result-video { width: 100%; height: 100%; border: 0; }
.result-image { width: 100%; height: 320px; border-radius: 8px; background: #f5f5f5; }
.empty-box { display: flex; align-items: center; justify-content: center; color: #dbeafe; }
.result-grid, .signal-strip, .warning-grid, .band-grid { margin-top: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.chart-wrap { position: relative; margin-top: 16px; min-height: 320px; border-radius: 8px; background: #fbfeff; border: 1px solid #e4edf2; }
.eeg-chart { height: 320px; width: 100%; }
.chart-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #7b8a97; pointer-events: none; }
.eeg-visual-section { margin-top: 0; padding: 18px; border: 1px solid #d9e9ee; background: linear-gradient(180deg, #fbfeff, #f4fafc); }
.eeg-visual-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.eeg-visual-head h4 { margin: 0; color: #203444; font-size: 18px; }
.eeg-visual-head p { margin: 6px 0 0; color: #64748b; font-size: 13px; }
.page-switch :deep(.el-button) { min-width: 118px; font-weight: 700; }
.eeg-visual-empty { margin-top: 14px; min-height: 160px; display: flex; align-items: center; justify-content: center; border-radius: 10px; border: 1px dashed #cbdce3; color: #718696; background: #fff; }
.status-empty { flex-direction: column; gap: 10px; text-align: center; padding: 24px; background: linear-gradient(135deg, #f8fcff, #eefafa); }
.status-empty strong { color: #203444; font-size: 20px; }
.status-empty span { max-width: 720px; color: #64748b; line-height: 1.7; }
.eeg-visual-page { margin-top: 14px; }
.page-note { padding: 12px 14px; border-radius: 10px; border: 1px solid #cfe9ed; background: #eefafa; color: #476275; font-size: 14px; line-height: 1.65; }
.page-note strong { color: #0f766e; }
.visual-grid { display: grid; gap: 14px; margin-top: 14px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.visual-card { position: relative; border-radius: 12px; border: 1px solid #dce9ee; background: #fff; box-shadow: 0 8px 22px rgba(61,101,120,.07); }
.visual-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 14px 16px 0; color: #203444; font-weight: 800; }
.visual-title span { font-size: 16px; }
.visual-title small { color: #718696; font-weight: 500; font-size: 12px; }
.mini-chart { height: 330px; width: 100%; }
.evidence-card { grid-column: 1 / -1; padding-bottom: 14px; }
.flower-chart { display: grid; grid-template-columns: minmax(360px, .92fr) 1fr; gap: 16px; align-items: center; margin: 14px; padding: 16px; border-radius: 18px; border: 1px solid #d7e8ee; background: radial-gradient(circle at 32% 50%, #ffffff 0%, #f6fbfd 58%, #eef7fa 100%); }
.flower-svg { width: 100%; max-height: 520px; min-height: 420px; overflow: visible; }
.flower-ring { fill: none; stroke: #dbe8ee; stroke-width: 1.2; }
.flower-ring.strong { stroke: #c6dbe3; stroke-width: 1.6; stroke-dasharray: 6 7; }
.flower-axis-label { fill: #64748b; font-size: 18px; font-weight: 900; letter-spacing: .5px; }
.flower-group { color: var(--state-color); }
.flower-petal { stroke: currentColor; stroke-width: 18; stroke-linecap: round; opacity: .46; filter: drop-shadow(0 8px 12px rgba(39,73,89,.16)); }
.flower-dot { fill: #fff; stroke: currentColor; stroke-width: 3; opacity: .95; }
.flower-group.active .flower-petal { stroke-width: 24; opacity: .82; filter: drop-shadow(0 12px 18px rgba(15,118,110,.2)); }
.flower-center { fill: #0f766e; filter: drop-shadow(0 12px 22px rgba(15,118,110,.28)); }
.flower-center-title, .flower-center-subtitle { fill: #fff; text-anchor: middle; font-weight: 900; }
.flower-center-title { font-size: 22px; }
.flower-center-subtitle { font-size: 17px; opacity: .9; }
.flower-legend { display: grid; gap: 12px; }
.flower-legend-item { border-left: 5px solid var(--state-color); border-radius: 12px; padding: 14px 16px; background: rgba(255,255,255,.86); box-shadow: 0 8px 18px rgba(61,101,120,.06); }
.flower-legend-item.active { background: #eefafa; box-shadow: 0 12px 24px rgba(15,118,110,.14); }
.flower-legend-item strong { display: block; color: var(--state-color); font-size: 18px; margin-bottom: 6px; }
.flower-legend-item span { color: #64748b; font-size: 13px; line-height: 1.5; }
.explain-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.explain-card { position: relative; padding: 14px; border-radius: 10px; border: 1px solid #e1ebef; background: #f9fcfd; }
.explain-card::before { content: ''; position: absolute; left: 0; top: 12px; bottom: 12px; width: 3px; border-radius: 4px; background: var(--state-color); }
.explain-card strong { color: var(--state-color); font-size: 16px; }
.explain-card p { margin: 8px 0 0; color: #607483; font-size: 12px; line-height: 1.55; }
.empty-wrap { min-height: 100%; display: flex; align-items: center; justify-content: center; }
.eye-alert-mask { position: fixed; inset: 0; z-index: 2400; display: flex; align-items: flex-start; justify-content: center; padding: 72px 20px 20px; background: rgba(15,23,42,.22); pointer-events: none; }
.eye-alert-card { pointer-events: auto; width: min(760px, 100%); display: grid; grid-template-columns: 76px 1fr auto; gap: 20px; align-items: center; padding: 26px 28px; border-radius: 8px; border: 2px solid #f59e0b; background: #fffbeb; box-shadow: 0 28px 70px rgba(120,53,15,.28); color: #78350f; }
.eye-alert-card.danger { border-color: #dc2626; background: #fef2f2; box-shadow: 0 28px 76px rgba(127,29,29,.34); color: #7f1d1d; }
.eye-alert-icon { width: 64px; height: 64px; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: #f59e0b; color: #fff; font-size: 42px; font-weight: 900; line-height: 1; }
.eye-alert-card.danger .eye-alert-icon { background: #dc2626; }
.eye-alert-content strong { display: block; font-size: 28px; line-height: 1.2; }
.eye-alert-content p { margin: 10px 0 8px; font-size: 20px; font-weight: 700; line-height: 1.55; }
.eye-alert-content span { font-size: 15px; font-weight: 600; opacity: .82; }
.eye-alert-close { min-width: 82px; height: 42px; border: 0; border-radius: 8px; background: rgba(15,23,42,.9); color: #fff; font-size: 16px; font-weight: 700; cursor: pointer; }
:global(.strong-alert-notification) { width: 420px; border-width: 2px; box-shadow: 0 20px 48px rgba(120,53,15,.22); }
:global(.strong-alert-notification .el-notification__title) { font-size: 20px; font-weight: 800; }
:global(.strong-alert-notification .el-notification__content) { font-size: 16px; font-weight: 700; line-height: 1.6; }
:global(.strong-alert-notification.danger) { box-shadow: 0 20px 52px rgba(127,29,29,.28); }
@media (max-width: 1440px) { .content-grid { grid-template-columns: 1fr; } .config-grid, .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .explain-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 960px) { .detail-page { padding: 16px; } .top-bar, .top-actions, .eeg-visual-head, .visual-title { flex-direction: column; align-items: flex-start; } .config-grid, .quick-grid, .result-grid, .signal-strip, .warning-grid, .band-grid, .visual-grid, .explain-grid { grid-template-columns: 1fr; } .evidence-card { grid-column: auto; } .flower-chart { grid-template-columns: 1fr; } .flower-svg { min-height: 380px; } .eye-alert-card { grid-template-columns: 52px 1fr; padding: 20px; } .eye-alert-icon { width: 48px; height: 48px; font-size: 32px; } .eye-alert-content strong { font-size: 22px; } .eye-alert-content p { font-size: 17px; } .eye-alert-close { grid-column: 1 / -1; width: 100%; } }
</style>
