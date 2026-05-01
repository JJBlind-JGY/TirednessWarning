<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { queryPersonnelApi, importPersonnelApi } from '@/api/personnel'

// 数据区
const searchForm = ref({ name: '', uid: '', type: '', date: [], begin: '', end: '' })
const personnelList = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)
const background = ref(true)
const dialogVisible = ref(false)
const workTicket = ref('')

// 生命周期钩子
onMounted(() => {
  loadPersonnel()
})

// 侦听时间变化
watch(() => searchForm.value.date, (val) => {
  if (val && val.length === 2) {
    searchForm.value.begin = val[0]
    searchForm.value.end = val[1]
  } else {
    searchForm.value.begin = ''
    searchForm.value.end = ''
  }
})

// 查询本地人员
const loadPersonnel = async () => {
  const res = await queryPersonnelApi({
    name: searchForm.value.name,
    uid: searchForm.value.uid,
    type: searchForm.value.type,
    begin: searchForm.value.begin,
    end: searchForm.value.end,
    page: currentPage.value,
    pageSize: pageSize.value
  })
  if (res.code) {
    personnelList.value = res.data.rows
    total.value = res.data.total
  }
}

// 清空搜索
const clearSearch = () => {
  searchForm.value = { name: '', uid: '', type: '', date: [], begin: '', end: '' }
  loadPersonnel()
}

// 一键导入
const importPersonnel = () => {
  ElMessageBox.prompt('请输入工作票号（workTicket）', '人员导入', {
    confirmButtonText: '导入',
    cancelButtonText: '取消',
  }).then(async ({ value }) => {
    const res = await importPersonnelApi(value)
    if (res.code) {
      ElMessage.success('人员导入成功')
      loadPersonnel()
    } else {
      ElMessage.error(res.msg || '导入失败')
    }
  }).catch(() => {
    ElMessage.info('已取消导入')
  })
}

// 分页事件
const handleSizeChange = () => loadPersonnel()
const handleCurrentChange = () => loadPersonnel()
</script>

<template>
  <h1>人员信息管理</h1>

  <!-- 搜索栏 -->
  <div class="container">
    <el-form :inline="true" :model="searchForm">
      <el-form-item label="姓名">
        <el-input v-model="searchForm.name" placeholder="请输入人员姓名" />
      </el-form-item>

      <el-form-item label="工号">
        <el-input v-model="searchForm.uid" placeholder="请输入工号" />
      </el-form-item>

      <el-form-item label="类型">
        <el-input v-model="searchForm.type" placeholder="请输入人员类型" />
      </el-form-item>

      <el-form-item label="创建时间">
        <el-date-picker
          v-model="searchForm.date"
          type="daterange"
          range-separator="到"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
        />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" @click="loadPersonnel">查询</el-button>
        <el-button type="info" @click="clearSearch">清空</el-button>
      </el-form-item>
    </el-form>
  </div>

  <!-- 功能按钮 -->
  <div class="container">
    <el-button type="success" @click="importPersonnel">一键导入</el-button>
  </div>

  <!-- 数据表 -->
  <div class="container">
    <el-table :data="personnelList" border style="width: 100%">
      <el-table-column prop="name" label="姓名"  align="center" />
      <el-table-column prop="uid" label="工号"  align="center" />
      <el-table-column prop="type" label="类型"  align="center" />
      <el-table-column prop="workTicket" label="工作票号"  align="center" />
      <el-table-column prop="importTime" label="创建时间"  align="center" />
    </el-table>
  </div>

  <!-- 分页 -->
  <div class="container">
    <el-pagination
      v-model:current-page="currentPage"
      v-model:page-size="pageSize"
      :page-sizes="[5, 10, 20, 50]"
      :background="background"
      layout="total, sizes, prev, pager, next, jumper"
      :total="total"
      @size-change="handleSizeChange"
      @current-change="handleCurrentChange"
    />
  </div>
</template>

<style scoped>
.container {
  margin: 10px 0;
}
</style>
