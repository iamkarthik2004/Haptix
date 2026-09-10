FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOLO_MODEL=yolo26n.pt \
    YOLO_CONFIG_DIR=/app/.config/Ultralytics

WORKDIR /app

RUN mkdir -p /app/.config/Ultralytics

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py yolo26n.pt ./
COPY static ./static
COPY templates ./templates

EXPOSE 5500

CMD ["python", "app.py"]