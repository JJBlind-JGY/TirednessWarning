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
