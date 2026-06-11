# TirednessWarning Windows 便携部署说明

## 使用方式

1. 将 `TirednessWarning-Release` 整个目录复制到目标 Windows 电脑。
2. 修改 `config/go2rtc.yaml` 中的 RTSP 摄像头地址。
3. 将电脑和脑电设备连接到同一个 2.4GHz WiFi，并在路由器中为每台设备设置 DHCP 地址保留。
4. 在 `config/eeg-devices.json` 中填写每台设备的 `baseUrl`，例如 `http://192.168.1.50`。
5. 右键运行 `check-env.ps1`，确认文件完整、端口未被占用。
6. 右键运行 `start-all.ps1`。
7. 打开 `http://127.0.0.1:5173/`。

## 目标电脑不需要安装

- JDK
- Maven
- Node.js
- npm
- Python
- pip

发布包已经包含 Java runtime、Python 虚拟环境、Java JAR、Vue `dist`、Python 服务、模型文件和 go2rtc。

完整包必须包含：

- `runtime/java/bin/java.exe`
- `runtime/python/venv/Scripts/python.exe`
- `apps/face-python/model.pt`
- `apps/face-python/models/*.onnx`
- `apps/front/dist/index.html`
- `apps/face-service/face-service.jar`

## 目标电脑可能仍需要

- 摄像头或采集卡驱动
- 允许电脑访问脑电设备所在的局域网
- Windows 防火墙放行本机端口
- 允许 PowerShell 脚本运行

如果 PowerShell 被策略拦截，可以在当前目录用 PowerShell 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-all.ps1
```

## 默认端口

- 前端页面：`5173`
- go2rtc：`1984`
- Python 模型服务：`8765`
- Python 模型健康检查：`8766`
- Java 服务：`8081`
- EEG 服务：`5000`

## 脑电 WiFi 设备

固件工程位于 `hardware/esp32-c3-eeg-wifi`。使用 VS Code PlatformIO 打开该目录，
复制 `include/wifi_config.example.h` 为 `include/wifi_config.h`，填写 2.4GHz WiFi
名称、密码和唯一设备 ID 后编译烧录。

设备配置示例：

```json
[
  {
    "workerId": 1,
    "value": 1,
    "name": "脑电设备 1",
    "baseUrl": "http://192.168.1.50",
    "enabled": true
  }
]
```

可先在浏览器访问 `http://设备IP/api/status` 验证固件在线，再在系统设备管理页
点击“测试连接”。

## 日志

所有服务日志写入 `logs/` 目录。启动失败时优先查看对应的 `.err.log` 文件。

## 构建发布包

在开发机项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1
```

如果开发机默认 `python.exe` 不是 Python 3.10，请显式指定：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1 -PythonExe "C:\Path\To\Python310\python.exe"
```

如果已经有可用的 Conda/venv 环境，推荐直接复制整个环境：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1 -PythonEnv "D:\project_APP\Anaconda\anaconda\envs\nanwang"
```

如果只想生成不带 Java/Python runtime 的轻量包：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1 -SkipRuntime
```

轻量包只适合已经配置好 Java 和 Python 环境的机器，不建议交付给普通目标电脑。
