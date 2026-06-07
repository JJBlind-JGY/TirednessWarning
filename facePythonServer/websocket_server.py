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
import numpy as np

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


# === MediaPipe FaceLandmarker 替换 open-closed-eye.onnx 的闭眼检测 ====================
# 设计目标: 改动最小，MediaPipe 不可用时禁用闭眼检测。
# - 不修改 face_emotion_model.YuNetEmotiEffRecognizer 的源码
# - 仅在 main 里运行时把 recognizer._predict_eye_state 替换成 MediaPipe 版本
# - 替换函数返回的 dict 与原方法接口完全兼容（status/closed/closed_score/open_score/boxes）
# - 加载失败 / 模型缺失 / mediapipe 没装时禁用闭眼检测，不回退到旧 ONNX 模型
import cv2  # face_emotion_model 已经依赖 cv2，显式 import 让本文件自包含

DEFAULT_MP_MODEL = os.path.join(BASE_DIR, "models", "face_landmarker.task")
DEFAULT_YAWN_MODEL = os.path.join(BASE_DIR, "models", "yawn_model_80_lite.onnx")
yawn_detector = None


def _load_mediapipe_landmarker(model_path):
    """加载 MediaPipe FaceLandmarker (with blendshapes)。失败抛异常。"""
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    options = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=False,
        num_faces=1,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(options)
    return landmarker, mp


def _make_mediapipe_eye_state_fn(landmarker, mp_module, blink_threshold=0.50):
    """返回一个 (image, face_box, landmarks) -> dict 的函数，
    格式与 face_emotion_model.YuNetEmotiEffRecognizer._predict_eye_state 完全兼容。

    面向多线程 ThreadPoolExecutor: MediaPipe FaceLandmarker.detect 不保证线程安全，
    所以加锁串行化（与原 recognizer 内部锁策略一致）。"""
    BLINK_LEFT = "eyeBlinkLeft"
    BLINK_RIGHT = "eyeBlinkRight"
    lock = threading.Lock()

    def predict_eye(image, face_box, landmarks):
        # face_box / landmarks 由 YuNet 给出，但 MediaPipe 自己在全图上跑，不依赖它们
        try:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            mp_img = mp_module.Image(image_format=mp_module.ImageFormat.SRGB, data=rgb)
            with lock:
                res = landmarker.detect(mp_img)
        except Exception as exc:
            print(f"[MP EYE ERROR] {exc}")
            return {"status": "invalid_eye", "closed": None,
                    "closed_score": 0.0, "open_score": 0.0, "boxes": []}

        if not res.face_blendshapes:
            return {"status": "invalid_eye", "closed": None,
                    "closed_score": 0.0, "open_score": 0.0, "boxes": []}

        scores = {b.category_name: b.score for b in res.face_blendshapes[0]}
        bl = float(scores.get(BLINK_LEFT, 0.0))
        br = float(scores.get(BLINK_RIGHT, 0.0))
        avg = (bl + br) / 2.0
        closed = avg >= blink_threshold

        # 估算两只眼睛的 bbox 给前端画框 / 兼容下游 _draw_eye_result(boxes[0] 索引)
        # 优先用 YuNet landmarks (前 2 个是左右眼中心)，否则用 face_box 估算
        eye_boxes = []
        if landmarks and len(landmarks) >= 2:
            side = 18
            for i in range(2):
                cx, cy = int(landmarks[i][0]), int(landmarks[i][1])
                eye_boxes.append([cx - side, cy - side, cx + side, cy + side])
        elif face_box and len(face_box) >= 4:
            x1, y1, x2, y2 = face_box
            fw = max(1, x2 - x1)
            fh = max(1, y2 - y1)
            ec = int(y1 + fh * 0.38)
            side = max(12, int(min(fw * 0.13, fh * 0.11)))
            for cx_ratio in (0.35, 0.65):
                cx = int(x1 + fw * cx_ratio)
                eye_boxes.append([cx - side, ec - side, cx + side, ec + side])

        return {
            "status": "closed" if closed else "open",
            "closed": bool(closed),
            "closed_score": float(avg),
            "open_score": float(max(0.0, 1.0 - avg)),
            "boxes": eye_boxes,
        }

    return predict_eye


def _patch_recognizer_with_mediapipe(recognizer, model_path, blink_threshold):
    """把 recognizer._predict_eye_state 换成 MediaPipe 实现。成功返回 True。"""
    if not os.path.exists(model_path):
        print(f"[WARN] MediaPipe model not found ({model_path}); eye detection disabled.")
        return False
    try:
        landmarker, mp_module = _load_mediapipe_landmarker(model_path)
    except ImportError as exc:
        print(f"[WARN] mediapipe package not installed ({exc}); eye detection disabled.")
        return False
    except Exception as exc:
        print(f"[WARN] MediaPipe load failed ({exc}); eye detection disabled.")
        return False

    recognizer._predict_eye_state = _make_mediapipe_eye_state_fn(
        landmarker, mp_module, blink_threshold=blink_threshold
    )
    print(f"[INFO] MediaPipe FaceLandmarker enabled for eye detection: {model_path}")
    print(f"[INFO]   blink_threshold = {blink_threshold}")
    return True


