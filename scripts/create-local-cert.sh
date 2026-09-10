#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
certificate_dir="${TLS_CERT_DIR:-$project_dir/.local-certs}"
certificate_file="$certificate_dir/haptix-cert.pem"
key_file="$certificate_dir/haptix-key.pem"

if ! command -v mkcert >/dev/null 2>&1; then
  echo "mkcert is required. Fedora: sudo dnf install -y mkcert" >&2
  exit 1
fi

lan_ip="${HOST_IP:-$(python3 - <<'PY'
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.connect(("8.8.8.8", 80))
    print(sock.getsockname()[0])
finally:
    sock.close()
PY
)}"

mkdir -p "$certificate_dir"
mkcert -install
mkcert -cert-file "$certificate_file" -key-file "$key_file" \
  localhost 127.0.0.1 ::1 "$lan_ip"

echo "Trusted certificate created for https://$lan_ip:5500"
echo "Certificate: $certificate_file"
echo "Key:         $key_file"
echo "Phone CA:    $(mkcert -CAROOT)/rootCA.pem"
