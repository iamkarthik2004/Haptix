# Haptix Vision

Haptix Vision runs object detection on a laptop while an Android phone supplies its rear-camera video. The laptop is the monitor and detector host. A second HTTPS service sends live haptic alerts to two Android receiver phones.

Both devices must be on the same Wi-Fi network.

## Local workflow

### 1. Prepare the laptop

Install the Python dependencies, then create a trusted local HTTPS certificate. HTTPS is required for Android browser camera access and PWA installation.

```bash
pip install -r requirements.txt
./scripts/create-local-cert.sh
python app.py
```

The certificate script uses `mkcert`, writes the certificate and private key to `.local-certs/`, and includes the laptop's current LAN IP. Those files are local-only and excluded from Git.

If `mkcert` is not installed, on Fedora run:

```bash
sudo dnf install -y mkcert nss-tools
```

Keep the server running. It prints the current monitor and camera URLs, for example:

```text
Laptop monitor: https://192.168.x.x:5500
Mobile camera:  https://192.168.x.x:5500/camera
Haptic phones:  https://192.168.x.x:5501
```

### 2. Trust the development CA on Android

The laptop trusts the local CA automatically. Android must trust it separately before Chrome can use the HTTPS camera page without a certificate warning.

1. On the laptop, locate the CA file with `mkcert -CAROOT`. The file to copy is `rootCA.pem`.
2. Transfer only that public CA file to the Android phone, for example over USB or a private file-transfer method.
3. In Android Settings, search for **Install certificate**, choose **CA certificate**, then select `rootCA.pem` and confirm the security warning. Menu names vary by Android version.
4. Use the same Wi-Fi network, then open `https://<laptop-ip>:5500/camera` in Chrome on the phone.

Do not copy the private key from `.local-certs/`, and do not distribute this development CA outside devices you control.

### 3. Install the Android PWA

The install recommendation appears only for Android phones. On the `/camera` page in Chrome, tap **Install** when the recommendation is shown, then approve Chrome's prompt. The installed app opens directly to the camera page in a focused window.

The laptop page at `https://<laptop-ip>:5500` remains a normal browser-based monitor. It does not register the PWA service worker or show an install recommendation.

If the install recommendation was dismissed, clear the Haptix site data in Chrome and reopen `/camera` to show it again.

### 4. Use the detector

After opening the camera page, grant Chrome camera permission and select the rear camera if necessary. Frames are sent to the laptop for analysis; the annotated output is shown in the laptop monitor, while object, distance, and range-status details are printed in the laptop terminal.

Open `https://<laptop-ip>:5501` on each of the two Android haptic phones. The page offers an **Install Haptix Receiver** recommendation; tap **Install**, then tap **Enable phone vibration** once in the installed app. Both phones receive the same server-sent haptic signal. No feedback is sent for objects farther than 2 m by default. Inside the haptic zone, the vibration bursts become denser as the estimated distance decreases: low (2–1.5 m), medium (1.5–1 m), high (1–0.5 m), and danger (0.5 m or less). An object in the `up` position has a stronger, distinct burst pattern at every distance band.

The receiver port defaults to `5501`; change it with `HAPTIC_PORT`, for example `HAPTIC_PORT=5601 python app.py`. The browser Vibration API controls duration and rhythm but not hardware vibration amplitude, so the stronger signals are encoded as longer, denser, more frequent bursts.

Objects whose bounding-box center falls in the upper third of the camera frame are returned to the laptop with `position: "up"` and `position_message: "Object at up position"`. The monitor highlights these objects and the terminal logs `OBJECT AT UP POSITION`. Adjust the upper-zone threshold with `UP_POSITION_MAX_FRAME_RATIO` (default: `0.333`).

Run `./scripts/create-local-cert.sh` again whenever the laptop moves to a network with a different LAN IP. Restart the server afterwards.

## Docker workflow

Create the certificate on the laptop before starting the container, then mount it read-only:

```bash
docker build -t haptix-vision .
docker run --rm \
  -p 5500:5500 -p 5501:5501 \
  -e HOST_IP=<YOUR_LAPTOP_LAN_IP> \
  -v "$PWD/.local-certs:/certs:ro" \
  -e TLS_CERT_FILE=/certs/haptix-cert.pem \
  -e TLS_KEY_FILE=/certs/haptix-key.pem \
  haptix-vision
```

Replace `<YOUR_LAPTOP_LAN_IP>` with the laptop's current Wi-Fi/LAN address. Complete the Android CA-trust step above before opening the camera URL on the phone.

Runtime settings can be overridden with environment variables, for example:

```bash
docker run --rm -p 5500:5500 -p 5501:5501 -e DETECTION_RANGE_METERS=3 haptix-vision
```

## Notes

Distance values are monocular estimates for objects with known reference widths. They are not depth measurements; use a calibrated camera or depth sensor when distance accuracy is critical.
