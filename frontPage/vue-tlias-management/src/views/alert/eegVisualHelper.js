export const EEG_STATE_KEYS = ['fatigue', 'stress', 'anxiety', 'weakness']

export const EEG_STATE_COLORS = {
  fatigue: '#ef4444',
  stress: '#f97316',
  anxiety: '#a855f7',
  weakness: '#3b82f6'
}

export const EEG_EMOTION_TEXT = {
  normal: '正常',
  anxiety: '焦虑',
  stress: '紧张',
  fatigue: '疲劳',
  weakness: '虚弱'
}

export const EEG_STATE_FEATURE_GROUPS = {
  fatigue: [
    { key: 'theta_beta', label: '低频疲劳增强' },
    { key: 'theta_alpha_beta', label: '疲劳低频占比' },
    { key: 'slow_ratio', label: '低频波占比升高' },
    { key: 'engagement', label: '低活跃疲劳倾向', invert: true }
  ],
  stress: [
    { key: 'beta_ratio', label: '高频紧张激活' },
    { key: 'engagement', label: '专注参与度升高' },
    { key: 'gamma_ratio', label: '警觉活跃增强' }
  ],
  anxiety: [
    { key: 'gamma_ratio', label: '高频焦虑波动' },
    { key: 'beta_ratio', label: '紧张激活增强' },
    { key: 'engagement', label: '警觉参与增强' },
    { key: 'theta_beta', label: '低频波动辅助' }
  ],
  weakness: [
    { key: 'slow_ratio', label: '低频波占比升高' },
    { key: 'theta_alpha_beta', label: '低活跃低频倾向' },
    { key: 'alpha_beta', label: '活跃度下降' },
    { key: 'beta_ratio', label: '高频活跃不足', invert: true }
  ]
}

export const EEG_FEATURE_EXPLANATIONS = [
  { state: '疲劳', color: EEG_STATE_COLORS.fatigue, text: '低频波相关特征升高，Theta 与低频占比增强，高频活跃度相对下降。' },
  { state: '紧张', color: EEG_STATE_COLORS.stress, text: 'Beta/Gamma 高频活动和专注参与度升高，表现为高警觉、高压力激活。' },
  { state: '焦虑', color: EEG_STATE_COLORS.anxiety, text: '高频紧张活动升高，同时伴随一定低频波动，表现为紧张且不稳定。' },
  { state: '虚弱', color: EEG_STATE_COLORS.weakness, text: 'Beta 活跃度下降，低频波和 Alpha 相对占比升高，整体呈低活跃状态。' }
]

export function hasZFeatureData(timeline = []) {
  return timeline.some((item) => Object.keys(item?.features?.z || {}).length > 0)
}

export function getZFeatureValue(item, name) {
  return Number(item?.features?.z?.[name] || 0)
}

export function getAverageZFeatureValue(timeline = [], name) {
  const values = timeline.map((item) => getZFeatureValue(item, name)).filter(Number.isFinite)
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
}

export function normalizeZFeatureStrength(value, invert = false) {
  const adjusted = invert ? -Number(value || 0) : Number(value || 0)
  return Math.max(0, Math.min(100, 50 + adjusted * 18))
}

export function getStateFeatureStrengths(timeline = [], stateKey) {
  return (EEG_STATE_FEATURE_GROUPS[stateKey] || []).map((feature) => {
    const average = getAverageZFeatureValue(timeline, feature.key)
    return {
      ...feature,
      average,
      strength: normalizeZFeatureStrength(average, feature.invert)
    }
  })
}

export function getStateFeatureScore(timeline = [], stateKey) {
  const strengths = getStateFeatureStrengths(timeline, stateKey)
  if (!strengths.length) return 0
  return strengths.reduce((sum, item) => sum + item.strength, 0) / strengths.length
}

export function getFeaturePetalArea(features = []) {
  return features.reduce((sum, feature) => sum + Math.max(0, Number(feature.strength || 0)) ** 1.35, 0)
}

export function getFeaturePetals(features = [], centerAngle = 0) {
  const spread = features.length > 3 ? 54 : 42
  const center = { x: 280, y: 280 }
  return features.map((feature, index) => {
    const offset = features.length <= 1 ? 0 : -spread / 2 + (spread * index) / (features.length - 1)
    const angle = (centerAngle + offset) * Math.PI / 180
    const strength = Math.max(0, Math.min(100, Number(feature.strength || 0)))
    const inner = 82
    const outer = 118 + strength * 1.35
    return {
      ...feature,
      x1: Number((center.x + Math.cos(angle) * inner).toFixed(2)),
      y1: Number((center.y + Math.sin(angle) * inner).toFixed(2)),
      x2: Number((center.x + Math.cos(angle) * outer).toFixed(2)),
      y2: Number((center.y + Math.sin(angle) * outer).toFixed(2)),
      strength
    }
  })
}

