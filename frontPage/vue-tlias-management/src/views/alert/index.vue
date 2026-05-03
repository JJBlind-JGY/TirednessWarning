<script setup>
import { useRouter } from 'vue-router'
import { useMonitorCenter } from './useMonitorCenter'

const router = useRouter()
const {
  state,
  overview,
  DEVICE_OPTIONS,
  CAMERA_OPTIONS,
  useMonitorCenterPage,
  addBinding,
  removeBinding,
  updateBindingPerson,
  updateBindingDevice,
  updateBindingCamera,
  getDeviceLabel,
  getCameraLabel,
  getDisplayEmotion,
  getAccessText,
  getEegStatusLabel,
  getFaceStatusLabel,
  getWarningText,
  getAlertType,
  formatShortTime
} = useMonitorCenter()

useMonitorCenterPage()
function openDetail(bindingId) { router.push(`/alert/device/${bindingId}`) }
function getDevicePort(workerId) { return DEVICE_OPTIONS.find((item) => item.value === workerId)?.port || '--' }
function latestTime(binding) { const value = binding.analysisTime || binding.lastValidFaceAt; return value ? formatShortTime(value) : '--:--:--' }
function adviceText(binding) { if (!binding.lastValidEegAt && !binding.lastValidFaceAt) return '等待有效数据'; return binding.emotion === 'normal' ? '继续监测' : '建议关注' }
</script>

