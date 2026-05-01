<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { useMonitorCenter } from '@/views/alert/useMonitorCenter'

const { state, initMonitorCenter, useMonitorCenterPage, addPersonnel, updatePersonnel, removePersonnel } = useMonitorCenter()

useMonitorCenterPage()
void initMonitorCenter()

const form = reactive({
  id: '',
  name: '',
  uid: '',
  type: ''
})

function resetForm() {
  form.id = ''
  form.name = ''
  form.uid = ''
  form.type = ''
}

async function submitForm() {
  if (!form.name || !form.uid) {
    ElMessage.warning('请先填写人员姓名和编号')
    return
  }
  try {
    if (form.id) {
      await updatePersonnel({ ...form })
      ElMessage.success('人员信息已更新')
    } else {
      await addPersonnel({ ...form })
      ElMessage.success('人员已添加')
    }
    resetForm()
  } catch (error) {
    ElMessage.error('人员信息保存失败，请确认 face-service 已启动')
  }
}

function editRow(row) {
  form.id = row.id
  form.name = row.name
  form.uid = row.uid
  form.type = row.type
}

async function removeRow(row) {
  try {
    await removePersonnel(row.id)
    if (form.id === row.id) {
      resetForm()
    }
    ElMessage.success('人员已删除')
  } catch (error) {
    ElMessage.error('人员删除失败，请确认 face-service 已启动')
  }
}
</script>

<template>
  <div class="manage-page">
    <section class="manage-hero">
      <div>
        <div class="hero-kicker">PERSONNEL</div>
        <h1>人员管理</h1>
      </div>
    </section>

    <section class="manage-grid">
      <article class="panel form-panel">
        <div class="panel-head">
          <h3>{{ form.id ? '编辑人员' : '新增人员' }}</h3>
        </div>
        <div class="form-grid">
          <el-form-item label="人员姓名">
            <el-input v-model="form.name" placeholder="例如：张三" />
          </el-form-item>
          <el-form-item label="人员编号">
            <el-input v-model="form.uid" placeholder="例如：P001" />
          </el-form-item>
          <el-form-item label="岗位">
            <el-input v-model="form.type" placeholder="例如：值班员" />
          </el-form-item>
        </div>
        <div class="form-actions">
          <el-button type="primary" @click="submitForm">{{ form.id ? '保存修改' : '添加人员' }}</el-button>
          <el-button @click="resetForm">重置</el-button>
        </div>
      </article>

      <article class="panel table-panel">
        <div class="panel-head">
          <h3>人员列表</h3>
          <span class="count-chip">{{ state.personnelOptions.length }} 人</span>
        </div>
        <el-table :data="state.personnelOptions" stripe empty-text="暂无人员信息，请先新增人员">
          <el-table-column prop="name" label="姓名" min-width="140" />
          <el-table-column prop="uid" label="编号" min-width="140" />
          <el-table-column prop="type" label="岗位" min-width="160" />
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button link type="primary" @click="editRow(row)">编辑</el-button>
              <el-button link type="danger" @click="removeRow(row)">删除</el-button>
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
    radial-gradient(circle at top left, rgba(16, 112, 180, 0.1), transparent 28%),
    linear-gradient(180deg, #f4f9fc 0%, #edf3f6 100%);
}

.manage-hero,
.panel {
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 18px 38px rgba(26, 67, 89, 0.08);
}

.manage-hero {
  padding: 28px;
}

.hero-kicker {
  font-size: 12px;
  letter-spacing: 0.16em;
  color: #0f5f8d;
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
  background: #eef6fb;
  color: #1b5c83;
  font-size: 13px;
}

@media (max-width: 1100px) {
  .manage-grid {
    grid-template-columns: 1fr;
  }
}
</style>
