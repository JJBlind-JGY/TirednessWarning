FROM python:3.8

WORKDIR ./
EXPOSE 8765
ADD . .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

RUN echo "deb https://mirrors.aliyun.com/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian-security/ bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    # 更新源缓存
    apt-get update

RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list
RUN sed -i 's/security.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list


RUN apt-get update
RUN apt-get install ffmpeg libsm6 libxext6  -y


RUN pip install -r requirements.txt

CMD ["python", "./websocket_server.py"]