<template>
  <el-container class="page-container">
    <el-header class="header">
      <div class="header-content">
        <div class="header-title">脑电数据记录</div>
      </div>
      <el-divider class="header-divider" />
    </el-header>

    <el-main class="main">
      <el-card shadow="hover" class="table-card">
        <!-- 搜索栏 -->
        <el-form inline>
          <el-form-item label="设备端口">
            <el-input v-model="query.devicePort" placeholder="如 COM3" />
          </el-form-item>
          <el-form-item label="人员姓名">
            <el-input v-model="query.personnelName" placeholder="请输入姓名" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="fetchData">查询</el-button>
            <el-button type="info" @click="reset">重置</el-button>
          </el-form-item>
        </el-form>

        <!-- 表格 -->
        <el-table :data="data" border size="small" stripe style="width: 100%;">
          <el-table-column prop="devicePort" label="设备端口" align="center" />
          <el-table-column prop="personnelName" label="人员姓名" align="center" />
          <el-table-column prop="fatigueLevel" label="情绪等级" align="center" />
          <el-table-column prop="timestamp" label="时间" align="center" />
        </el-table>

        <!-- 分页 -->
        <div class="pagination-wrapper">
          <el-pagination
            background
            small
            layout="prev, pager, next"
            :total="total"
            :page-size="pageSize"
            v-model:current-page="currentPage"
            @current-change="fetchData"
          />
        </div>
      </el-card>
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import request from '@/utils/request'

const query = ref({ devicePort: '', personnelName: '' })
const data = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 10

async function fetchData() {
  const res = await request.get('/storage/list', { params: { ...query.value, page: currentPage.value, pageSize } })
  data.value = res.data.rows
  total.value = res.data.total
}

function reset() {
  query.value = { devicePort: '', personnelName: '' }
  currentPage.value = 1
  fetchData()
}

onMounted(fetchData)
</script>