def _disable_eye_state_fn(image, face_box, landmarks):
    """Eye detection is disabled on main; develop keeps the full eye-alert feature."""
    return {"status": "disabled", "closed": None,
            "closed_score": 0.0, "open_score": 0.0, "boxes": []}


class HippoYDMouthOpenDetector:
    def __init__(self, model_path, threshold=0.80):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"HippoYD yawn model not found: {model_path}")
        import onnxruntime as ort

        session_options = ort.SessionOptions()
        session_options.log_severity_level = 3
        self.session = ort.InferenceSession(
            model_path,
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )
        yawn_input = self.session.get_inputs()[0]
        self.input_name = yawn_input.name
        self.output_name = self.session.get_outputs()[0].name
        self.input_height = int(yawn_input.shape[1])
        self.input_width = int(yawn_input.shape[2])
        self.threshold = float(threshold)
        self.lock = threading.Lock()

    def predict_from_bytes(self, frame_data, face_box):
        image = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
        if image is None or not face_box:
            return {"mouthOpen": None, "yawnScore": 0.0}
        score = self._predict_score(image, face_box)
        return {"mouthOpen": bool(score >= self.threshold), "yawnScore": score}

    def _predict_score(self, frame_bgr, face_box):
        mouth_crop = self._crop_mouth_region(frame_bgr, face_box)
        if mouth_crop is None:
            return 0.0
        resized = cv2.resize(mouth_crop, (self.input_width, self.input_height), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        blob = (gray.astype(np.float32) / 255.0).reshape(1, self.input_height, self.input_width, 1)
        with self.lock:
            output = self.session.run([self.output_name], {self.input_name: blob})[0]
        return float(np.squeeze(output))

    @staticmethod
    def _crop_mouth_region(frame_bgr, face_box):
        x1, y1, x2, y2 = [int(value) for value in face_box]
        h, w = frame_bgr.shape[:2]
        face_w = x2 - x1
        face_h = y2 - y1
        if face_w <= 0 or face_h <= 0:
            return None

        mx1 = max(0, int(x1 + face_w * 0.12))
        mx2 = min(w, int(x2 - face_w * 0.12))
        my1 = max(0, int(y1 + face_h * 0.48))
        my2 = min(h, int(y2 + face_h * 0.08))
        if mx2 - mx1 < 12 or my2 - my1 < 12:
            return None
        return frame_bgr[my1:my2, mx1:mx2]


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

        mouth_result = {"mouthOpen": None, "yawnScore": 0.0}
        if yawn_detector is not None:
            try:
                mouth_result = yawn_detector.predict_from_bytes(frame_data, result.face_box)
            except Exception as exc:
                print(f"[YAWN ERROR] {exc}")

        checked_at = int(time.time() * 1000)
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
            "eyeCheckedAt": checked_at,
            "mouthOpen": mouth_result.get("mouthOpen"),
            "yawnScore": round(float(mouth_result.get("yawnScore") or 0.0) * 100, 3),
            "mouthCheckedAt": checked_at,
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

    # === 接入 MediaPipe 替换闭眼检测（失败则禁用闭眼，不回退旧 ONNX）===
    recognizer._predict_eye_state = _disable_eye_state_fn
    _mp_model_path = resolve_local_path(config.get('mediapipe_eye_model', DEFAULT_MP_MODEL))
    _mp_blink_threshold = float(config.get('mp_blink_threshold', 0.50))
    _patch_recognizer_with_mediapipe(recognizer, _mp_model_path, _mp_blink_threshold)

    try:
        _yawn_model_path = resolve_local_path(config.get('yawn_model', DEFAULT_YAWN_MODEL))
        _yawn_threshold = float(config.get('yawn_threshold', 0.80))
        yawn_detector = HippoYDMouthOpenDetector(_yawn_model_path, _yawn_threshold)
        print(f"[INFO] HippoYD mouth-open detection enabled: {_yawn_model_path}")
        print(f"[INFO]   yawn_threshold = {_yawn_threshold}")
    except Exception as exc:
        yawn_detector = None
        print(f"[WARN] HippoYD mouth-open detection disabled ({exc}).")
    # 创建一个线程池执行器
    # executor = ThreadPoolExecutor(max_workers=10)
    #
    # # 创建一个异步任务队列
    # task_queue = asyncio.Queue(1000)
    # asyncio.run(start_tasks())
    # asyncio.run(start_server())
    asyncio.run(main())  # 唯一的事件循环入口
