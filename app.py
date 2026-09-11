from base64 import b64encode
from io import BytesIO
import math
import os
from pathlib import Path
import socket
from threading import Condition, Lock, Thread
from time import perf_counter, time
import json

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from PIL import Image, ImageDraw
from ultralytics import YOLO
from werkzeug.serving import make_server


app = Flask(__name__)
PROJECT_DIR = Path(__file__).resolve().parent
haptic_app = Flask(
    "haptix_haptic_receiver",
    template_folder=str(PROJECT_DIR / "templates"),
    static_folder=str(PROJECT_DIR / "static"),
)

MODEL_NAME = os.getenv("YOLO_MODEL", "yolo26n.pt")
DETECTION_RANGE_METERS = float(os.getenv("DETECTION_RANGE_METERS", "2"))
CAMERA_HORIZONTAL_FOV_DEGREES = float(os.getenv("CAMERA_HORIZONTAL_FOV_DEGREES", "65"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.35"))
UP_POSITION_MAX_FRAME_RATIO = float(os.getenv("UP_POSITION_MAX_FRAME_RATIO", "0.333"))
HAPTIC_PORT = int(os.getenv("HAPTIC_PORT", "5501"))
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

# Any number of Android phones can connect to this separate receiver service.
haptic_condition = Condition()
latest_haptic = {
    "frame_id": 0, "active": False, "level": "clear", "strength": 0,
    "distance_m": None, "position": None, "horizontal": None, "label": None,
    "pattern": [], "repeat_ms": 0,
    "message": "No obstacle in the haptic zone", "updated_at": None,
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


def vertical_position(box, frame_height):
    """Classify an object by the vertical center of its bounding box."""
    if frame_height <= 0:
        return "unknown"
    center_y_ratio = ((box[1] + box[3]) / 2) / frame_height
    if center_y_ratio <= UP_POSITION_MAX_FRAME_RATIO:
        return "up"
    if center_y_ratio >= 1 - UP_POSITION_MAX_FRAME_RATIO:
        return "down"
    return "center"


def position_message(position):
    return "Object at up position" if position == "up" else None


def horizontal_position(box, frame_width):
    """Classify an object by the horizontal center of its bounding box."""
    if frame_width <= 0:
        return "unknown"
    center_x_ratio = ((box[0] + box[2]) / 2) / frame_width
    if center_x_ratio <= 0.333:
        return "left"
    if center_x_ratio >= 0.667:
        return "right"
    return "center"


def horizontal_message(horizontal):
    if horizontal == "left":
        return "Object at left position"
    if horizontal == "right":
        return "Object at right position"
    return None


def build_haptic_alert(detections):
    """Turn the most urgent in-range detection into a browser haptic cue.

    Browser vibration APIs use duration rather than motor amplitude. Stronger
    feedback is therefore represented by longer, denser bursts and a shorter
    repeat interval. An `up` obstacle gets its own stronger warning pattern.
    """
    candidates = [
        detection for detection in detections
        if detection["distance_m"] is not None and detection["distance_m"] <= DETECTION_RANGE_METERS
    ]
    if not candidates:
        return {
            "active": False, "level": "clear", "strength": 0,
            "distance_m": None, "position": None, "label": None,
            "pattern": [], "repeat_ms": 0,
            "message": "No obstacle in the haptic zone",
        }

    def urgency(detection):
        closeness = 1 - (detection["distance_m"] / DETECTION_RANGE_METERS)
        position_bonus = 20 if detection["position"] == "up" else 0
        horizontal_bonus = 15 if detection.get("horizontal") in {"left", "right"} else 0
        return closeness * 100 + position_bonus + horizontal_bonus

    target = max(candidates, key=urgency)
    distance = target["distance_m"]
    if distance <= 0.5:
        level, strength, pattern, repeat_ms = "danger", 100, [220, 45, 220, 45, 220], 420
    elif distance <= 1.0:
        level, strength, pattern, repeat_ms = "high", 82, [150, 55, 150, 55, 150], 680
    elif distance <= 1.5:
        level, strength, pattern, repeat_ms = "medium", 58, [130, 110, 130], 1050
    else:
        level, strength, pattern, repeat_ms = "low", 35, [140], 1450

    if target["position"] == "up":
        strength = min(100, strength + 25)
        if distance > 1.5:
            pattern, repeat_ms = [220, 55, 220], 1000
        elif distance > 1.0:
            pattern, repeat_ms = [190, 50, 190, 50, 190], 800
        elif distance > 0.5:
            pattern, repeat_ms = [175, 40, 175, 40, 175, 40, 175], 560
        else:
            pattern, repeat_ms = [260, 35, 260, 35, 260, 35, 260], 330
    elif target.get("horizontal") == "left":
        pattern, repeat_ms = [160, 50, 160], 950
        strength = max(strength, 65)
    elif target.get("horizontal") == "right":
        pattern, repeat_ms = [160, 50, 160], 950
        strength = max(strength, 65)

    direction = "up / walking direction" if target["position"] == "up" else target.get("horizontal") or target["position"]
    return {
        "active": True, "level": level, "strength": strength,
        "distance_m": distance, "position": target["position"], "horizontal": target.get("horizontal"), "label": target["label"],
        "pattern": pattern, "repeat_ms": repeat_ms,
        "message": f"{target['label'].title()} at {distance:.1f} m · {direction}",
    }


def publish_haptic(frame_id, detections):
    alert = build_haptic_alert(detections)
    with haptic_condition:
        latest_haptic.update(alert, frame_id=frame_id, updated_at=time())
        haptic_condition.notify_all()


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
        position = det["position"].upper()
        horizontal = det.get("horizontal", "center").upper()
        alert = f" | {ANSI_YELLOW}OBJECT AT UP POSITION{ANSI_RESET}" if det["position"] == "up" else ""
        print(f"  Object {i:<3} | {dist:>6} | {color}● {marker}{ANSI_RESET} | {position} | {horizontal}{alert}")


def draw_detections(image, detections):
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    colors = {"within": "#16d6ad", "outside": "#ff745f", "unknown": "#f6c453"}
    for i, detection in enumerate(detections, 1):
        x1, y1, x2, y2 = detection["box"]
        color = colors[detection["range_state"]]
        horizontal = detection.get("horizontal", "center").upper()
        draw.rectangle((x1, y1, x2, y2), outline=color, width=4)
        label = f"Object {i} · {detection['position'].upper()} · {horizontal}"
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
    return render_template(
        "dashboard.html", range_meters=DETECTION_RANGE_METERS,
        model_name=MODEL_NAME, haptic_port=HAPTIC_PORT,
    )


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
            position = vertical_position(coordinates, image.height)
            horizontal = horizontal_position(coordinates, image.width)
            detections.append({
                "class_id": class_id,
                "label": label,
                "confidence": round(float(box.conf.item()), 4),
                "box": coordinates,
                "distance_m": distance_m,
                "range_state": range_state(distance_m),
                "position": position,
                "position_message": position_message(position),
                "horizontal": horizontal,
                "horizontal_message": horizontal_message(horizontal),
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
        publish_haptic(frame_id, detections)
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


@haptic_app.get("/")
def haptic_receiver():
    return render_template("haptic.html", range_meters=DETECTION_RANGE_METERS)


@haptic_app.get("/manifest.webmanifest")
def haptic_manifest():
    return haptic_app.send_static_file("haptic-manifest.webmanifest")


@haptic_app.get("/service-worker.js")
def haptic_service_worker():
    response = haptic_app.send_static_file("haptic-service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@haptic_app.get("/latest")
def haptic_latest():
    with haptic_condition:
        return jsonify(latest_haptic.copy())


@haptic_app.get("/events")
def haptic_events():
    def stream():
        last_frame_id = -1
        while True:
            with haptic_condition:
                haptic_condition.wait_for(
                    lambda: latest_haptic["frame_id"] != last_frame_id,
                    timeout=15,
                )
                payload = latest_haptic.copy()
                last_frame_id = payload["frame_id"]
            yield f"event: haptic\ndata: {json.dumps(payload)}\n\n"

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


def get_ssl_context():
    """Use a trusted mkcert certificate when one has been created locally.

    The adhoc fallback keeps Docker and first-time development usable, but it
    does not provide the browser trust needed for a reliable mobile PWA.
    """
    certificate = Path(os.getenv("TLS_CERT_FILE", PROJECT_DIR / ".local-certs" / "haptix-cert.pem"))
    private_key = Path(os.getenv("TLS_KEY_FILE", PROJECT_DIR / ".local-certs" / "haptix-key.pem"))
    if certificate.is_file() and private_key.is_file():
        return str(certificate), str(private_key)
    print(f"{ANSI_YELLOW}Trusted TLS certificate not found. Falling back to an adhoc certificate. "
          f"Run ./scripts/create-local-cert.sh to enable trusted HTTPS.{ANSI_RESET}")
    return "adhoc"


if __name__ == "__main__":
    ip = os.environ.get("HOST_IP") or get_local_ip()
    print("\n" + "=" * 58)
    print("  Haptix Vision - rear camera object detection")
    print("=" * 58)
    print(f"\n  Laptop monitor: https://{ip}:5500")
    print(f"  Mobile camera:  https://{ip}:5500/camera")
    print(f"  Haptic phones:  https://{ip}:{HAPTIC_PORT}")
    print("\n  Use the same Wi-Fi network. Run ./scripts/create-local-cert.sh for trusted HTTPS.")
    print("  Detection details will appear here in the terminal.\n")
    ssl_context = get_ssl_context()
    haptic_server = make_server(
        "0.0.0.0", HAPTIC_PORT, haptic_app, ssl_context=ssl_context, threaded=True,
    )
    Thread(target=haptic_server.serve_forever, daemon=True).start()
    app.run(host="0.0.0.0", port=5500, debug=False, ssl_context=ssl_context, threaded=True)
