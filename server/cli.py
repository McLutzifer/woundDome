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
import re

# ============================================
# CONFIGURATION - ADAPT TO YOUR SYSTEM
# ============================================
MQTT_BROKER_IP = "10.167.157.26" # Caros IP
MQTT_TOPIC = "esp32cam/cmd"
MQTT_MESSAGE = "capture"
MOSQUITTO_PUB_CMD = r"C:\Program Files\mosquitto\mosquitto_pub.exe"  # Adapt this path if different

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

    print(f"  [OK] Saved image: {filename}")
    return "OK", 200


def start_server():
    """Start Flask server in background thread"""
    global server_running
    UPLOAD_DIR.mkdir(exist_ok=True)
    server_running = True
    print(f"\n[SERVER] Starting on http://0.0.0.0:8000")
    print(f"[SERVER] Saving images to: {UPLOAD_DIR.resolve()}\n")
    app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False, threaded=True, processes=1)


def send_mqtt_capture():
    """Send MQTT command to trigger ESP32 cameras"""
    cmd = [
        MOSQUITTO_PUB_CMD,
        "-h", MQTT_BROKER_IP,
        "-t", MQTT_TOPIC,
        "-m", MQTT_MESSAGE
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("  [MQTT] Capture command sent!")
            return True
        else:
            print(f"  [WARN] MQTT command failed: {result.stderr}")
            return False
    except FileNotFoundError:
        print(f"  [ERROR] mosquitto_pub not found at: {MOSQUITTO_PUB_CMD}")
        print("     Please update MOSQUITTO_PUB_CMD in the configuration section")
        return False
    except subprocess.TimeoutExpired:
        print("  [WARN] MQTT command timed out")
        return False
    except Exception as e:
        print(f"  [ERROR] Error sending MQTT: {e}")
        return False


def run_colmap():
    """Run COLMAP reconstruction"""
    print("\n" + "="*60)
    print("[COLMAP] Running reconstruction...")
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
        print(f"\n[WARN] COLMAP exited with code {result.returncode}")
    else:
        print("\n[OK] COLMAP completed successfully")


def ensure_images_in_workspace():
    """Copy images to colmap_ws/images for LichtFeld-Studio"""
    print("\n[PREP] Preparing workspace for LichtFeld-Studio...")
    
    images_dir = COLMAP_WORKSPACE / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in UPLOAD_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            target = images_dir / f.name
            shutil.copy2(f, target)
            count += 1

    print(f"  [OK] Copied {count} images to workspace")


def run_lichtfeld():
    """Run LichtFeld-Studio training with live status + latest snapshot"""

    print("\n" + "=" * 60)
    print("[LICHTFELD] Running LichtFeld-Studio...")
    print("=" * 60)

    LFS_OUTPUT_DIR.mkdir(exist_ok=True)

    # Folder that always contains the latest snapshot
    latest_dir = LFS_OUTPUT_DIR / "latest"

    # ===== TIME-BASED SNAPSHOT CONFIG =====
    snapshot_interval_seconds = 120  # alle 2 Minuten
    last_snapshot_time = time.time()
    # =====================================

    lfs_dir = Path(LFS_CMD).parent
    total_iterations = 15000

    cmd = [
        LFS_CMD,
        "-d", str(COLMAP_WORKSPACE.resolve()),
        "-o", str(LFS_OUTPUT_DIR.resolve()),
        "-i", str(total_iterations),
        "--headless",
        "--gut",
        "--eval",
        "--save-eval-images",
    ]

    print(f"[LICHTFELD] Command: {' '.join(cmd)}")
    print(f"[LICHTFELD] Working directory: {lfs_dir}")
    print(f"[INFO] Snapshot every {snapshot_interval_seconds} seconds")
    print(f"[INFO] Training will run for {total_iterations} iterations...\n")

    spinner = ["|", "/", "-", "\\"]
    spin_idx = 0
    last_status_time = time.time()

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(lfs_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in process.stdout:
            line = line.strip()

            # ===== STATUS HEARTBEAT =====
            if time.time() - last_status_time > 1.0:
                print(
                    f"\r[TRAINING] Running {spinner[spin_idx % len(spinner)]}",
                    end="",
                    flush=True
                )
                spin_idx += 1
                last_status_time = time.time()

            # ===== TIME-BASED SNAPSHOT =====
            now = time.time()
            if now - last_snapshot_time >= snapshot_interval_seconds:
                last_snapshot_time = now
                print("\n[SNAPSHOT] Updating latest results...")

                # Reset latest/
                if latest_dir.exists():
                    shutil.rmtree(latest_dir)
                latest_dir.mkdir(parents=True, exist_ok=True)

                # Copy newest splat_*.ply
                splats = sorted(
                    LFS_OUTPUT_DIR.glob("splat_*.ply"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )

                if splats:
                    shutil.copy2(splats[0], latest_dir / splats[0].name)

                # Copy newest eval_* folder
                eval_dirs = sorted(
                    LFS_OUTPUT_DIR.glob("eval_*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )

                if eval_dirs:
                    shutil.copytree(
                        eval_dirs[0],
                        latest_dir / eval_dirs[0].name
                    )

                print("[SNAPSHOT] Latest results updated")

            # ===== IMPORTANT LOG LINES =====
            if line and any(k in line.lower() for k in ["error", "warn", "loss", "cuda"]):
                print(f"\n[LICHTFELD] {line}")

        process.wait()
        print()

        if process.returncode != 0:
            print(f"\n[WARN] LichtFeld-Studio exited with code {process.returncode}")
        else:
            print(f"\n[OK] LichtFeld-Studio completed successfully")
            print(f"[OUTPUT] Saved to: {LFS_OUTPUT_DIR.resolve()}")

    except Exception as e:
        print(f"\n[ERROR] LichtFeld-Studio crashed: {e}")

def run_pipeline():
    """Execute the full COLMAP + LichtFeld pipeline"""
    image_count = len(list(UPLOAD_DIR.glob("*.jpg")))
    
    if image_count == 0:
        print("\n[ERROR] No images found in captures directory!")
        print("   Please capture some images first (press X)")
        return

    print(f"\n[PIPELINE] Starting with {image_count} images...")
    
    try:
        run_colmap()
        ensure_images_in_workspace()
        run_lichtfeld()
        print("\n" + "="*60)
        print("[SUCCESS] Pipeline completed successfully!")
        print("="*60)
    except Exception as e:
        print(f"\n[ERROR] Pipeline error: {e}")


def show_menu():
    """Display interactive menu"""
    print("\n" + "="*60)
    print("WOUND DOME - Control Panel")
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
    print(f"\n[STATUS]")
    print(f"  Server: {'Running' if server_running else 'Stopped'}")
    print(f"  Images captured: {image_count}")
    print(f"  MQTT Broker: {MQTT_BROKER_IP}")


def clear_captures():
    """Clear all captured images"""
    if not UPLOAD_DIR.exists():
        print("\n[INFO] No captures directory found")
        return
    
    images = list(UPLOAD_DIR.glob("*.jpg"))
    if not images:
        print("\n[INFO] No images to clear")
        return
    
    confirm = input(f"\n[WARN] Delete {len(images)} images? (yes/no): ").strip().lower()
    if confirm == "yes":
        for img in images:
            img.unlink()
        print(f"[OK] Deleted {len(images)} images")
    else:
        print("[INFO] Cancelled")


def main():
    """Main CLI loop"""
    global server_thread, server_running
    
    print("\n" + "="*60)
    print("WOUND DOME - Starting System")
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
                print("\n[CAPTURE] Triggering capture...")
                send_mqtt_capture()
                
            elif cmd == "Y":
                run_pipeline()
                
            elif cmd == "S":
                show_status()
                
            elif cmd == "C":
                clear_captures()
                
            elif cmd == "Q":
                print("\n[SHUTDOWN] Shutting down...")
                server_running = False
                break
                
            elif cmd == "":
                continue
                
            else:
                print(f"[ERROR] Unknown command: {cmd}")
                show_menu()
                
    except KeyboardInterrupt:
        print("\n\n[SHUTDOWN] Interrupted - shutting down...")
        server_running = False
    
    print("Goodbye!\n")


if __name__ == "__main__":
    main()