export function getStateFeatureProfiles(timeline = []) {
  const sectorCenters = { fatigue: -135, stress: -45, anxiety: 45, weakness: 135 }
  const cards = EEG_STATE_KEYS.map((key) => ({
    key,
    name: EEG_EMOTION_TEXT[key],
    color: EEG_STATE_COLORS[key],
    features: getStateFeatureStrengths(timeline, key).map((item) => ({
      ...item,
      strengthText: item.strength.toFixed(1),
      rawText: item.average.toFixed(3)
    }))
  }))
  const maxArea = Math.max(...cards.map((item) => getFeaturePetalArea(item.features)), 0)
  return cards.map((item) => ({
    ...item,
    active: getFeaturePetalArea(item.features) === maxArea && maxArea > 0,
    petals: getFeaturePetals(item.features, sectorCenters[item.key] || 0),
    topFeatures: item.features
      .slice()
      .sort((a, b) => b.strength - a.strength)
      .slice(0, 2)
      .map((feature) => feature.label)
      .join(' / ')
  }))
}

export function getTimelineXAxisData(timeline = []) {
  const total = Math.max(timeline.length, 1)
  return Array.from({ length: total }, (_, index) => index + 1)
}

export function getPlaybackMarkLineData(timeline = [], cursorIndex = -1) {
  if (!timeline.length || cursorIndex < 0) return []
  return [{ xAxis: Math.max(0, Math.min(timeline.length - 1, cursorIndex)), name: '播放位置', lineStyle: { color: '#0f766e', width: 2 }, label: { formatter: '播放位置' } }]
}

export function getStateTrendOption(timeline = [], { cursorIndex = -1, cursorLabel = '播放位置' } = {}) {
  const markLineData = getPlaybackMarkLineData(timeline, cursorIndex)
  if (markLineData.length && cursorLabel) markLineData[0].label = { formatter: cursorLabel }
  return {
    color: EEG_STATE_KEYS.map((key) => EEG_STATE_COLORS[key]),
    tooltip: { trigger: 'axis' },
    legend: { top: 4, textStyle: { fontSize: 14, color: '#334155' } },
    grid: { left: 66, right: 34, top: 58, bottom: 48 },
    xAxis: { type: 'category', boundaryGap: false, data: getTimelineXAxisData(timeline), name: '秒', axisLabel: { fontSize: 14 }, axisLine: { lineStyle: { color: '#9db4c0' } } },
    yAxis: { type: 'value', min: 0, max: 100, name: '状态指数', nameTextStyle: { fontSize: 14, color: '#64748b' }, axisLabel: { fontSize: 13 }, splitLine: { lineStyle: { color: '#e8f0f4' } } },
    series: EEG_STATE_KEYS.map((key) => ({
      name: EEG_EMOTION_TEXT[key],
      type: 'line',
      smooth: true,
      showSymbol: true,
      symbolSize: 8,
      lineStyle: { width: 3.2 },
      markLine: key === 'fatigue'
        ? {
            silent: true,
            symbol: 'none',
            data: [
              { yAxis: 59, name: '阈值 59', lineStyle: { color: '#dc2626', type: 'dashed', width: 2 }, label: { formatter: '阈值 59', fontSize: 13, color: '#dc2626' } },
              ...markLineData
            ]
          }
        : undefined,
      data: timeline.map((item) => Number(item?.indices?.[`${key}_idx`] || 0).toFixed(2)).map(Number)
    }))
  }
}

