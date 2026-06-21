# WiFi 版本 Windows 新电脑完整部署手册

本文档用于在一台全新的 Windows 电脑上，从零完成 TirednessWarning WiFi 版本工程部署、ESP32-C3 脑电头盔固件烧录、设备 IP 配置、系统启动和现场验收。

## 1. 系统运行链路

当前 WiFi 版本不是只拷贝发布包就能独立运行。完整链路如下：

```text
ESP32-C3 头盔固件 main.cpp
  -> 头盔连接 2.4GHz WiFi
  -> 暴露 http://头盔IP/api/status 和 http://头盔IP/api/eeg
  -> Windows 新电脑运行 EEG Python 服务读取头盔数据
  -> Java face-service 提供人脸、设备、样本、日志接口
  -> 前端 Vite 页面展示实时监控和样本可视化
```

因此部署分成两部分：

- 电脑端运行环境：Git、JDK 17、Maven、Node.js、Python 3.10、Python 依赖包。
- 硬件端烧录环境：VS Code、PlatformIO、ESP32-C3 USB 驱动、2.4GHz WiFi。

## 2. 安装包下载

建议全部从官方网站下载。

| 工具 | 用途 | 下载地址 |
| --- | --- | --- |
| Git for Windows | 克隆代码仓库 | https://git-scm.com/install/windows |
| JDK 17 | 编译和运行 Spring Boot Java 服务 | https://www.oracle.com/java/technologies/javase/jdk17-archive-downloads.html |
| Apache Maven | Java 依赖下载、测试、打包 | https://maven.apache.org/download.cgi |
| Node.js LTS | 前端 Vue/Vite 依赖安装和运行 | https://nodejs.org/en/download |
| Python 3.10.x | 人脸模型服务和 EEG Python 服务 | https://www.python.org/downloads/release/python-31011/ |
| Visual Studio Code | 打开工程和烧录固件 | https://code.visualstudio.com/download |
| PlatformIO IDE | ESP32-C3 固件编译和烧录 | https://platformio.org/install/ide?install=vscode |

安装顺序建议：

1. Git
2. JDK 17
3. Maven
4. Node.js LTS
5. Python 3.10.x
6. VS Code
7. VS Code 内安装 PlatformIO IDE

## 3. Windows 环境变量检查

安装完成后，重新打开 PowerShell，执行：

```powershell
git --version
java -version
mvn -v
node -v
npm -v
python --version
pip --version
```

期望结果：

- `git --version` 能输出 Git 版本。
- `java -version` 显示 17。
- `mvn -v` 能显示 Maven 版本，并且 Java home 指向 JDK 17。
- `node -v` 和 `npm -v` 能输出版本。
- `python --version` 必须是 `3.10.x`。

如果 `java` 无法识别：

1. 新增系统变量 `JAVA_HOME`，值类似：`C:\Program Files\Java\jdk-17`。
2. 在系统 `Path` 中新增：`%JAVA_HOME%\bin`。
3. 重新打开 PowerShell。

如果 `mvn` 无法识别：

1. 解压 Maven 到例如：`D:\Tools\apache-maven-3.9.x`。
2. 新增系统变量 `MAVEN_HOME`，值为 Maven 解压目录。
3. 在系统 `Path` 中新增：`%MAVEN_HOME%\bin`。
4. 重新打开 PowerShell。

如果 `python` 不是 3.10：

1. 卸载不需要的 Python，或把 Python 3.10 放到 Path 更靠前的位置。
2. 也可以在后续命令中显式使用 Python 3.10 的完整路径。

## 4. 克隆工程

选择一个不包含中文和空格的工作目录，例如 `D:\Project`：

```powershell
cd D:\Project
git clone <你的仓库地址>
cd TirednessWarning
```

确认关键目录存在：

```powershell
dir
dir faceJavaServer
dir facePythonServer
dir frontPage\vue-tlias-management
dir hardware\esp32-c3-eeg-wifi
```

