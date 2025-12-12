"""
Wound Dome - Unified CLI Tool
Manages ESP32 camera capture and 3D reconstruction pipeline
"""

import subprocess
import threading
import time
import uuid
from pathlib import Path
from flask import Flask, request
import os
import shutil
import sys

# ============================================
# CONFIGURATION - ADAPT TO YOUR SYSTEM
# ============================================
MQTT_BROKER_IP = "10.66.64.206"
MQTT_TOPIC = "esp32cam/cmd"
MQTT_MESSAGE = "capture"

COLMAP_CMD = r"C:\Users\Admin\wounddome_server\colmap-x64-windows-cuda\COLMAP.bat"
LFS_CMD = r"C:\Users\Admin\repos\LichtFeld-Studio\build\LichtFeld-Studio.exe"

UPLOAD_DIR = Path("captures")
COLMAP_WORKSPACE = Path("colmap_ws")
LFS_OUTPUT_DIR = Path("lfs_output")
# ============================================

# Flask app for image server
app = Flask(__name__)
server_thread = None
server_running = False


@app.route("/upload", methods=["POST"])
def upload_image():
    """Accept raw JPEG data from ESP32 cameras"""
    raw = request.data

    if not raw:
        return "No data received", 400

    # Use random UUID instead of timestamp
    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = UPLOAD_DIR / filename

    with open(filepath, "wb") as f:
        f.write(raw)

    print(f"  ✓ Saved image: {filename}")
    return "OK", 200


def start_server():
    """Start Flask server in background thread"""
    global server_running
    UPLOAD_DIR.mkdir(exist_ok=True)
    server_running = True
    print(f"\n🌐 Server starting on http://0.0.0.0:8000")
    print(f"📁 Saving images to: {UPLOAD_DIR.resolve()}\n")
    app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False)


def send_mqtt_capture():
    """Send MQTT command to trigger ESP32 cameras"""
    cmd = [
        "mosquitto_pub",
        "-h", MQTT_BROKER_IP,
        "-t", MQTT_TOPIC,
        "-m", MQTT_MESSAGE
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("  📸 Capture command sent!")
            return True
        else:
            print(f"  ⚠ MQTT command failed: {result.stderr}")
            return False
    except FileNotFoundError:
        print("  ❌ mosquitto_pub not found. Install Mosquitto MQTT broker.")
        return False
    except subprocess.TimeoutExpired:
        print("  ⚠ MQTT command timed out")
        return False
    except Exception as e:
        print(f"  ❌ Error sending MQTT: {e}")
        return False


def run_colmap():
    """Run COLMAP reconstruction"""
    print("\n" + "="*60)
    print("🔧 Running COLMAP reconstruction...")
    print("="*60)
    
    COLMAP_WORKSPACE.mkdir(exist_ok=True)
    
    img_path = UPLOAD_DIR.resolve()
    ws_path = COLMAP_WORKSPACE.resolve()

    cmd = [
        COLMAP_CMD,
        "automatic_reconstructor",
        "--image_path", str(img_path),
        "--workspace_path", str(ws_path),
    ]

    print(f"Command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True)

    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    if result.returncode != 0:
        print(f"\n⚠ COLMAP exited with code {result.returncode}")
    else:
        print("\n✓ COLMAP completed successfully")


def ensure_images_in_workspace():
    """Copy images to colmap_ws/images for LichtFeld-Studio"""
    print("\n📋 Preparing workspace for LichtFeld-Studio...")
    
    images_dir = COLMAP_WORKSPACE / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in UPLOAD_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            target = images_dir / f.name
            shutil.copy2(f, target)
            count += 1

    print(f"  ✓ Copied {count} images to workspace")


def run_lichtfeld():
    """Run LichtFeld-Studio processing"""
    print("\n" + "="*60)
    print("✨ Running LichtFeld-Studio...")
    print("="*60)
    
    LFS_OUTPUT_DIR.mkdir(exist_ok=True)

    cmd = [
        LFS_CMD,
        "-d", str(COLMAP_WORKSPACE),
        "-o", str(LFS_OUTPUT_DIR),
    ]

    print(f"Command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True)

    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    if result.returncode != 0:
        print(f"\n⚠ LichtFeld-Studio exited with code {result.returncode}")
    else:
        print(f"\n✓ LichtFeld-Studio completed successfully")
        print(f"📁 Output saved to: {LFS_OUTPUT_DIR.resolve()}")


def run_pipeline():
    """Execute the full COLMAP + LichtFeld pipeline"""
    image_count = len(list(UPLOAD_DIR.glob("*.jpg")))
    
    if image_count == 0:
        print("\n❌ No images found in captures directory!")
        print("   Please capture some images first (press X)")
        return

    print(f"\n🚀 Starting pipeline with {image_count} images...")
    
    try:
        run_colmap()
        ensure_images_in_workspace()
        run_lichtfeld()
        print("\n" + "="*60)
        print("✅ Pipeline completed successfully!")
        print("="*60)
    except Exception as e:
        print(f"\n❌ Pipeline error: {e}")


def show_menu():
    """Display interactive menu"""
    print("\n" + "="*60)
    print("🎯 WOUND DOME - Control Panel")
    print("="*60)
    print("  [X] - Trigger camera capture (MQTT)")
    print("  [Y] - Run processing pipeline (COLMAP + LichtFeld)")
    print("  [S] - Show status")
    print("  [C] - Clear captured images")
    print("  [Q] - Quit")
    print("="*60)


def show_status():
    """Show current status"""
    image_count = len(list(UPLOAD_DIR.glob("*.jpg")))
    print(f"\n📊 Status:")
    print(f"  Server: {'🟢 Running' if server_running else '🔴 Stopped'}")
    print(f"  Images captured: {image_count}")
    print(f"  MQTT Broker: {MQTT_BROKER_IP}")


def clear_captures():
    """Clear all captured images"""
    if not UPLOAD_DIR.exists():
        print("\n📁 No captures directory found")
        return
    
    images = list(UPLOAD_DIR.glob("*.jpg"))
    if not images:
        print("\n📁 No images to clear")
        return
    
    confirm = input(f"\n⚠ Delete {len(images)} images? (yes/no): ").strip().lower()
    if confirm == "yes":
        for img in images:
            img.unlink()
        print(f"✓ Deleted {len(images)} images")
    else:
        print("Cancelled")


def main():
    """Main CLI loop"""
    global server_thread, server_running
    
    print("\n" + "="*60)
    print("🏥 WOUND DOME - Starting System")
    print("="*60)
    
    # Start Flask server in background
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)  # Give server time to start
    
    show_menu()
    
    try:
        while True:
            cmd = input("\nCommand: ").strip().upper()
            
            if cmd == "X":
                print("\n📸 Triggering capture...")
                send_mqtt_capture()
                
            elif cmd == "Y":
                run_pipeline()
                
            elif cmd == "S":
                show_status()
                
            elif cmd == "C":
                clear_captures()
                
            elif cmd == "Q":
                print("\n👋 Shutting down...")
                server_running = False
                break
                
            elif cmd == "":
                continue
                
            else:
                print(f"❌ Unknown command: {cmd}")
                show_menu()
                
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted - shutting down...")
        server_running = False
    
    print("Goodbye!\n")


if __name__ == "__main__":
    main()