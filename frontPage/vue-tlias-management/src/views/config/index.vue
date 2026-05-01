<script setup>
import { ref, reactive } from 'vue'
import {
  ElContainer,
  ElHeader,
  ElMain,
  ElTabs,
  ElTabPane,
  ElForm,
  ElFormItem,
  ElInput,
  ElSelect,
  ElOption,
  ElSwitch,
  ElButton,
  ElDivider,
  ElCard,
  ElMessage
} from 'element-plus'

// 当前激活的标签页
const activeTab = ref('device')

// ====== 装置参数配置数据（带默认值） ======
const deviceForm = reactive({
  deviceName: 'EEG-001',
  protocol:   'TCP',
  ip:         '192.168.0.10',
  port:       '5000',
  algorithm:  'default',
  enableLogging: true,
  samplingRate: 128
})
const deviceFormRef = ref(null)
const deviceProtocols = ['TCP', 'UDP', 'HTTP']
const algorithms = ['default', 'fast', 'accurate']

// ====== 场景化配置数据（带默认值） ======
const sceneForm = reactive({
  operator:  '王小明',
  shift:     'day',
  location:  '装配线 A 区',
  notes:     ''
})
const sceneFormRef = ref(null)
const shifts = ['day', 'night', 'rotating']

// ====== 提交处理 ======
function submitDevice() {
  deviceFormRef.value.validate(valid => {
    if (!valid) return
    // TODO: 调用 API 保存 deviceForm
    ElMessage.success('装置参数保存成功')
  })
}
function submitScene() {
  sceneFormRef.value.validate(valid => {
    if (!valid) return
    // TODO: 调用 API 保存 sceneForm
    ElMessage.success('场景配置保存成功')
  })
}
</script>

<template>
  <el-container class="cfg-container">
    <el-header class="cfg-header">
      <h2>装置配置管理</h2>
      <el-divider />
    </el-header>

    <el-main>
      <el-card shadow="hover" class="cfg-card">
        <el-tabs type="border-card" v-model="activeTab">
          <!-- 装置本身参数配置 -->
          <el-tab-pane label="装置参数配置" name="device">
            <el-form
              ref="deviceFormRef"
              :model="deviceForm"
              label-width="140px"
              size="small"
              class="cfg-form"
            >
              <el-form-item label="装置名称" prop="deviceName" :rules="[{ required: true, message: '请输入名称', trigger: 'blur' }]">
                <el-input v-model="deviceForm.deviceName" />
              </el-form-item>

              <el-form-item label="网络协议">
                <el-select v-model="deviceForm.protocol">
                  <el-option
                    v-for="p in deviceProtocols"
                    :key="p"
                    :label="p"
                    :value="p"
                  />
                </el-select>
              </el-form-item>

              <el-form-item label="IP 地址" prop="ip" :rules="[{ required: true, message: '请输入 IP', trigger: 'blur' }]">
                <el-input v-model="deviceForm.ip" />
              </el-form-item>

              <el-form-item label="端口号" prop="port" :rules="[{ required: true, message: '请输入端口', trigger: 'blur' }]">
                <el-input v-model="deviceForm.port" />
              </el-form-item>

              <el-form-item label="算法配置">
                <el-select v-model="deviceForm.algorithm">
                  <el-option
                    v-for="a in algorithms"
                    :key="a"
                    :label="a"
                    :value="a"
                  />
                </el-select>
              </el-form-item>

              <el-form-item label="日志记录">
                <el-switch v-model="deviceForm.enableLogging" />
              </el-form-item>

              <el-form-item label="采样率 (Hz)">
                <el-input v-model="deviceForm.samplingRate" type="number" />
              </el-form-item>

              <el-form-item>
                <el-button type="primary" @click="submitDevice">保存参数</el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <!-- 场景化配置 -->
          <el-tab-pane label="场景化配置" name="scene">
            <el-form
              ref="sceneFormRef"
              :model="sceneForm"
              label-width="140px"
              size="small"
              class="cfg-form"
            >
              <el-form-item label="作业人员" prop="operator" :rules="[{ required: true, message: '请输入姓名', trigger: 'blur' }]">
                <el-input v-model="sceneForm.operator" />
              </el-form-item>

              <el-form-item label="班次">
                <el-select v-model="sceneForm.shift">
                  <el-option
                    v-for="s in shifts"
                    :key="s"
                    :label="s"
                    :value="s"
                  />
                </el-select>
              </el-form-item>

              <el-form-item label="使用场景">
                <el-input v-model="sceneForm.location" />
              </el-form-item>

              <el-form-item label="备注">
                <el-input
                  type="textarea"
                  v-model="sceneForm.notes"
                  :rows="3"
                />
              </el-form-item>

              <el-form-item>
                <el-button type="primary" @click="submitScene">保存场景</el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </el-main>
  </el-container>
</template>

<style scoped>
.cfg-container {
  height: 100%;
  background: #f5f7fa;
}
.cfg-header {
  padding: 20px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}
.cfg-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}
.cfg-card {
  margin: 20px;
  padding: 20px;
  background: #fff;
}
.cfg-form {
  max-width: 600px;
}
</style>
