<script setup>
import { onBeforeUnmount, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { useMonitorCenter } from '@/views/alert/useMonitorCenter'

const {
  DEVICE_OPTIONS,
  CAMERA_OPTIONS,
  initMonitorCenter,
  useMonitorCenterPage,
  addDevice,
  updateDevice,
  removeDevice,
  addCamera,
  updateCamera,
  removeCamera
} = useMonitorCenter()

useMonitorCenterPage()
void initMonitorCenter()

const eegForm = reactive({
  value: null,
  name: '',
  transport: 'wifi',
  baseUrl: '',
  port: '',
  baud: 460800
})
const eegHealth = reactive({})
let healthTimer = null

const cameraForm = reactive({
  id: '',
  originalId: '',
  name: '',
  sourceType: 'local',
  deviceIndex: 0,
  rtspUrl: '',
  streamName: ''
})

function resetEegForm() {
  eegForm.value = null
  eegForm.name = ''
  eegForm.transport = 'wifi'
  eegForm.baseUrl = ''
  eegForm.port = ''
  eegForm.baud = 460800
}

function resetCameraForm() {
  cameraForm.id = ''
  cameraForm.originalId = ''
  cameraForm.name = ''
  cameraForm.sourceType = 'local'
  cameraForm.deviceIndex = 0
  cameraForm.rtspUrl = ''
  cameraForm.streamName = ''
}

async function submitEegForm() {
  if (!eegForm.name) {
    ElMessage.warning('请先填写脑电设备名称')
    return
  }
  if (eegForm.transport === 'wifi') {
    eegForm.baseUrl = normalizeDeviceUrl(eegForm.baseUrl)
    eegForm.port = ''
    if (!isValidDeviceUrl(eegForm.baseUrl)) {
      ElMessage.warning('请填写有效的 HTTP 设备地址，例如 http://192.168.1.50')
      return
    }
  } else {
    eegForm.baseUrl = ''
    eegForm.port = String(eegForm.port || '').trim()
    eegForm.baud = Number.parseInt(eegForm.baud || 57600, 10) || 57600
    if (!eegForm.port) {
      ElMessage.warning('请填写串口号，例如 COM5')
      return
    }
  }


  try {
    if (eegForm.value != null) {
      await updateDevice({ ...eegForm })
      ElMessage.success('脑电设备已更新')
    } else {
      await addDevice({ ...eegForm })
      ElMessage.success('脑电设备已添加')
    }
    resetEegForm()
  } catch (error) {
    ElMessage.error('脑电设备保存失败，请确认 EEG 服务已启动')
  }
}

async function submitCameraForm() {
  if (!cameraForm.id) {
    ElMessage.warning('请填写摄像头通道')
    return
  }
  if (!cameraForm.name) {
    ElMessage.warning('请填写摄像头名称')
    return
  }
  if (cameraForm.sourceType === 'rtsp' && !cameraForm.rtspUrl) {
    ElMessage.warning('请填写 RTSP 地址')
    return
  }
  if (hasLocalCameraIndexConflict()) {
    ElMessage.warning(`本机摄像头索引 ${cameraForm.deviceIndex} 已被其他通道使用`)
    return
  }

  const payload = {
    id: cameraForm.id,
    name: cameraForm.name,
    sourceType: cameraForm.sourceType,
    deviceIndex: cameraForm.deviceIndex,
    rtspUrl: cameraForm.sourceType === 'rtsp' ? cameraForm.rtspUrl : '',
    streamName: cameraForm.streamName || cameraForm.id
  }

  try {
    if (cameraForm.originalId) {
      if (cameraForm.originalId !== cameraForm.id) {
        await removeCamera(cameraForm.originalId)
        await addCamera(payload)
      } else {
        await updateCamera(payload)
      }
      ElMessage.success('摄像头设备已更新')
    } else {
      await addCamera(payload)
      ElMessage.success('摄像头设备已添加')
    }
    resetCameraForm()
  } catch (error) {
    ElMessage.error('摄像头设备保存失败，请确认 face-service 已启动')
  }
}

function hasLocalCameraIndexConflict() {
  if (cameraForm.sourceType !== 'local') return false
  const currentId = cameraForm.originalId || cameraForm.id
  const currentIndex = Number(cameraForm.deviceIndex ?? 0)
  return CAMERA_OPTIONS.some((camera) => (
    camera.id !== currentId
    && camera.sourceType === 'local'
    && Number(camera.deviceIndex ?? 0) === currentIndex
  ))
}

function editEegRow(row) {
  eegForm.value = row.value
  eegForm.name = row.name
  eegForm.transport = row.transport || (row.port ? 'serial' : 'wifi')
  eegForm.baseUrl = row.baseUrl || ''
  eegForm.port = row.port || ''
  eegForm.baud = row.baud || 57600
}

function isValidDeviceUrl(value) {
  try {
    const url = new URL(String(value || '').trim())
    return ['http:', 'https:'].includes(url.protocol) && Boolean(url.host)
  } catch {
    return false
  }
}

function normalizeDeviceUrl(value) {
  const input = String(value || '').trim().replace(/\/+$/, '')
  return input && !input.includes('://') ? `http://${input}` : input
}

function getEegConnectionText(row) {
  return row.transport === 'serial' ? `${row.port || '--'} / ${row.baud || 57600}` : (row.baseUrl || '--')
}

function formatLastSuccess(value) {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '--' : date.toLocaleTimeString('zh-CN', { hour12: false })
}

function deviceRuntime(row) {
  return eegHealth[row.value] || {}
}

function deviceStatusMeta(row) {
  const runtime = deviceRuntime(row)
  const status = runtime.status || 'connecting'
  if (status === 'online' && runtime.last_success_at) return { text: '采集中', type: 'success' }
  if (status === 'connecting') return { text: '连接中', type: 'warning' }
  if (status === 'offline') return { text: '设备离线', type: 'info' }
  if (status === 'error') return { text: '协议错误', type: 'danger' }
  return { text: '等待采集', type: 'info' }
}

async function refreshEegHealth() {
  try {
    const response = await fetch('/eeg/health', { cache: 'no-store' })
    if (!response.ok) return
    const payload = await response.json()
    Object.keys(eegHealth).forEach((key) => delete eegHealth[key])
    Object.entries(payload.workers || {}).forEach(([key, value]) => {
      eegHealth[key] = value
    })
  } catch {
    // Keep the last known device state while the EEG service restarts.
  }
}

async function probeEegDevice(row) {
  try {
    const response = await fetch(`/eeg/devices/${encodeURIComponent(row.value)}/probe`, { cache: 'no-store' })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.message || '连接失败')
    ElMessage.success(`设备连接正常：${payload.data?.deviceId || row.name}`)
    await refreshEegHealth()
  } catch (error) {
    ElMessage.error(`设备连接失败：${error.message || '请检查地址和同一 WiFi'}`)
  }
}

