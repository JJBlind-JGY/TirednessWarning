# 项目启动说明

## action: 
由于模型参数太大，超出GitHub限制，没有成功上传面部后端中的facePythonServer/model.pt 和 facePythonServer/face_recognition_repo/face_recognition_models/ 文件夹中的模型，如果需要的话，需要自行下载

## 1. 工程结构

- `.vscode/`：本地编辑器配置。
- `faceJavaServer/`：Java 后端，负责读取摄像头 RTSP 流、把帧推给 Python 微表情模型服务，并把模型结果推给前端。
- `facePythonServer/`：微表情/疲劳识别 Python 模型服务，默认 WebSocket 地址为 `ws://localhost:8765`。
- `frontPage/vue-tlias-management/`：Vue 前端；其中 `src/py/EEG_0417.py` 是真实脑电 SSE 服务，`src/py/EEG_emotion_simulator.py` 是联调用模拟服务。

## 2. 动态配置文件

运行时会自动创建以下 JSON 文件；这些是本机运行数据，不建议上传 GitHub。

- `faceJavaServer/config/personnel-config.json`：人员信息。
- `faceJavaServer/config/camera-config.json`：摄像头信息，包含摄像头通道 `id`、名称和 `rtspUrl`。
- `frontPage/vue-tlias-management/src/py/config/eeg-devices.json`：脑电设备信息，包含 `workerId`、名称和串口 `port`。

如果文件不存在，对应服务会创建空数组 `[]`。前端页面会显示“暂无人员/暂无脑电设备/暂无摄像头设备”的空状态。

## 3. 启动顺序

建议按下面顺序启动。

### 3.1 启动微表情 Python 模型服务

```powershell
cd D:\Space_for_myself\HUST\NanFangDianWang_Proj\Project\TirednessWarning\facePythonServer
pip install -r requirements.txt
python websocket_server.py
```

默认监听配置来自 `facePythonServer/config.yaml`：

```yaml
port: 8765
url: 0.0.0.0
task_workers: 2
model_instances: 2
executor_workers: 4
```

Java 后端通过 `faceJavaServer/face-service/src/main/resources/application.properties` 中的 `websocket.modelServer.url=ws://localhost:8765` 连接它。

### 3.2 启动 Java 摄像头后端

```powershell
cd D:\Space_for_myself\HUST\NanFangDianWang_Proj\Project\TirednessWarning\faceJavaServer
mvn -pl face-service -am spring-boot:run
```

默认端口是 `8081`，配置在：

```text
faceJavaServer/face-service/src/main/resources/application.properties
```

前端通过 `/face-api` 代理到 `8081`，通过 `/wss` 连接 Java 的 SockJS/STOMP 推送接口。

### 3.3 启动脑电 Python SSE 服务

```powershell
cd D:\Space_for_myself\HUST\NanFangDianWang_Proj\Project\TirednessWarning
pip install flask numpy scipy pyserial
python frontPage\vue-tlias-management\src\py\EEG_0417.py
```

默认监听 `5000`，前端通过 `/eeg` 代理访问。

如需改脑电配置文件位置，可设置环境变量：

```powershell
$env:EEG_CONFIG_FILE="D:\path\to\eeg-devices.json"
python frontPage\vue-tlias-management\src\py\EEG_0417.py
```

### 3.4 启动前端

```powershell
cd D:\Space_for_myself\HUST\NanFangDianWang_Proj\Project\TirednessWarning\frontPage\vue-tlias-management
npm install
npm run dev -- --host 127.0.0.1
```

Vite 会输出实际访问地址，例如：

```text
http://127.0.0.1:5175/
```

## 4. 动态设备链路确认

### 4.1 脑电链路

1. 在前端“设备管理”中新增脑电设备，填写串口，例如 `COM5`。
2. 前端调用 `POST /eeg/devices`，写入 `eeg-devices.json`。
3. 在总览或详情页选择脑电设备后，绑定卡片保存 `workerId`。
4. 点击“接入脑电”时，前端请求：

```text
/eeg/stream?workerId=<前端选择的workerId>
```

5. `EEG_0417.py` 根据 `workerId` 从 `eeg-devices.json` 查找串口并启动对应 `EEGWorker`。

结论：脑电不是写死串口，最终读取的是前端选择的 `workerId` 对应串口。

### 4.2 摄像头链路

1. 在前端“设备管理”中新增摄像头设备，填写通道 ID 和 RTSP 地址。
2. 前端调用 `POST /face-api/faceDetectService/cameras`，写入 `camera-config.json`。
3. Java 后端刷新摄像头流任务；每个摄像头配置对应一个拉流线程。
4. Java 拉流时调用：

```java
faceDetectService.processVideo(rtspUrl, cameraId)
```

5. 模型结果按 `cameraId` 推送到：

```text
/topic/face_fatigue/{cameraId}
```

6. 前端详情页选择摄像头后，保存 `faceChannelId`，并订阅对应 topic。

结论：摄像头不是写死 RTSP 或 `camera_001`，最终订阅和展示的是前端选择的 `faceChannelId`。

## 5. 多卡片与并发能力

- 多个卡片可选择不同 `workerId` 和不同 `faceChannelId`。
- 脑电后端按 `workerId` 创建独立 `EEGWorker` 线程；不同 worker 可并发读取。
- 同一个脑电 worker 被多个卡片选择时，前端复用同一条 SSE 流，避免重复打开同一个串口。
- 摄像头后端按摄像头 ID 创建独立 RTSP 拉流线程。
- 摄像头帧处理线程池按 CPU 核心数扩展，降低多摄像头情况下排队延迟。
- 微表情 Python 模型服务支持通过 `facePythonServer/config.yaml` 调整 `task_workers`、`model_instances`、`executor_workers`。显存或内存不足时先调小 `model_instances`。
- 前端切换脑电设备时，如果当前正在接入，会断开旧 worker 并接入新 worker。
- 前端切换摄像头设备时，会取消旧 topic 并订阅新 topic。

## 6. 不建议上传 GitHub 的内容

这些内容已经写入根目录 `.gitignore`：

- 运行配置和本机数据：
  - `faceJavaServer/config/`
  - `frontPage/vue-tlias-management/src/py/config/`
- 构建产物：
  - `**/target/`
  - `frontPage/vue-tlias-management/dist/`
- 依赖目录：
  - `**/node_modules/`
- 缓存和日志：
  - `**/__pycache__/`
  - `*.log`
  - `frontPage/vue-tlias-management/vite-dev*.log`
- 本地 IDE 配置：
  - `.idea/`
  - `.vscode/`
- 大模型/本地视频数据：
  - `facePythonServer/model.pt`
  - `facePythonServer/video/`
  - `facePythonServer/face_recognition_repo/results/`

如果 `model.pt` 必须随项目分发，建议使用 Git LFS 或在 README 中提供下载方式，不建议直接提交普通 Git。

## 7. GitHub 上传建议

提交前建议检查：

```powershell
git status --short
```

重点确认不要提交：

- `node_modules`
- `dist`
- `target`
- `*.log`
- `config/*.json`
- `model.pt`
- 本机 `.idea`、`.vscode`

建议提交：

- Java/Python/Vue 源码
- `pom.xml`
- `package.json`、`package-lock.json`
- `requirements.txt`
- `PROJECT_STARTUP.md`
- `.gitignore`