<template>
  <div class="overview-page">
    <section class="hero-panel">
      <div class="hero-copy">
        <div class="hero-kicker">综合监测</div>
        <h1>脑电 / 微表情 / 预警</h1>
        <p>集中展示人员绑定、实时接入状态、脑电指数变化、微表情识别与综合预警结果。</p>
      </div>
      <div class="hero-metrics">
        <div class="metric-card"><span>监测卡片</span><strong>{{ overview.total }}</strong></div>
        <div class="metric-card"><span>已接入</span><strong>{{ overview.onlineCount }}</strong></div>
        <div class="metric-card warning"><span>预警卡片</span><strong>{{ overview.warningCount }}</strong></div>
        <div class="metric-card danger"><span>非正常状态</span><strong>{{ overview.dangerCount }}</strong></div>
      </div>
    </section>

    <section class="toolbar">
      <div>
        <h2>综合监测卡片</h2>
        <p>每张卡片绑定一名人员、一台脑电设备和一个摄像头。</p>
      </div>
      <el-button type="primary" @click="addBinding">新增监测卡片</el-button>
    </section>

    <section v-if="!state.personnelOptions.length || !DEVICE_OPTIONS.length || !CAMERA_OPTIONS.length" class="config-empty-board">
      <el-alert v-if="!state.personnelOptions.length" type="warning" :closable="false" title="请先在人员管理中配置人员" />
      <el-alert v-if="!DEVICE_OPTIONS.length" type="warning" :closable="false" title="请先在设备管理中配置脑电设备" />
      <el-alert v-if="!CAMERA_OPTIONS.length" type="warning" :closable="false" title="请先在设备管理中配置摄像头 RTSP 地址" />
    </section>

    <section v-if="state.bindings.length" class="card-grid">
      <article v-for="binding in state.bindings" :key="binding.id" class="device-card">
        <header class="card-header">
          <div>
            <h3>{{ binding.personName || '未绑定人员' }}</h3>
            <p>{{ getDeviceLabel(binding.workerId) }} / {{ getCameraLabel(binding.faceChannelId) }}</p>
          </div>
          <div class="card-actions">
            <el-tag :type="getAlertType(binding)" effect="dark">{{ getWarningText(binding) }}</el-tag>
            <el-button link type="danger" @click="removeBinding(binding.id)">移除</el-button>
          </div>
        </header>

        <div class="config-grid">
          <el-form-item label="人员">
            <el-select v-model="binding.personId" placeholder="选择人员" filterable @change="updateBindingPerson(binding)">
              <el-option v-for="person in state.personnelOptions" :key="person.id" :label="`${person.name} / ${person.uid}`" :value="person.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="脑电设备">
            <el-select v-model="binding.workerId" placeholder="选择脑电设备" @change="updateBindingDevice(binding)">
              <el-option v-for="device in DEVICE_OPTIONS" :key="device.value" :label="device.label" :value="device.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="岗位">
            <el-input :model-value="binding.personType" disabled placeholder="未配置" />
          </el-form-item>
          <el-form-item label="摄像头设备">
            <el-select v-model="binding.faceChannelId" placeholder="选择摄像头" @change="updateBindingCamera(binding)">
              <el-option v-for="camera in CAMERA_OPTIONS" :key="camera.id" :label="camera.label" :value="camera.id" />
            </el-select>
          </el-form-item>
        </div>

        <div class="summary-grid">
          <div class="summary-item"><span>接入状态</span><strong>{{ getAccessText(binding) }}</strong></div>
          <div class="summary-item"><span>综合状态</span><strong>{{ getDisplayEmotion(binding) }}</strong></div>
          <div class="summary-item"><span>面部识别</span><strong>{{ binding.lastValidFaceEmotionZh || getFaceStatusLabel(binding) }}</strong></div>
          <div class="summary-item"><span>脑电识别</span><strong>{{ binding.lastValidEegEmotion ? binding.eegEmotionZh : getEegStatusLabel(binding) }}</strong></div>
          <div class="summary-item"><span>最近时间</span><strong>{{ latestTime(binding) }}</strong></div>
          <div class="summary-item"><span>处理建议</span><strong>{{ adviceText(binding) }}</strong></div>
        </div>

        <div class="mini-footer">
          <div class="mini-line"><span>设备端口</span><strong>{{ getDevicePort(binding.workerId) }}</strong></div>
          <div class="mini-line"><span>摄像头</span><strong>{{ getCameraLabel(binding.faceChannelId) }}</strong></div>
          <div class="mini-line"><span>脑电波形</span><strong>{{ binding.rawWaveBuffer.length ? '已接入' : getEegStatusLabel(binding) }}</strong></div>
          <div class="mini-line"><span>微表情</span><strong>{{ getFaceStatusLabel(binding) }}</strong></div>
        </div>

        <div class="enter-bar"><el-button type="primary" @click="openDetail(binding.id)">查看详情</el-button></div>
      </article>
    </section>

    <el-empty v-else class="empty-bindings" description="暂无监测卡片" />

    <section v-if="state.alertHistory.length" class="alert-board">
      <div class="section-head"><h3>预警历史</h3></div>
      <div class="alert-list">
        <div v-for="item in state.alertHistory" :key="item.id" class="alert-row" :class="item.level">
          <div class="alert-main"><strong>{{ item.personName }}</strong><span>{{ item.device }}</span></div>
          <p>{{ item.message }}</p><time>{{ item.time }}</time>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.overview-page { min-height: 100%; padding: 24px; background: linear-gradient(180deg, #f4fbff 0%, #eef5f7 100%); }
.hero-panel { display: grid; grid-template-columns: 1.5fr 1fr; gap: 20px; padding: 28px; border-radius: 8px; background: linear-gradient(135deg, #0f3d56 0%, #2f6176 55%, #d8e8ee 100%); color: #fff; box-shadow: 0 18px 45px rgba(16,58,82,.16); }
.hero-kicker { font-size: 13px; color: rgba(255,255,255,.76); }
.hero-copy h1 { margin: 10px 0 14px; font-size: 30px; }
.hero-copy p { margin: 0; line-height: 1.8; color: rgba(255,255,255,.84); }
.hero-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.metric-card { padding: 18px; border-radius: 8px; background: rgba(255,255,255,.12); }
.metric-card span { display: block; font-size: 13px; color: rgba(255,255,255,.74); }
.metric-card strong { display: block; margin-top: 10px; font-size: 28px; }
.metric-card.warning { background: rgba(245,158,11,.22); }
.metric-card.danger { background: rgba(239,68,68,.22); }
.toolbar, .config-empty-board, .alert-board, .device-card, .empty-bindings { margin-top: 20px; border-radius: 8px; background: rgba(255,255,255,.9); box-shadow: 0 14px 32px rgba(66,101,122,.08); }
.config-empty-board { display: grid; gap: 10px; padding: 16px 20px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; padding: 20px 24px; }
.toolbar h2, .section-head h3, .card-header h3 { margin: 0; }
.toolbar p, .card-header p { margin: 6px 0 0; color: #64748b; }
.alert-board { padding: 20px 24px; }
.alert-list { display: grid; gap: 12px; }
.alert-row { display: grid; grid-template-columns: 1fr 1.6fr 180px; gap: 14px; align-items: center; padding: 14px 16px; border-radius: 8px; background: #f7fafc; }
.alert-row.warning { background: #fff7e6; }
.alert-main span, .alert-row time { color: #64748b; }
.alert-row p { margin: 0; }
.card-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.empty-bindings { padding: 36px 20px; }
.device-card { padding: 22px; }
.card-header, .card-actions { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.config-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 20px 0 16px; padding: 18px; border-radius: 8px; background: #f5f9fb; }
.config-grid :deep(.el-form-item) { margin-bottom: 0; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.mini-footer { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
.summary-item, .mini-line { padding: 14px 16px; border-radius: 8px; background: #f7fafc; }
.summary-item span, .mini-line span { display: block; margin-bottom: 6px; font-size: 12px; color: #64748b; }
.summary-item strong, .mini-line strong { font-size: 18px; color: #203444; }
.enter-bar { margin-top: 18px; display: flex; justify-content: flex-end; }
@media (max-width: 1200px) { .card-grid { grid-template-columns: 1fr; } }
@media (max-width: 960px) { .overview-page { padding: 16px; } .hero-panel, .hero-metrics, .config-grid, .summary-grid, .mini-footer { grid-template-columns: 1fr; } .toolbar, .card-header, .card-actions, .alert-row { display: flex; flex-direction: column; align-items: flex-start; } }
</style>
