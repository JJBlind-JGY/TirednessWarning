<script setup>
import { computed, onMounted, ref } from 'vue'
import { Cpu, Histogram, Monitor, User, VideoCamera } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const loginName = ref('')

const activeMenu = computed(() => {
  if (route.path.startsWith('/manage/personnel')) return '/manage/personnel'
  if (route.path.startsWith('/manage/device')) return '/manage/device'
  if (route.path.startsWith('/alert/eeg') || route.path.includes('/eeg')) return '/alert/eeg'
  if (route.path.startsWith('/alert/face') || route.path.includes('/face')) return '/alert/face'
  return '/alert'
})

onMounted(() => {
  const loginUser = JSON.parse(localStorage.getItem('loginUser') || 'null')
  if (loginUser?.name) {
    loginName.value = loginUser.name
  }
})
</script>

<template>
  <div class="layout-page">
    <el-container class="layout-shell">
      <el-aside class="sidebar" width="240px">
        <div class="brand-block">
          <div class="brand-mark">EEG</div>
          <div class="brand-copy">
            <strong>综合监测平台</strong>
            <span>脑电 / 微表情 / 预警</span>
          </div>
        </div>

        <el-menu :default-active="activeMenu" router class="nav-menu">
          <el-menu-item index="/alert" class="nav-item">
            <el-icon><Monitor /></el-icon>
            <span>综合监测</span>
          </el-menu-item>
          <el-menu-item index="/alert/eeg" class="nav-item">
            <el-icon><Histogram /></el-icon>
            <span>脑电界面</span>
          </el-menu-item>
          <el-menu-item index="/alert/face" class="nav-item">
            <el-icon><VideoCamera /></el-icon>
            <span>微表情界面</span>
          </el-menu-item>
          <el-menu-item index="/manage/personnel" class="nav-item">
            <el-icon><User /></el-icon>
            <span>人员管理</span>
          </el-menu-item>
          <el-menu-item index="/manage/device" class="nav-item">
            <el-icon><Cpu /></el-icon>
            <span>设备管理</span>
          </el-menu-item>
        </el-menu>

        <div class="sidebar-footer">
          <div class="user-card">
            <span>当前用户</span>
            <strong>{{ loginName || '未命名用户' }}</strong>
          </div>
        </div>
      </el-aside>

      <el-container>
        <el-header class="topbar">
          <div class="page-title">
            <h1>脑电与微表情综合监测</h1>
          </div>
        </el-header>

        <el-main class="main-panel">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<style scoped>
.layout-page {
  min-height: 100vh;
  background: linear-gradient(180deg, #f1f7fb 0%, #edf3f7 100%);
}

.layout-shell {
  min-height: 100vh;
}

.sidebar {
  display: flex;
  flex-direction: column;
  padding: 22px 18px;
  background: linear-gradient(180deg, #0f3d56 0%, #173f57 55%, #234a63 100%);
  color: #fff;
  box-shadow: 10px 0 30px rgba(15, 61, 86, 0.14);
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 6px 22px;
}

.brand-mark {
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: linear-gradient(135deg, #7dd3fc 0%, #bae6fd 100%);
  color: #0f3d56;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.brand-copy strong {
  font-size: 18px;
}

.brand-copy span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}

.nav-menu {
  border: none;
  background: transparent;
}

.nav-menu :deep(.el-menu-item) {
  margin-bottom: 10px;
  border-radius: 14px;
  color: rgba(255, 255, 255, 0.78);
}

.nav-menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.nav-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(135deg, rgba(125, 211, 252, 0.2), rgba(255, 255, 255, 0.12));
  color: #fff;
}

.sidebar-footer {
  margin-top: auto;
  padding-top: 20px;
}

.user-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.08);
}

.user-card span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.68);
}

.user-card strong {
  font-size: 16px;
}

.topbar {
  display: flex;
  align-items: center;
  padding: 20px 28px;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid #e2ebf0;
}

.page-title h1 {
  margin: 0;
  font-size: 28px;
  color: #17384d;
}

.main-panel {
  padding: 0;
}

@media (max-width: 960px) {
  .layout-shell {
    flex-direction: column;
  }

  .sidebar {
    width: 100% !important;
    padding: 16px;
  }

  .topbar {
    align-items: flex-start;
  }
}
</style>
