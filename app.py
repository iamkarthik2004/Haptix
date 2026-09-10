from base64 import b64encode
from io import BytesIO
import math
import os
import socket
from threading import Lock
from time import perf_counter, time

from flask import Flask, jsonify, render_template, request
from PIL import Image, ImageDraw
from ultralytics import YOLO


app = Flask(__name__)

MODEL_NAME = os.getenv("YOLO_MODEL", "yolo26n.pt")
DETECTION_RANGE_METERS = float(os.getenv("DETECTION_RANGE_METERS", "2"))
CAMERA_HORIZONTAL_FOV_DEGREES = float(os.getenv("CAMERA_HORIZONTAL_FOV_DEGREES", "65"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.35"))
model = YOLO(MODEL_NAME)

REFERENCE_WIDTHS_METERS = {
    "person": 0.45, "bicycle": 0.60, "car": 1.80, "motorcycle": 0.75,
    "bus": 2.55, "truck": 2.50, "boat": 1.80, "bench": 1.20,
    "chair": 0.45, "couch": 1.80, "bed": 1.60, "dining table": 1.20,
    "tv": 1.00, "laptop": 0.34, "bottle": 0.07, "backpack": 0.32,
    "suitcase": 0.42, "stop sign": 0.75, "potted plant": 0.35,
}

ANSI_GREEN = "\033[92m"
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_BOLD = "\033[1m"
ANSI_RESET = "\033[0m"

latest_lock = Lock()
latest_frame = {
    "frame_id": 0, "image": None, "detections": [], "inference_ms": None,
    "received_at": None, "source_size": None,
}


def estimate_distance(label, box, frame_width):
    reference_width = REFERENCE_WIDTHS_METERS.get(label.lower())
    box_width = max(box[2] - box[0], 1)
    if reference_width is None or frame_width <= 0:
        return None
    focal_length_px = frame_width / (2 * math.tan(math.radians(CAMERA_HORIZONTAL_FOV_DEGREES / 2)))
    return round(reference_width * focal_length_px / box_width, 2)


def range_state(distance_m):
    if distance_m is None:
        return "unknown"
    if distance_m <= DETECTION_RANGE_METERS:
        return "within"
    return "outside"


def print_terminal_detections(frame_id, detections):
    count = len(detections)
    if count == 0:
        print(f"{ANSI_BOLD}[Frame #{frame_id}]{ANSI_RESET} 0 objects detected")
        return

    print(f"\n{ANSI_BOLD}[Frame #{frame_id}]{ANSI_RESET} {count} object{'s' if count != 1 else ''} detected:")
    for i, det in enumerate(detections, 1):
        dist = f"{det['distance_m']:.1f} m" if det["distance_m"] is not None else "--"
        state = det["range_state"]
        if state == "within":
            color = ANSI_GREEN
            marker = "WITHIN"
        elif state == "outside":
            color = ANSI_RED
            marker = "OUTSIDE"
        else:
            color = ANSI_YELLOW
            marker = "UNKNOWN"
        print(f"  Object {i:<3} | {dist:>6} | {color}● {marker}{ANSI_RESET}")


def draw_detections(image, detections):
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    colors = {"within": "#16d6ad", "outside": "#ff745f", "unknown": "#f6c453"}
    for i, detection in enumerate(detections, 1):
        x1, y1, x2, y2 = detection["box"]
        color = colors[detection["range_state"]]
        draw.rectangle((x1, y1, x2, y2), outline=color, width=4)
        label = f"Object {i}"
        label_box = draw.textbbox((x1, y1), label)
        label_top = max(0, y1 - (label_box[3] - label_box[1]) - 10)
        draw.rectangle((x1, label_top, label_box[2] + 8, y1), fill=color)
        draw.text((x1 + 4, label_top + 3), label, fill="#07131a")
    return annotated


def encode_frame(image):
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=76, optimize=True)
    return "data:image/jpeg;base64," + b64encode(buffer.getvalue()).decode("ascii")


@app.get("/")
def dashboard():
    return render_template("dashboard.html", range_meters=DETECTION_RANGE_METERS, model_name=MODEL_NAME)


@app.get("/camera")
def camera():
    return render_template("camera.html", range_meters=DETECTION_RANGE_METERS)


@app.post("/analyze")
def analyze():
    frame = request.files.get("frame")
    if frame is None:
        return jsonify({"error": "missing frame"}), 400
    try:
        image = Image.open(BytesIO(frame.read())).convert("RGB")
        started_at = perf_counter()
        result = model(image, verbose=False, conf=MIN_CONFIDENCE)[0]
        inference_ms = round((perf_counter() - started_at) * 1000)
        detections = []
        for box in result.boxes:
            class_id = int(box.cls.item())
            coordinates = [round(value, 1) for value in box.xyxy[0].tolist()]
            label = result.names[class_id]
            distance_m = estimate_distance(label, coordinates, image.width)
            detections.append({
                "class_id": class_id,
                "label": label,
                "confidence": round(float(box.conf.item()), 4),
                "box": coordinates,
                "distance_m": distance_m,
                "range_state": range_state(distance_m),
            })

        with latest_lock:
            latest_frame["frame_id"] += 1
            frame_id = latest_frame["frame_id"]

        print_terminal_detections(frame_id, detections)

        annotated_image = draw_detections(image, detections)
        with latest_lock:
            latest_frame["image"] = encode_frame(annotated_image)
            latest_frame["detections"] = detections
            latest_frame["inference_ms"] = inference_ms
            latest_frame["received_at"] = time()
            latest_frame["source_size"] = [image.width, image.height]
            response = {
                "frame_id": frame_id,
                "detections": detections,
                "inference_ms": inference_ms,
            }
        return jsonify(response)
    except Exception as error:
        app.logger.exception("Frame analysis failed")
        return jsonify({"error": str(error)}), 400


@app.get("/latest")
def latest():
    with latest_lock:
        return jsonify(latest_frame.copy())


@app.get("/health")
def health():
    return jsonify({"status": "ok", "model": MODEL_NAME, "range_meters": DETECTION_RANGE_METERS})


@app.get("/manifest.webmanifest")
def manifest():
    return app.send_static_file("manifest.webmanifest")


@app.get("/service-worker.js")
def service_worker():
    response = app.send_static_file("service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


if __name__ == "__main__":
    ip = os.environ.get("HOST_IP") or get_local_ip()
    print("\n" + "=" * 58)
    print("  Haptix Vision - rear camera object detection")
    print("=" * 58)
    print(f"\n  Laptop monitor: https://{ip}:5500")
    print(f"  Mobile camera:  https://{ip}:5500/camera")
    print("\n  Use the same Wi-Fi network and accept the local certificate once.")
    print("  Detection details will appear here in the terminal.\n")
    app.run(host="0.0.0.0", port=5500, debug=False, ssl_context="adhoc")
