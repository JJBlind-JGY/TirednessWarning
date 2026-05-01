# Fatigue Detect Server 项目文档
## 项目概述
本项目 fatigue-detect-server 是一个疲劳检测服务器，包含 common 和 face-service 两个模块。common 模块提供公共依赖，face-service 模块实现具体的面部疲劳检测服务。
主要用于处理人脸疲劳检测相关的视频数据。该服务接收前端上传的视频文件，将视频处理为一帧一帧的图片发送给模型进行处理，并将处理结果通过 WebSocket 推送给客户端。
## 环境要求
Java：JDK 17
Maven：Apache Maven 3.9.6
其它详见pom.xml文件
## 编译步骤
### 1.下载代码到本地
### 2.配置环境变量
确保 JAVA_HOME 和 MAVEN_HOME 环境变量已正确配置。
### 3.使用Maven命令编译项目
## 部署步骤
### 1.修改配置文件
修改 face-service/src/main/resources/application.yml 文件，确保前端、模型连接信息和服务器端口配置正确。
### 2.启动服务
进入编译文件的目录，运行生成的jar文件