必须能看到：

- `start-all.ps1`
- `faceJavaServer`
- `facePythonServer`
- `frontPage`
- `hardware\esp32-c3-eeg-wifi`

## 5. 安装前端依赖

进入前端目录：

```powershell
cd frontPage\vue-tlias-management
npm install
npm run build
cd ..\..
```

说明：

- `npm install` 下载 Vue、Vite、Element Plus、ECharts 等依赖。
- `npm run build` 用于确认前端可生产构建。
- 如果出现 `Some chunks are larger than 500 KiB`，这是体积提示，不影响系统运行。

## 6. 安装 Java 依赖并测试

进入 Java 服务目录：

```powershell
cd faceJavaServer
mvn.cmd -pl face-service -am test
cd ..
```

说明：

- `-pl face-service -am` 表示构建 `face-service` 以及它依赖的 `common` 模块。
- 测试全部通过后，说明 Java 设备配置、人脸服务接口、样本上传、日志等基础逻辑可用。

如果 Maven 下载依赖很慢，可临时配置国内镜像，但现场优先保证网络稳定。

## 7. 安装 Python 依赖

建议在项目根目录创建独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r facePythonServer\requirements.txt
```

当前 requirements 已包含运行所需核心包：

- `numpy`
- `opencv_python`
- `torch`
- `torchvision`
- `websockets`
- `pyyaml`
- `flask`
- `scipy`
- `mediapipe`
- `onnxruntime`

安装完成后验证：

```powershell
python -c "import flask, scipy, mediapipe, onnxruntime, cv2, torch; print('python deps ok')"
```

如果 `torch` 下载失败，先确认网络；如果 `mediapipe` 安装失败，优先确认 Python 是 3.10 且是 64 位。

## 8. 烧录 ESP32-C3 WiFi 头盔固件

1. 打开 VS Code。
2. 确认左侧扩展里已安装 `PlatformIO IDE`。
3. 在 VS Code 中打开文件夹：`hardware\esp32-c3-eeg-wifi`。
4. 复制配置模板：

```powershell
copy include\wifi_config.example.h include\wifi_config.h
```

5. 编辑 `include\wifi_config.h`：

```cpp
#pragma once

#define EEG_WIFI_SSID "你的2.4GHz WiFi名称"
#define EEG_WIFI_PASSWORD "你的WiFi密码"
#define EEG_DEVICE_ID "eeg-001"
```

注意：

- 必须使用 2.4GHz WiFi。
- `EEG_DEVICE_ID` 每个头盔建议唯一，例如 `eeg-001`、`eeg-002`。
- `wifi_config.h` 不提交到 Git，用于现场私有 WiFi 配置。

6. USB 连接 ESP32-C3。
7. PlatformIO 选择环境：`esp32-c3-devkitm-1`。
8. 点击 `Build`。
9. Build 成功后点击 `Upload`。
10. 打开 PlatformIO Serial Monitor，波特率 `115200`。

成功后会看到类似输出：

```text
EEG WiFi device is ready
Device ID: eeg-001
IP address: 192.168.1.50
Base URL: http://192.168.1.50
Status API: http://192.168.1.50/api/status
EEG API: http://192.168.1.50/api/eeg?after=0&limit=20
```

记录 `Base URL`，并在路由器后台给该设备设置 DHCP 地址保留。

如果无法上传：

- 检查 USB 数据线是否支持数据传输。
- 检查设备管理器中是否出现串口。
- 必要时安装 ESP32-C3 对应 USB 串口驱动。
- 按住 BOOT 再插 USB，或在上传时短按 RESET/BOOT，视开发板型号而定。

## 9. 验证头盔 HTTP 接口

在 Windows 新电脑浏览器打开：

```text
http://头盔IP/api/status
http://头盔IP/api/eeg?after=0&limit=20
```

`/api/status` 应返回设备 ID、IP、RSSI、采样率等状态。

`/api/eeg` 应返回：

- `schemaVersion`
- `deviceId`
- `sampleRateHz`
- `startIndex`
- `returnedUntilIndex`
- `poorSignal`
- `bands`
- `samples`

如果打不开，优先确认电脑和头盔在同一 2.4GHz WiFi，且路由器没有开启 AP 隔离。

## 10. 启动完整系统

回到项目根目录：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-all.ps1
```