onMounted(() => {
  void refreshEegHealth()
  healthTimer = window.setInterval(refreshEegHealth, 5000)
})

onBeforeUnmount(() => {
  if (healthTimer) window.clearInterval(healthTimer)
})

async function removeEegRow(row) {
  try {
    await removeDevice(row.value)
    if (eegForm.value === row.value) {
      resetEegForm()
    }
    ElMessage.success('脑电设备已删除')
  } catch (error) {
    ElMessage.error('脑电设备删除失败，请确认 EEG 服务已启动')
  }
}

function editCameraRow(row) {
  cameraForm.id = row.id
  cameraForm.originalId = row.id
  cameraForm.name = row.name
  cameraForm.sourceType = row.sourceType || 'rtsp'
  cameraForm.deviceIndex = row.deviceIndex ?? 0
  cameraForm.rtspUrl = row.rtspUrl
  cameraForm.streamName = row.streamName || row.id
}

async function removeCameraRow(row) {
  try {
    await removeCamera(row.id)
    if (cameraForm.originalId === row.id) {
      resetCameraForm()
    }
    ElMessage.success('摄像头设备已删除')
  } catch (error) {
    ElMessage.error('摄像头设备删除失败，请确认 face-service 已启动')
  }
}
</script>

<template>
  <div class="manage-page">
    <section class="manage-hero">
      <div>
        <div class="hero-kicker">DEVICE</div>
        <h1>设备管理</h1>
      </div>
    </section>

    <section class="manage-grid">
      <article class="panel form-panel">
        <div class="panel-head">
          <h3>{{ eegForm.value != null ? '编辑脑电设备' : '新增脑电设备' }}</h3>
        </div>
        <div class="form-grid">
          <el-form-item label="脑电设备名称">
            <el-input v-model="eegForm.name" placeholder="例如：脑电 1" />
          </el-form-item>
          <el-form-item label="设备类型">
            <el-radio-group v-model="eegForm.transport">
              <el-radio-button label="wifi">WiFi 设备</el-radio-button>
              <el-radio-button label="serial">串口设备</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="eegForm.transport === 'wifi'" label="设备 IP / 地址">
            <el-input v-model="eegForm.baseUrl" placeholder="例如：http://192.168.1.50" />
          </el-form-item>
          <template v-else>
            <el-form-item label="脑电串口">
              <el-input v-model="eegForm.port" placeholder="例如：COM5" />
            </el-form-item>
            <el-form-item label="串口波特率">
              <el-input-number v-model="eegForm.baud" :min="1200" :step="1200" />
            </el-form-item>
          </template>
        </div>
        <el-alert
          v-if="eegForm.transport === 'serial'"
          class="eeg-usage-tip"
          type="info"
          :closable="false"
          title="新版 USB 透传固件使用 460800 波特率；旧设备请按原固件手动选择波特率。"
        />
        <el-alert
          v-else
          class="eeg-usage-tip"
          type="info"
          :closable="false"
          title="WiFi 设备需烧录项目固件，并在同一 2.4 GHz 局域网内配置设备 IP。"
        />
        <el-alert
          class="eeg-usage-tip"
          type="warning"
          :closable="false"
          title="采集前请用酒精清洁皮肤并保持静止。耳夹款：EEG 电极贴额头；三金属电极款：小端轻压头皮并微调至接触稳定。"
        />
        <div class="form-actions">
          <el-button type="primary" @click="submitEegForm">{{ eegForm.value != null ? '保存脑电设备' : '添加脑电设备' }}</el-button>
          <el-button @click="resetEegForm">重置</el-button>
        </div>
      </article>

      <article class="panel form-panel">
        <div class="panel-head">
          <h3>{{ cameraForm.originalId ? '编辑摄像头设备' : '新增摄像头设备' }}</h3>
        </div>
        <div class="form-grid">
          <el-form-item label="摄像头通道">
            <el-input v-model="cameraForm.id" :disabled="Boolean(cameraForm.originalId)" placeholder="例如：camera_001" />
          </el-form-item>
          <el-form-item label="摄像头名称">
            <el-input v-model="cameraForm.name" placeholder="例如：入口摄像头" />
          </el-form-item>
          <el-form-item label="摄像头来源">
            <el-select v-model="cameraForm.sourceType">
              <el-option label="本机摄像头" value="local" />
              <el-option label="RTSP 摄像头" value="rtsp" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="cameraForm.sourceType === 'local'" label="设备索引">
            <el-input-number v-model="cameraForm.deviceIndex" :min="0" :step="1" />
          </el-form-item>
          <el-form-item v-else label="RTSP 地址">
            <el-input v-model="cameraForm.rtspUrl" placeholder="rtsp://192.168.1.8:554/type=0&id=3" />
          </el-form-item>
          <el-form-item v-if="cameraForm.sourceType === 'rtsp'" label="go2rtc stream">
            <el-input v-model="cameraForm.streamName" placeholder="optional, default camera id" />
          </el-form-item>
        </div>
        <div class="form-actions">
          <el-button type="primary" @click="submitCameraForm">{{ cameraForm.originalId ? '保存摄像头' : '添加摄像头' }}</el-button>
          <el-button @click="resetCameraForm">重置</el-button>
        </div>
      </article>

      <article class="panel table-panel">
        <div class="panel-head">
          <h3>脑电设备列表</h3>
          <span class="count-chip">{{ DEVICE_OPTIONS.length }} 个</span>
        </div>
        <el-table :data="DEVICE_OPTIONS" stripe empty-text="暂无脑电设备，请先新增 WiFi 脑电设备">
          <el-table-column prop="value" label="WorkerId" width="120" />
          <el-table-column prop="name" label="脑电设备名称" min-width="160" />
          <el-table-column prop="baseUrl" label="设备地址" min-width="210" show-overflow-tooltip />
          <el-table-column label="状态" min-width="150">
            <template #default="{ row }">
              <el-tag :type="deviceStatusMeta(row).type">
                {{ deviceStatusMeta(row).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="WiFi RSSI" width="110">
            <template #default="{ row }">{{ deviceRuntime(row).device_rssi ?? '--' }}</template>
          </el-table-column>
          <el-table-column label="最近数据" width="120">
            <template #default="{ row }">{{ formatLastSuccess(deviceRuntime(row).last_success_at) }}</template>
          </el-table-column>
          <el-table-column label="丢点" width="90">
            <template #default="{ row }">{{ deviceRuntime(row).dropped_sample_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="采样游标" width="120">
            <template #default="{ row }">{{ deviceRuntime(row).sample_cursor ?? '--' }}</template>
          </el-table-column>
          <el-table-column label="延迟(ms)" width="100">
            <template #default="{ row }">{{ deviceRuntime(row).sample_lag_ms ?? '--' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="240">
            <template #default="{ row }">
              <el-button link type="success" @click="probeEegDevice(row)">测试连接</el-button>
              <el-button link type="primary" @click="editEegRow(row)">编辑</el-button>
              <el-button link type="danger" @click="removeEegRow(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </article>

      <article class="panel table-panel">
        <div class="panel-head">
          <h3>摄像头设备列表</h3>
          <span class="count-chip">{{ CAMERA_OPTIONS.length }} 个</span>
        </div>
        <el-table :data="CAMERA_OPTIONS" stripe empty-text="暂无摄像头设备，请先新增 RTSP 地址">
          <el-table-column prop="id" label="通道" min-width="150" />
          <el-table-column prop="name" label="摄像头名称" min-width="160" />
          <el-table-column label="来源" width="110">
            <template #default="{ row }">{{ row.sourceType === 'local' ? '本机' : 'RTSP' }}</template>
          </el-table-column>
          <el-table-column label="设备地址" min-width="280" show-overflow-tooltip>
            <template #default="{ row }">{{ row.sourceType === 'local' ? `设备索引 ${row.deviceIndex}` : row.rtspUrl }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button link type="primary" @click="editCameraRow(row)">编辑</el-button>
              <el-button link type="danger" @click="removeCameraRow(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </article>
    </section>
  </div>
</template>

<style scoped>
.manage-page {
  min-height: 100%;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 28%),
    linear-gradient(180deg, #f2f8f7 0%, #edf3f2 100%);
}

.manage-hero,
.panel {
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 18px 38px rgba(23, 70, 74, 0.08);
}

.manage-hero {
  padding: 28px;
}

.hero-kicker {
  font-size: 12px;
  letter-spacing: 0.16em;
  color: #0f766e;
}

.manage-hero h1 {
  margin: 10px 0 12px;
  color: #17384d;
}

.manage-hero p {
  margin: 0;
  color: #67808f;
}

.manage-grid {
  display: grid;
  grid-template-columns: 0.9fr 1.4fr;
  gap: 20px;
  margin-top: 20px;
}

.panel {
  padding: 20px 24px;
}

.panel-head,
.form-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.panel-head h3 {
  margin: 0;
}

.form-grid {
  display: grid;
  gap: 16px;
  margin-top: 18px;
}

.form-grid :deep(.el-form-item) {
  margin-bottom: 0;
}

.eeg-usage-tip {
  margin-top: 12px;
}

.form-actions {
  margin-top: 18px;
  justify-content: flex-end;
}

.count-chip {
  padding: 8px 12px;
  border-radius: 999px;
  background: #eef7f5;
  color: #0f766e;
  font-size: 13px;
}

@media (max-width: 1100px) {
  .manage-grid {
    grid-template-columns: 1fr;
  }
}
</style>
