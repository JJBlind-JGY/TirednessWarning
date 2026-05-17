# TirednessWarning Windows 便携部署说明

## 使用方式

1. 将 `TirednessWarning-Release` 整个目录复制到目标 Windows 电脑。
2. 修改 `config/go2rtc.yaml` 中的 RTSP 摄像头地址。
3. 如需修改脑电串口，编辑 `config/eeg-devices.json`。
4. 右键运行 `check-env.ps1`，确认文件完整、端口未被占用。
5. 右键运行 `start-all.ps1`。
6. 打开 `http://127.0.0.1:5173/`。

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
- 脑电设备串口驱动
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