脚本会启动多个窗口：

| 服务 | 端口 | 作用 |
| --- | --- | --- |
| go2rtc | 1984 | 摄像头流管理 |
| face-python | 8765 | 人脸、表情、闭眼、打哈欠模型服务 |
| face-java | 8081 | Java 后端接口 |
| eeg-python | 5000 | 读取 WiFi 头盔 EEG 数据 |
| frontend-vite | 5173 | 前端页面 |

打开前端：

```text
http://127.0.0.1:5173/index.html
```

如果 Vite 自动换了端口，以 `frontend-vite` 窗口实际输出为准。

## 11. 在页面配置头盔设备

进入系统设备管理页：

1. 新增脑电设备。
2. 名称填写：`脑电设备1`。
3. 地址填写头盔 Base URL，例如：`http://192.168.1.50`。
4. 保存。
5. 点击测试连接。
6. 测试成功后进入监控页。
7. 绑定人员、脑电设备和摄像头。
8. 等待 EEG 校准完成后观察状态输出。

配置文件对应位置：

```text
frontPage\vue-tlias-management\src\py\config\eeg-devices.json
```

## 12. 摄像头配置

系统使用 go2rtc 管理摄像头流。

常用检查地址：

```text
http://127.0.0.1:1984/
```

摄像头配置来源：

```text
faceJavaServer\face-service\config\camera-config.json
faceJavaServer\go2rtc\go2rtc.yaml
```

如果使用本机摄像头，确认没有其他软件占用摄像头。

如果使用 RTSP 摄像头，先用 VLC 或 go2rtc 页面验证 RTSP 可播放。

## 13. 阈值现场调整

实时融合敏感度在：

```text
frontPage\vue-tlias-management\src\views\alert\useMonitorCenter.js
```

当前值：

```js
const FACE_MIN_CONFIDENCE = 0.38
const ABNORMAL_MIN_RATIO = 0.16
```

含义：

- `FACE_MIN_CONFIDENCE`：人脸置信度低于该值，不进入融合投票。
- `ABNORMAL_MIN_RATIO`：20 秒窗口内某异常状态加权占比达到该值，才可能成为最终状态。

推荐现场档位：

```js
// 当前敏感档
const FACE_MIN_CONFIDENCE = 0.38
const ABNORMAL_MIN_RATIO = 0.16

// 稳妥档
const FACE_MIN_CONFIDENCE = 0.40
const ABNORMAL_MIN_RATIO = 0.18

// 保守档
const FACE_MIN_CONFIDENCE = 0.50
const ABNORMAL_MIN_RATIO = 0.18
```

如果前端正在 Vite 开发模式运行，保存后通常会自动热更新。若是构建后的前端，需要重新执行：

```powershell
cd frontPage\vue-tlias-management
npm run build
```

## 14. 可视化贡献度解释

第二个特征展示界面展示最近 20 秒 EEG 特征贡献总结。

贡献度由特征相对个人基线的 z-score 映射得到：

```text
贡献度 = 50 + 18 × z
```

| 贡献度 | 近似含义 | 对外解释 |
| --- | --- | --- |
| 50 | 个人基线附近 | 当前特征没有明显偏离 |
| 59 | 约高于基线 0.5 个标准差 | 开始出现轻度偏离 |
| 68 | 约高于基线 1.0 个标准差 | 相关异常特征明显增强 |
| 70 | 约高于基线 1.1 个标准差 | 界面标记为明显增强 |
| 86 | 约高于基线 2.0 个标准差 | 强异常特征 |

