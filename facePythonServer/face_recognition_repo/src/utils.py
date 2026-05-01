import os
import sys
import cv2
import numpy as np

# ==========================================
# 0. 环境与路径初始化
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, root_dir)
model_repo_path = os.path.join(root_dir, "face_recognition_models")
sys.path.insert(0, model_repo_path)

try:
    import face_recognition

    print("[SYSTEM] 成功关联本地代码与模型！")
except AttributeError as e:
    print(f"[ERROR] 关联失败：{e}")
    sys.exit(1)


# ==========================================
# 核心工具类：UI 绘制与 ROI 提取
# ==========================================
def draw_face_box(image, top, right, bottom, left, label="FACE"):
    """统一的画框与标签函数"""
    cv2.rectangle(image, (left, top), (right, bottom), (0, 255, 0), 2)
    cv2.rectangle(image, (left, top - 35), (right, top), (0, 255, 0), cv2.FILLED)
    cv2.putText(image, label, (left + 6, top - 10),
                cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)


def extract_face_roi(image, top, right, bottom, left, padding=0):
    """
    为未来的表情识别提取高清人脸区域 (ROI)
    增加 padding 可以让人脸周围多保留一点背景，有助于表情模型识别下巴和边缘
    """
    h, w = image.shape[:2]
    # 确保加入 padding 后不会越界
    p_top = max(0, top - padding)
    p_bottom = min(h, bottom + padding)
    p_left = max(0, left - padding)
    p_right = min(w, right + padding)

    return image[p_top:p_bottom, p_left:p_right]


# ==========================================
# 功能一：静态图片检测 
# ==========================================
def process_static_image(image_path, output_dir=None, extract_faces=True):
    """
    处理静态图片，检测人脸并可选将提取的高清人脸单独保存。
    """
    print(f"\n[INFO] 正在加载图片: {image_path}")
    if not os.path.exists(image_path):
        print(f"[ERROR] 找不到图片: {image_path}")
        return

    image = face_recognition.load_image_file(image_path)
    cv2_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    # 优化精度：number_of_times_to_upsample=1 可以把图片放大一倍来寻找小人脸
    # 如果显存允许，甚至可以设为 model="cnn" 获得最强精度
    print("[INFO] 正在分析面部特征 (开启精度优化)...")
    face_locations = face_recognition.face_locations(image, model="hog", number_of_times_to_upsample=1)
    print(f"[INFO] 分析完毕！共发现 {len(face_locations)} 张人脸。")

    # 如果需要保存裁剪的人脸，创建输出目录
    if extract_faces and output_dir and len(face_locations) > 0:
        os.makedirs(output_dir, exist_ok=True)

    for i, (top, right, bottom, left) in enumerate(face_locations):
        # 1. 为将来的表情识别截取高清原图 ROI (加上20像素的padding保留面部边缘)
        if extract_faces and output_dir:
            face_roi = extract_face_roi(cv2_image, top, right, bottom, left, padding=20)
            roi_path = os.path.join(output_dir, f"face_roi_{i}.jpg")
            cv2.imwrite(roi_path, face_roi)
            print(f"[SUCCESS] 提取高清人脸已保存: {roi_path}")

        # 2. 在原图上画框
        draw_face_box(cv2_image, top, right, bottom, left, label=f"FACE_{i}")

    # 保存最终画好框的全图
    if output_dir:
        result_path = os.path.join(output_dir, "full_result.jpg")
        cv2.imwrite(result_path, cv2_image)

    # 智能缩放显示逻辑
    h, w = cv2_image.shape[:2]
    max_size = 1000
    if w > max_size or h > max_size:
        scale = min(max_size / w, max_size / h)
        cv2_image = cv2.resize(cv2_image, (0, 0), fx=scale, fy=scale)

    cv2.imshow('Static Analysis', cv2_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


# ==========================================
# 功能二：字节流处理 (后端 API接口)
# ==========================================
def process_image_to_bytes(input_data, is_bytes=False, output_format='.jpg'):
    """
    接收图片路径或字节流，确保识别精度与输出一致。
    """
    # 1. 统一加载为 OpenCV 的 BGR 格式
    if is_bytes:
        nparr = np.frombuffer(input_data, np.uint8)
        cv2_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    else:
        cv2_image = cv2.imread(input_data)

    if cv2_image is None:
        print("[ERROR] 无法解析图片数据")
        return None, False
    # cv2.imshow("cv2_image", cv2_image)
    # cv2.waitKey(1)
    # 2. 使用 OpenCV 官方函数进行深拷贝转换，确保内存连续性
    rgb_image = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)

    # 3. 【精度优化】增加 number_of_times_to_upsample
    face_locations = face_recognition.face_locations(
        rgb_image,
        model="hog",
        number_of_times_to_upsample=1
    )
    face_detected = len(face_locations) > 0
    if not face_locations:
        print("[DEBUG] 当前图片未检测到人脸")
    else:
        print(f"[DEBUG] 成功检测到 {len(face_locations)} 张人脸，准备绘图...")

    # 4. 绘图
    for (top, right, bottom, left) in face_locations:
        # 调用我们之前封装的高级画框函数
        draw_face_box(cv2_image, top, right, bottom, left, label="DETECTED")

    # 5. 编码回字节流
    success, result_raw = cv2.imencode(output_format, cv2_image)

    if success:
        return result_raw.tobytes(), face_detected
    return None, face_detected


# ==========================================
# 功能三：实时视频流引擎
# ==========================================
def run_face_locator():
    video_capture = cv2.VideoCapture(0)
    if not video_capture.isOpened():
        print("[ERROR] 无法打开摄像头")
        return

    print("\n[INFO] 实时引擎启动！(按 'q' 退出)")
    process_this_frame = True

    while True:
        ret, frame = video_capture.read()
        if not ret: break

        # 缩小画面用于快速检测
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small_frame = small_frame[:, :, ::-1]

        if process_this_frame:
            face_locations = face_recognition.face_locations(rgb_small_frame, model="hog")

        # 将定位坐标放大回原图尺寸，在原图(高分辨率)上画框
        for (top, right, bottom, left) in face_locations:
            top, right, bottom, left = top * 4, right * 4, bottom * 4, left * 4
            draw_face_box(frame, top, right, bottom, left, label="LIVE FACE")

        cv2.imshow('Live Engine', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    video_capture.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    print("\n" + "=" * 30)
    print(" 视觉检测")
    print("=" * 30)
    print("1: 处理静态图 (含自动高清裁剪)")
    print("2: 处理字节流测试")
    print("3: 启动摄像头实时检测")

    choice = input("\n请输入 (1/2/3): ")

    test_img_path = os.path.join(root_dir, "tests", "test_images", "obama.jpg")

    if choice == '1':
        # 将结果输出到项目根目录的 results 文件夹中
        output_folder = os.path.join(root_dir, "results")
        process_static_image(test_img_path, output_dir=output_folder, extract_faces=True)

    elif choice == '2':
        if not os.path.exists(test_img_path):
            print("[ERROR] 测试图片不存在！")
            sys.exit(1)

        with open(test_img_path, 'rb') as f:
            raw_bytes = f.read()
        processed_bytes = process_image_to_bytes(raw_bytes, is_bytes=True)

        if processed_bytes:
            with open(os.path.join(root_dir, "stream_result.jpg"), "wb") as f:
                f.write(processed_bytes)
            print("[SUCCESS] 字节流处理完成。")

    elif choice == '3':
        run_face_locator()
    else:
        print("[ERROR] 指令无效。")
