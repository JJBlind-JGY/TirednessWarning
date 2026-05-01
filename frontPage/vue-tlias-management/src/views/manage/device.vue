<script setup>
import { reactive } from 'vue'
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
  port: ''
})

const cameraForm = reactive({
  id: '',
  originalId: '',
  name: '',
  rtspUrl: ''
})

function resetEegForm() {
  eegForm.value = null
  eegForm.name = ''
  eegForm.port = ''
}

function resetCameraForm() {
  cameraForm.id = ''
  cameraForm.originalId = ''
  cameraForm.name = ''
  cameraForm.rtspUrl = ''
}

async function submitEegForm() {
  if (!eegForm.name) {
    ElMessage.warning('请先填写脑电设备名称')
    return
  }
  if (!eegForm.port) {
    ElMessage.warning('请填写脑电串口')
    return
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
  if (!cameraForm.rtspUrl) {
    ElMessage.warning('请填写 RTSP 地址')
    return
  }

  const payload = {
    id: cameraForm.id,
    name: cameraForm.name,
    rtspUrl: cameraForm.rtspUrl
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

function editEegRow(row) {
  eegForm.value = row.value
  eegForm.name = row.name
  eegForm.port = row.port
}

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
  cameraForm.rtspUrl = row.rtspUrl
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
          <el-form-item label="脑电串口">
            <el-input v-model="eegForm.port" placeholder="例如：COM5" />
          </el-form-item>
        </div>
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
          <el-form-item label="RTSP 地址">
            <el-input v-model="cameraForm.rtspUrl" placeholder="rtsp://192.168.1.8:554/type=0&id=3" />
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
        <el-table :data="DEVICE_OPTIONS" stripe empty-text="暂无脑电设备，请先新增脑电串口">
          <el-table-column prop="value" label="WorkerId" width="120" />
          <el-table-column prop="name" label="脑电设备名称" min-width="160" />
          <el-table-column prop="port" label="串口" min-width="130" />
          <el-table-column prop="label" label="展示名称" min-width="220" />
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
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
          <el-table-column prop="rtspUrl" label="RTSP 地址" min-width="280" show-overflow-tooltip />
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
