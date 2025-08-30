python -m venv venv && source venv/bin/activate
pip install fastapi uvicorn[standard] python-multipart
export UVICORN_HOST=0.0.0.0
export UVICORN_PORT=8000
export ADMIN_BEARER="Bearer change-me-admin"     # change me
export DEVICE_BEARER="Bearer change-me-device"   # share with ESP32 firmware
python app.py
# open: http://<pi-ip>:8000/ui  (same Wi-Fi)
