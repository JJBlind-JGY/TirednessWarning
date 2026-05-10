import asyncio
import json
import base64
import os
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import yaml
import websockets

from face_emotion_model import DEFAULT_EMOTION_MODEL, DEFAULT_EYE_MODEL, DEFAULT_YUNET_MODEL, YuNetEmotiEffRecognizer


import warnings
# warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore")
executor = None
recognizer = None
scheduler = None
executor_workers = 0


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_local_path(path):
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)


class ModelPool:
    def __init__(self, max_instances):
        self.pool = Queue(max_instances)
        for _ in range(max_instances):
            MODEL = models.maxvit_t(weights="DEFAULT")
            block_channels = MODEL.classifier[3].in_features
            MODEL.classifier = nn.Sequential(
                nn.AdaptiveAvgPool2d(1),
                nn.Flatten(),
                nn.LayerNorm(block_channels),
                nn.Linear(block_channels, block_channels),
                nn.Tanh(),
                nn.Dropout(0.3),
                nn.Linear(block_channels, 2, bias=False),
            )
            MODEL.to(DEVICE)

            # 加载保存的模型权重
            model_path = "model.pt"  # 保存的模型路径
            MODEL.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))

            # 设置为评估模式
            MODEL.eval()
            self.pool.put(MODEL)

    def get_instance(self):
        return self.pool.get()

    def release(self, instance):
        self.pool.put(instance)


def normlize(x):
    if x > 10:
        x = 10
    if x < 0:
        x = 0
    return x


class LatestFrameScheduler:
    def __init__(self):
        self.latest_frames = {}
        self.ready_users = asyncio.Queue()
        self.queued_users = set()
        self.lock = asyncio.Lock()
        self.received_count = 0
        self.processed_count = 0
        self.dropped_count = 0
        self.error_count = 0
        self.total_inference_ms = 0.0
        self.max_inference_ms = 0.0

    async def submit(self, user_id, frame_data, websocket):
        if not user_id:
            return
        async with self.lock:
            if user_id in self.latest_frames:
                self.dropped_count += 1
            self.latest_frames[user_id] = (frame_data, websocket, time.time())
            self.received_count += 1
            if user_id not in self.queued_users:
                self.queued_users.add(user_id)
                await self.ready_users.put(user_id)

    async def take(self):
        while True:
            user_id = await self.ready_users.get()
            async with self.lock:
                self.queued_users.discard(user_id)
                item = self.latest_frames.pop(user_id, None)
            if item is not None:
                frame_data, websocket, queued_at = item
                return user_id, frame_data, websocket, queued_at

    async def mark_processed(self, inference_ms):
        async with self.lock:
            self.processed_count += 1
            self.total_inference_ms += inference_ms
            self.max_inference_ms = max(self.max_inference_ms, inference_ms)

    async def mark_error(self):
        async with self.lock:
            self.error_count += 1

    async def snapshot(self):
        async with self.lock:
            avg_ms = self.total_inference_ms / self.processed_count if self.processed_count else 0.0
            return {
                "status": "ok",
                "activeUsers": len(self.latest_frames) + len(self.queued_users),
                "queuedUsers": self.ready_users.qsize(),
                "receivedCount": self.received_count,
                "processedCount": self.processed_count,
                "droppedCount": self.dropped_count,
                "errorCount": self.error_count,
                "avgInferenceMs": round(avg_ms, 3),
                "maxInferenceMs": round(self.max_inference_ms, 3),
                "executorWorkers": executor_workers,
                "updatedAt": int(time.time() * 1000),
            }