export function getStateHeatmapOption(timeline = []) {
  const data = []
  timeline.forEach((item, x) => EEG_STATE_KEYS.forEach((key, y) => {
    const value = Number(item?.indices?.[`${key}_idx`] || 0)
    data.push({
      value: [x, y, value],
      itemStyle: {
        borderWidth: value >= 59 ? 2 : 1,
        borderColor: value >= 59 ? EEG_STATE_COLORS[key] : '#d8e6ec'
      }
    })
  }))
  return {
    tooltip: { formatter: ({ value }) => `${EEG_EMOTION_TEXT[EEG_STATE_KEYS[value[1]]]}<br/>第 ${value[0] + 1} 秒：${Number(value[2]).toFixed(1)}${value[2] >= 59 ? '（过阈值）' : ''}` },
    grid: { left: 82, right: 34, top: 26, bottom: 48 },
    xAxis: { type: 'category', data: getTimelineXAxisData(timeline), name: '秒', axisLabel: { fontSize: 14 }, splitArea: { show: true } },
    yAxis: { type: 'category', data: EEG_STATE_KEYS.map((key) => EEG_EMOTION_TEXT[key]), axisLabel: { fontSize: 16, fontWeight: 700 }, splitArea: { show: true } },
    visualMap: { show: false, min: 0, max: 100, dimension: 2, inRange: { color: ['#f7fbff', '#dbeafe', '#93c5fd', '#5eead4', '#fbbf24', '#f97316'] }, outOfRange: { opacity: 1 } },
    series: [{
      type: 'heatmap',
      data,
      label: { show: true, formatter: ({ value }) => value[2] >= 59 ? Number(value[2]).toFixed(0) : '', color: '#172033', fontSize: 16, fontWeight: 800 },
      emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(15,118,110,.35)' } }
    }]
  }
}

export function getFeatureContributionOption(timeline = []) {
  const scores = EEG_STATE_KEYS.map((key) => Number(getStateFeatureScore(timeline, key).toFixed(1)))
  return {
    backgroundColor: 'transparent',
    color: EEG_STATE_KEYS.map((key) => EEG_STATE_COLORS[key]),
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const item = params?.[0]
        const key = EEG_STATE_KEYS[item?.dataIndex || 0]
        const features = getStateFeatureStrengths(timeline, key).map((feature) => `${feature.label}：${feature.strength.toFixed(1)}`).join('<br/>')
        return `${EEG_EMOTION_TEXT[key]}特征贡献：${Number(item?.value || 0).toFixed(1)}<br/>${features}`
      }
    },
    grid: { left: 64, right: 30, top: 42, bottom: 52 },
    xAxis: { type: 'category', data: EEG_STATE_KEYS.map((key) => EEG_EMOTION_TEXT[key]), axisLabel: { fontSize: 16, fontWeight: 700, color: '#334155' }, axisLine: { lineStyle: { color: '#9db4c0' } } },
    yAxis: { type: 'value', min: 0, max: 100, name: '特征强度', nameTextStyle: { fontSize: 14, color: '#64748b' }, axisLabel: { fontSize: 13 }, splitLine: { lineStyle: { color: '#e8f0f4' } } },
    series: [{
      name: '四状态特征贡献',
      type: 'bar',
      barMaxWidth: 78,
      itemStyle: { borderRadius: [10, 10, 0, 0], color: ({ dataIndex }) => EEG_STATE_COLORS[EEG_STATE_KEYS[dataIndex]] },
      label: { show: true, position: 'top', fontSize: 18, fontWeight: 800, formatter: '{c}' },
      markLine: {
        silent: true,
        symbol: 'none',
        data: [
          { yAxis: 50, name: '显示中线', lineStyle: { color: '#64748b', type: 'dashed' }, label: { formatter: '显示中线 50' } },
          { yAxis: 70, name: '明显增强', lineStyle: { color: '#f59e0b', type: 'dashed' }, label: { formatter: '明显增强 70' } }
        ]
      },
      data: scores
    }]
  }
}

export function getRadarOption(timeline = []) {
  const values = EEG_STATE_KEYS.map((key) => Number(getStateFeatureScore(timeline, key).toFixed(1)))
  return {
    backgroundColor: 'transparent',
    tooltip: {},
    radar: {
      radius: '64%',
      indicator: EEG_STATE_KEYS.map((key) => ({ name: `${EEG_EMOTION_TEXT[key]}特征`, max: 100 })),
      axisName: { color: '#334155', fontSize: 15, fontWeight: 700 },
      splitLine: { lineStyle: { color: '#dbe7ec' } },
      splitArea: { areaStyle: { color: ['#fbfdfe', '#f1f7f8'] } },
      axisLine: { lineStyle: { color: '#c7d9df' } }
    },
    series: [{
      type: 'radar',
      data: [
        { value: EEG_STATE_KEYS.map(() => 50), name: '个人基线', symbol: 'none', lineStyle: { color: '#64748b', type: 'dashed', width: 1 }, areaStyle: { color: 'transparent' } },
        { value: values, name: '窗口特征强度', lineStyle: { color: '#0f766e', width: 3 }, itemStyle: { color: '#0891b2' }, areaStyle: { color: 'rgba(20,184,166,.22)' } }
      ]
    }]
  }
}
