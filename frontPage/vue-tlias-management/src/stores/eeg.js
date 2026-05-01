// src/stores/eeg.js
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const useEegStore = defineStore('eeg', () => {
  // --- 状态 ---
  const rawWave      = ref([])
  const fatigueIndex = ref(0)
  const deltaPower   = ref(0)
  const thetaPower   = ref(0)
  const alphaPower   = ref(0)
  const betaPower    = ref(0)
  const fatigueLevel = ref('')
  const accuracy     = ref(0)
  const recordHistory = ref([])

  // --- 历史记录 ---
  watch(fatigueIndex, val => {
    recordHistory.value.push({
      timestamp: new Date().toLocaleTimeString(),
      value: val,
      level: fatigueLevel.value
    })
    if (recordHistory.value.length > 10)
      recordHistory.value.shift()
  })

  let evt = null
  let reconnectTimer = null

  // --- 启动 SSE ---
  function startSse({ port }) {
    if (!port) {
      console.warn('[SSE] 缺少 port 参数')
      return
    }

    stopSse() // 避免重复连接
    const url = `/eeg/stream?port=${encodeURIComponent(port)}`
    console.log('[SSE] 连接:', url)

    evt = new EventSource(url)

    evt.onopen = () => {
      console.log('[SSE] 已连接')
      clearTimeout(reconnectTimer)
    }

    evt.onmessage = e => {
      try {
        const d = JSON.parse(e.data)
        rawWave.value      = d.rawWave || []
        fatigueIndex.value = d.fatigueIndex || 0
        deltaPower.value   = (d.deltaPower ?? 0) * 100
        thetaPower.value   = (d.thetaPower ?? 0) * 100
        alphaPower.value   = (d.alphaPower ?? 0) * 100
        betaPower.value    = (d.betaPower  ?? 0) * 100
        fatigueLevel.value = d.fatigueLevel || ''
        accuracy.value     = d.acc ?? 0
      } catch (err) {
        console.warn('[SSE] 数据解析失败:', err)
      }
    }

    evt.onerror = err => {
      console.warn('[SSE] 连接错误:', err)
      evt.close()
      evt = null
      scheduleReconnect(port)
    }
  }

  // --- 自动重连 ---
  function scheduleReconnect(port) {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      console.log('[SSE] 正在重连...')
      startSse({ port })
    }, 5000)
  }

  // --- 关闭 SSE ---
  function stopSse() {
    if (evt) {
      evt.close()
      evt = null
    }
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  return {
    rawWave,
    fatigueIndex,
    deltaPower,
    thetaPower,
    alphaPower,
    betaPower,
    fatigueLevel,
    recordHistory,
    accuracy,
    startSse,
    stopSse
  }
})