推荐说明：

- “贡献度超过 59，说明这个状态相关脑电特征开始偏离个人基线。”
- “贡献度超过 68，说明该状态相关特征明显增强。”
- “贡献度超过 70，适合解释为最近 20 秒该异常状态具有较强特征贡献。”
- “如果四个异常状态都低于 59，且 20 秒融合投票没有达到阈值，则当前状态解释为正常。”
- “最终状态不是只看单根柱子，而是结合 EEG 指数、人脸置信度、20 秒投票、闭眼和打哈欠行为规则。”

## 15. 现场常见问题

### PowerShell 禁止运行脚本

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-all.ps1
```

### Python 版本错误

- 确认 `python --version` 是 3.10.x。
- 重新创建 `.venv`。
- 重新安装 requirements。

### EEG 设备离线

1. 浏览器打开 `http://头盔IP/api/status`。
2. 确认电脑和头盔在同一个 WiFi。
3. 确认 WiFi 是 2.4GHz。
4. 检查路由器是否开启 AP 隔离。
5. 检查页面里 `baseUrl` 是否填成 `http://头盔IP`。

### 头盔 IP 改变

- 打开 Serial Monitor 查看 `Base URL`。
- 或登录路由器后台查看 ESP32-C3 当前 IP。
- 给头盔设置 DHCP 地址保留。

### 摄像头无画面

1. 打开 `http://127.0.0.1:1984/`。
2. 检查 go2rtc 是否启动。
3. 检查摄像头是否被其他软件占用。
4. 如果是 RTSP，先用 VLC 验证 RTSP 地址。
5. 查看 Java 服务窗口日志。

### Java 服务启动失败

1. 确认 `java -version` 是 17。
2. 确认 `mvn -v` 可用。
3. 在 `faceJavaServer` 执行：

```powershell
mvn.cmd -pl face-service -am test
```

4. 检查 8081 端口是否被占用。

### 前端打不开

- 查看 `frontend-vite` 窗口实际端口。
- 默认地址是 `http://127.0.0.1:5173/index.html`。
- 如果端口被占用，Vite 可能自动切换到其他端口。

## 16. 验收清单

1. `git --version` 正常。
2. `java -version` 是 17。
3. `mvn -v` 正常。
4. `node -v`、`npm -v` 正常。
5. `python --version` 是 3.10.x。
6. `python -c "import flask, scipy, mediapipe, onnxruntime"` 成功。
7. ESP32-C3 固件上传成功。
8. `http://头盔IP/api/status` 可访问。
9. `http://头盔IP/api/eeg?after=0&limit=20` 返回 samples。
10. `start-all.ps1` 启动所有服务。
11. `http://127.0.0.1:5173/index.html` 可打开。
12. 设备管理页脑电设备测试连接成功。
13. 摄像头画面正常。
14. 监控页能看到 EEG 波形、状态指数、人脸识别结果。
15. 样本展示页可上传 `samples\demo-final-showcase` 下的演示样本。

## 17. 当前工程健康检查记录

本次落地前已做非破坏性检查：

- 前端融合逻辑测试：`npm run test:behavior`，13 个测试全部通过。
- EEG Python 测试：使用项目 Python 环境运行，18 个测试全部通过。
- Java 测试：`mvn.cmd -pl face-service -am test`，15 个测试全部通过，构建成功。
- 前端生产构建：`npm run build` 成功，仅有 chunk 体积较大提示，不影响运行。

注意事项：

- 默认系统 Python 若未安装 Flask，会导致 EEG 测试失败。
- 因此新机器必须按本文档安装 `facePythonServer\requirements.txt`，该文件已包含 `flask` 和 `scipy`。

## 18. 样本目录保留策略

最终只保留：

```text
samples\demo-final-showcase
samples\vedio
samples\samples
```

其他历史样本目录可清理，但必须遵守删除安全规则。批量删除前应先确认目录清单，避免误删最终演示样本。
