import subprocess
import os

avi_path = r"D:\code\server\video\20251113_094028.avi"
rtsp_url = "rtsp://192.168.1.8:554/type=0&id=3"

if not os.path.exists(avi_path):
    raise FileNotFoundError(f"视频不存在: {avi_path}")

cmd = [
    "ffmpeg",
    "-re",                      # 按原始帧率读取，模拟实时流
    "-stream_loop", "-1",        # 循环推流；不想循环就删掉这两项
    "-i", avi_path,

    "-an",                      # 不推音频；需要音频就删掉
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-tune", "zerolatency",
    "-pix_fmt", "yuv420p",

    "-f", "rtsp",
    "-rtsp_transport", "tcp",
    rtsp_url
]

print("开始推流...")
print(" ".join(cmd))

process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="ignore"
)

try:
    for line in process.stdout:
        print(line, end="")
except KeyboardInterrupt:
    print("\n停止推流")
    process.terminate()