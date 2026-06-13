import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeCameraRecord, usesModelFramePreview } from '../src/views/alert/monitorDeviceConfig.js'

test('local camera defaults to device zero and go2rtc preview', () => {
  const camera = normalizeCameraRecord({
    id: 'local_camera_0',
    name: '本机摄像头',
    sourceType: 'local'
  }, 0, 'http://127.0.0.1:1984')

  assert.equal(camera.deviceIndex, 0)
  assert.match(camera.streamUrl, /stream\.html\?src=local_camera_0&mode=webrtc/)
  assert.equal(usesModelFramePreview(camera), false)
})

test('RTSP camera keeps the go2rtc preview URL', () => {
  const camera = normalizeCameraRecord({
    id: 'camera_01',
    sourceType: 'rtsp',
    rtspUrl: 'rtsp://192.168.1.8/live',
    streamName: 'camera_01'
  }, 0, 'http://127.0.0.1:1984')

  assert.equal(camera.deviceIndex, 0)
  assert.match(camera.streamUrl, /stream\.html\?src=camera_01&mode=webrtc/)
  assert.equal(usesModelFramePreview(camera), false)
})