# 处理任务的协程
async def process_tasks():
    print("Task consumer started")
    while True:
        # 从队列中获取任务
        user_id, frame_data, websocket, queued_at = await scheduler.take()
        started_at = time.perf_counter()
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                executor,
                recognizer.predict_from_bytes,
                frame_data,
                True,
                '.jpg'
            )
        except Exception as e:
            await scheduler.mark_error()
            try:
                await websocket.send(json.dumps({"status": "error", "userId": user_id, "error": str(e)}, ensure_ascii=False))
            except Exception:
                pass
            continue
        inference_ms = (time.perf_counter() - started_at) * 1000
        await scheduler.mark_processed(inference_ms)
        image_b64 = ""
        if result.image_bytes is not None:
            image_b64 = base64.b64encode(result.image_bytes).decode('utf-8')

        response = {
            "status": result.status,
            "userId": user_id,
            "arousal": round(10 - result.fatigue_index, 3),
            "valence": 5,
            "emotionId": result.emotion_id,
            "emotion5": result.emotion5,
            "emotionCat": result.emotion5_zh,
            "emotion7": result.emotion7,
            "score": round(result.score, 3),
            "fatigueIndex": round(result.fatigue_index, 3),
            "fatigueRank": result.fatigue_rank,
            "faceBox": result.face_box,
            "scores7": result.scores7,
            "eyeStatus": result.eye_status,
            "eyeClosed": result.eye_closed,
            "eyeClosedScore": round(result.eye_closed_score * 100, 3),
            "eyeOpenScore": round(result.eye_open_score * 100, 3),
            "eyeBoxes": result.eye_boxes,
            "eyeCheckedAt": int(time.time() * 1000),
            "modelQueuedMs": round(max(0, time.time() - queued_at) * 1000, 3),
            "modelInferenceMs": round(inference_ms, 3),
            "image": image_b64,
        }
        try:
            await websocket.send(json.dumps(response, ensure_ascii=False))
        except Exception as e:
            await scheduler.mark_error()
            print(f"[WARN] send result failed for {user_id}: {e}")
        continue

        # print('get data from queue')
        # 处理视频帧
        face_detected = True
        processed_bytes = frame_data
        processed_bytes, face_detected = await asyncio.get_running_loop().run_in_executor(
            executor,
            process_image_to_bytes,
            frame_data,  # 传入原始帧字节流
            True,  # 告诉函数输入是 Bytes
            '.jpg'
        )
        image_b64 = ""
        if processed_bytes is not None:
            # 把 bytes 转成 Base64 字符串
            image_b64 = base64.b64encode(processed_bytes).decode('utf-8')
        # if not face_detected:
        #     print("[DEBUG] 未检测到人脸，跳过推理，直接返回")
        #     response = {
        #         "arousal": 5,
        #         "userId": user_id,
        #         "status": "no_face",
        #         "message": "未检测到人脸",
        #         "emotionId": -1,
        #         "score": 90,  # 可以给个默认分
        #         "image": image_b64,
        #
        #     }
        #     await websocket.send(json.dumps(response))
        #     continue
        arousal, valence = await asyncio.get_running_loop().run_in_executor(
            executor,
            process_frame,
            processed_bytes
        )
        rate = 90
        if arousal < 4:
            if valence < 4:
                emotion_id = 0
                x = ((4 - arousal) + (4 - valence)) / 2
            else:
                emotion_id = 1
                x = (4 - arousal) + (valence - 4) / 2
        elif arousal > 5.5:
            if valence < 4:
                emotion_id = 2
                x = ((arousal - 5.5) + (4 - valence)) / 2
            else:
                emotion_id = 3
                x = ((arousal - 5.5) + (valence - 4)) / 2
        else:
            x = (arousal + valence) / 2
            emotion_id = 4
        # 发送响应
        x = x / 3
        response = {
            "arousal": arousal,
            "userId": user_id,
            "emotionId": emotion_id,
            "score": x + 90,
            "image": image_b64
        }
        await websocket.send(json.dumps(response))


async def handle_connection(websocket):
    print("Client connected")
    async for message in websocket:
        try:
            # 接收 JSON 数据
            data = json.loads(message)
            user_id = data.get("userId")
            frame_data = data.get("frame")

            # 处理视频帧（假设 frame_data 是 Base64 编码的图片）
            # 这里可以将图片保存到磁盘或进行其他处理
            img_data = base64.b64decode(frame_data)
            # 发给模型识别
            await scheduler.submit(user_id, img_data, websocket)
            # print(f"[DEBUG] Queue size after put: {task_queue.qsize()}")
            # print('put data in queue')
        except json.JSONDecodeError:
            await websocket.send(json.dumps({"error": "Invalid JSON format"}))
        except Exception as e:
            await websocket.send(json.dumps({"error": str(e)}))


