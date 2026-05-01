# 项目概述

本项目是一个基于 Python 的 WebSocket 服务器，用于接收客户端发送的视频帧（Base64 编码的图片），并使用预训练的深度学习模型对这些帧进行处理，预测唤醒度（arousal）。处理结果将以 JSON 格式返回给客户端。
# 环境要求
Python 3.8
你可以使用以下命令安装所需的库：
`pip install -r requirements.txt`
# 编译步骤
本项目是纯 Python 项目，无需编译。但在运行之前，你需要确保已经安装了所有依赖库，并且下载了预训练模型 4Amodel.pt。
下载预训练模型
请确保 4Amodel.pt 文件存在于项目根目录下。如果该文件缺失，你需要从相应的存储位置下载。
# 部署步骤
2. 配置环境
安装依赖库： `pip install -r requirements.txt`
3. 运行服务器
在项目根目录下，运行以下命令启动 WebSocket 服务器：
python websocket_server.py
4. 验证服务器是否运行
如果服务器成功启动，你将在终端看到以下输出：
WebSocket server started on ws://配置文件指定的路径和端口号
Task consumer started

5. 后端连接
后端可以使用 WebSocket 协议连接到 ws://+指定的路径和端口号，并发送包含 userId 和 frame（Base64 编码的图片）的 JSON 数据。服务器将处理这些数据，最后将包含唤醒度预测结果的 JSON 响应推送过去。