import { createRouter, createWebHistory } from 'vue-router'

import LayoutView from '@/views/layout/index.vue'
import LoginView from '@/views/login/index.vue'
import AlertView from '@/views/alert/index.vue'
import AlertDetailView from '@/views/alert/detail.vue'
import AlertEegView from '@/views/alert/eeg.vue'
import AlertFaceView from '@/views/alert/face.vue'
import PersonnelManageView from '@/views/manage/personnel.vue'
import DeviceManageView from '@/views/manage/device.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: LayoutView,
      redirect: '/alert',
      children: [
        { path: 'alert', name: 'alert', component: AlertView, meta: { keepAlive: true } },
        { path: 'alert/eeg', name: 'alertEegHome', component: AlertEegView },
        { path: 'alert/face', name: 'alertFaceHome', component: AlertFaceView },
        { path: 'alert/device/:id', name: 'alertDetail', component: AlertDetailView },
        { path: 'alert/device/:id/eeg', name: 'alertEeg', component: AlertEegView },
        { path: 'alert/device/:id/face', name: 'alertFace', component: AlertFaceView },
        { path: 'manage/personnel', name: 'personnelManage', component: PersonnelManageView },
        { path: 'manage/device', name: 'deviceManage', component: DeviceManageView }
      ]
    },
    { path: '/login', name: 'login', component: LoginView }
  ]
})

export default router