def process_frame(frame_data):
    model = None
    try:
        # Base64字节流 -> OpenCV图像
        nparr = np.frombuffer(frame_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(image)
        image = image.convert('RGB')

        context_mean = [0.4690646, 0.4407227, 0.40508908]
        context_std = [0.2514227, 0.24312855, 0.24266963]
        body_mean = [0.43832874, 0.3964344, 0.3706214]
        body_std = [0.24784276, 0.23621225, 0.2323653]
        context_norm = [context_mean, context_std]
        body_norm = [body_mean, body_std]
        body_norm = transforms.Normalize(body_norm[0],
                                         body_norm[1])

        # 预处理
        transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
        tensor = body_norm(transform(image).unsqueeze(0).to(DEVICE))

        # 模型推理
        model = pool.get_instance()
        with torch.no_grad():

            output = model(tensor)
            ### 新增
            valence = (output[:, 0].item() + 1) * 5
            arousal = (output[:, 1].item() + 1) * 5

            if arousal >= 10.0:
                arousal = 10
            if arousal <= 0:
                arousal = 0

        return arousal, valence

        # return 3
    except Exception as e:
        print(f"[ERROR] process_frame: {str(e)}")
        return -1
    finally:
        if model is not None:
            pool.release(model)


# async def start_tasks():
#     asyncio.create_task(process_tasks())
#
#
# async def start_server():
#     async with websockets.serve(handle_connection, "localhost", 8765):
#         print("WebSocket server started on ws://localhost:8765")
#         await asyncio.Future()  # Keep the server running
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/health", "/metrics"):
            self.send_response(404)
            self.end_headers()
            return

        if scheduler is None:
            payload = {"status": "starting", "updatedAt": int(time.time() * 1000)}
        else:
            future = asyncio.run_coroutine_threadsafe(scheduler.snapshot(), HealthHandler.loop)
            payload = future.result(timeout=2)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def start_health_server(host, port, loop):
    HealthHandler.loop = loop
    server = ThreadingHTTPServer((host, port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, name="face-health-server", daemon=True)
    thread.start()
    print(f"Health server started on http://{host}:{port}/health")


def read_config(file_path):
    try:
        with open(file_path, 'r') as file:
            config = yaml.safe_load(file)
            return config
    except FileNotFoundError:
        print(f"错误: 文件 '{file_path}' 未找到")
        return None
    except yaml.YAMLError as e:
        print(f"错误: YAML解析错误: {e}")
        return None


async def main():
    global scheduler
    scheduler = LatestFrameScheduler()

    # 读取文件配置
    config = read_config('config.yaml')  # 请确保该文件存在
    if config:
        port = config.get('port')
        url = config.get('url')
        task_workers = int(config.get('task_workers', 1))
        health_port = int(config.get('health_port', 8766))
    else:
        port = 8765
        url = '0.0.0.0'
        task_workers = 1
        health_port = 8766

    start_health_server(url, health_port, asyncio.get_running_loop())

    # 初始化任务处理器。多个消费者可以并发处理不同摄像头发送来的帧。
    task_processors = [
        asyncio.create_task(process_tasks())
        for _ in range(max(1, task_workers))
    ]
    #     cert_path = config.get('cert_path')  # SSL证书路径
    #     key_path = config.get('key_path')  # 私钥路径
    # if not all([cert_path, key_path]):
    #     print("错误：配置文件中缺少cert_path或key_path")
    #     return
    #
    # try:
    #     ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    #     ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    # except Exception as e:
    #     print(f"SSL证书加载失败: {str(e)}")
    #     return

        # 启动WSS服务
    server = await websockets.serve(
        handle_connection,
        url,
        port,
        # ssl=ssl_context  # 启用SSL
    )
    print(f"WSS server started on ws://{url}:{port}")

    # 启动 WebSocket 服务
    await server.wait_closed()  # 等待服务关闭
    await asyncio.gather(*task_processors)  # 理论上永远不会执行到这里


if __name__ == "__main__":
    config = read_config('config.yaml') or {}
    executor_workers = max(1, int(config.get('executor_workers', 2)))
    executor = ThreadPoolExecutor(max_workers=executor_workers)
    recognizer = YuNetEmotiEffRecognizer(
        yunet_model=resolve_local_path(config.get('yunet_model', DEFAULT_YUNET_MODEL)),
        emotion_model=resolve_local_path(config.get('emotion_model', DEFAULT_EMOTION_MODEL)),
        eye_model=resolve_local_path(config.get('eye_model', DEFAULT_EYE_MODEL)),
        input_size=int(config.get('emotion_input_size', 260)),
        face_score_threshold=float(config.get('face_score_threshold', 0.7)),
        eye_closed_threshold=float(config.get('eye_closed_threshold', 0.65)),
    )
    # 创建一个线程池执行器
    # executor = ThreadPoolExecutor(max_workers=10)
    #
    # # 创建一个异步任务队列
    # task_queue = asyncio.Queue(1000)
    # asyncio.run(start_tasks())
    # asyncio.run(start_server())
    asyncio.run(main())  # 唯一的事件循环入口
