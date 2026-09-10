Haptix Vision
=============

Run the detector on the laptop, then use the mobile rear camera as the capture device.
Both devices must be on the same Wi-Fi network.

1. Install dependencies: `pip install -r requirements.txt`
2. Start the server: `python app.py`
3. Open `https://<laptop-ip>:5500` on the laptop for the live monitor.
4. Open `https://<laptop-ip>:5500/camera` on the phone for the rear-camera capture page.

Detection details (Object 1, Object 2, etc. with distance and range status) appear in the laptop terminal.

## Docker

Build and start the container:

```bash
docker build -t haptix-vision .
docker run --rm \
  -p 5500:5500 \
  -e HOST_IP=<YOUR_MAC_LAN_IP> \
  haptix-vision
```

Replace `<YOUR_MAC_LAN_IP>` with your Mac's current Wi-Fi/LAN address. Both the phone and Mac must be on the same Wi-Fi network.

Open `https://localhost:5500` on the host, or `https://<YOUR_MAC_LAN_IP>:5500/camera` on a phone connected to the same network. Accept the development certificate warning once.

Runtime settings can be overridden with environment variables, for example:

```bash
docker run --rm -p 5500:5500 -e DETECTION_RANGE_METERS=3 haptix-vision
```

The mobile camera page is installable as a PWA. A local HTTPS certificate is required for mobile camera access; accept the browser's certificate warning once when using the development server.

Distance values are monocular estimates for objects with known reference widths. They are not depth measurements; use a calibrated camera or depth sensor when distance accuracy is critical.
