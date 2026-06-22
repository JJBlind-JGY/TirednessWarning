export function normalizeCameraRecord(item, index = 0, go2rtcBaseUrl = '') {
  const id = String(item.id || item.faceChannelId || item.cameraId || `camera_${String(index + 1).padStart(3, '0')}`)
  const name = String(item.name || `摄像头${index + 1}`)
  const sourceType = String(item.sourceType || 'rtsp').toLowerCase() === 'local' ? 'local' : 'rtsp'
  const deviceIndex = Math.max(0, Number.parseInt(item.deviceIndex ?? 0, 10) || 0)
  const rtspUrl = String(item.rtspUrl || '')
  const streamName = String(item.streamName || item.go2rtcStream || id)
  const streamUrl = `${go2rtcBaseUrl}/stream.html?src=${encodeURIComponent(streamName)}&mode=webrtc`
  return { id, name, sourceType, deviceIndex, rtspUrl, streamName, streamUrl, label: `${name} / ${id}` }
}

export function usesModelFramePreview(camera) {
  return !camera?.streamUrl
}


export function normalizeEegDeviceRecord(item, index = 0) {
  const value = Number(item.value ?? item.workerId ?? index + 1)
  const workerId = value
  const name = String(item.name || `????${value}`)
  const rawTransport = String(item.transport || '').toLowerCase()
  const hasPort = Boolean(String(item.port || '').trim())
  const hasBaseUrl = Boolean(String(item.baseUrl || '').trim())
  const transport = rawTransport || (hasPort && !hasBaseUrl ? 'serial' : 'wifi')
  const baud = Number.parseInt(item.baud ?? 57600, 10) || 57600
  const inputUrl = String(item.baseUrl || '').trim().replace(/\/+$/, '')
  const baseUrl = inputUrl && !inputUrl.includes('://') ? `http://${inputUrl}` : inputUrl
  const port = String(item.port || '').trim()
  const endpoint = transport === 'serial' ? `${port || '\u672a\u914d\u7f6e\u4e32\u53e3'} / ${baud}` : baseUrl
  const label = item.label || (endpoint ? `${name} / ${endpoint}` : name)
  return { value, workerId, name, transport, baseUrl, port, baud, label }
}
