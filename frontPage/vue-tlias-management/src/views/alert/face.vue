<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMonitorCenter } from './useMonitorCenter'

const route = useRoute()
const router = useRouter()

const { state, useMonitorCenterPage, getBindingById, getDeviceLabel, getCameraLabel } = useMonitorCenter()

useMonitorCenterPage()

const selectedBindingId = computed(() => route.params.id || route.query.binding || state.bindings[0]?.id || '')
const binding = computed(() => getBindingById(selectedBindingId.value))

function openBinding(bindingId) {
  if (!bindingId) return
  if (route.params.id) {
    router.push(`/alert/device/${bindingId}/face`)
    return
  }
  router.push({ name: 'alertFaceHome', query: { binding: bindingId } })
}
</script>

<template>
  <div v-if="binding" class="face-page">
    <section class="face-hero">
      <div>
        <div class="hero-kicker">FACE STREAM</div>
        <h1>{{ binding.personName || '未绑定人员' }} / {{ getDeviceLabel(binding.workerId) }} / {{ getCameraLabel(binding.faceChannelId) }}</h1>
      </div>
      <div class="hero-actions">
        <el-tag :type="binding.faceConnected ? 'success' : 'info'">{{ binding.faceConnected ? '视频在线' : '等待画面' }}</el-tag>
        <el-tag type="warning">1080P</el-tag>
        <el-button @click="router.push(`/alert/device/${binding.id}`)">返回详情</el-button>
      </div>
    </section>

    <section class="video-shell">
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

      <div class="video-head">
        <div>
          <h3>实时视频流</h3>
          <p>当前页面固定展示为 1080P 标准视图。</p>
        </div>
        <div class="resolution-chip">1920 × 1080</div>
      </div>

      <div class="video-stage">
        <el-image
          v-if="binding.faceImageUrl"
          :src="binding.faceImageUrl"
          fit="contain"
          :preview-src-list="[binding.faceImageUrl]"
          class="face-stream"
        >
          <template #error>
            <div class="stream-placeholder">
              <strong>视频流加载失败</strong>
              <span>请检查微表情通道和后端推流状态。</span>
            </div>
          </template>
        </el-image>

        <div v-else class="stream-placeholder">
          <strong>等待视频流</strong>
          <span>当前还没有收到微表情画面，请保持通道在线。</span>
        </div>
      </div>
    </section>
  </div>

  <div v-else class="empty-wrap">
    <el-empty description="未找到该设备卡片">
      <el-button type="primary" @click="router.push('/alert')">返回总界面</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
.face-page {
  min-height: 100%;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(18, 76, 120, 0.14), transparent 28%),
    radial-gradient(circle at top right, rgba(32, 179, 167, 0.08), transparent 20%),
    linear-gradient(180deg, #eff5fb 0%, #ebf2f6 100%);
}

.face-hero,
.video-shell {
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 18px 38px rgba(25, 63, 88, 0.1);
}

.face-hero {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 28px;
}

.hero-kicker {
  font-size: 12px;
  letter-spacing: 0.16em;
  color: #0f5f8d;
}

.face-hero h1 {
  margin: 10px 0 12px;
  color: #17384d;
}

.face-hero p {
  margin: 0;
  max-width: 780px;
  line-height: 1.8;
  color: #667f90;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 10px;
}

.video-shell {
  margin-top: 20px;
  padding: 20px 24px 24px;
}

.binding-switcher {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 18px;
}

.video-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}

.video-head h3 {
  margin: 0;
  color: #18394e;
}

.video-head p {
  margin: 8px 0 0;
  color: #6b8392;
}

.resolution-chip {
  padding: 10px 14px;
  border-radius: 999px;
  background: linear-gradient(135deg, #0f5f8d, #1796ab);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}

.video-stage {
  margin-top: 18px;
  min-height: 640px;
  border-radius: 22px;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(6, 19, 31, 0.96) 0%, rgba(9, 28, 45, 0.98) 100%);
  border: 1px solid rgba(72, 119, 148, 0.16);
}

.face-stream {
  width: 100%;
  height: 640px;
}

.face-stream :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.face-stream :deep(.el-image__wrapper) {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}

.stream-placeholder {
  width: 100%;
  height: 640px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: rgba(232, 244, 255, 0.88);
}

.stream-placeholder strong {
  font-size: 22px;
}

.stream-placeholder span {
  color: rgba(212, 228, 239, 0.72);
}

.empty-wrap {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (max-width: 960px) {
  .face-page {
    padding: 16px;
  }

  .face-hero,
  .hero-actions,
  .video-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .video-stage,
  .face-stream,
  .stream-placeholder {
    min-height: 420px;
    height: 420px;
  }
}
</style>
