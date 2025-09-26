"""
server_mqtt.py

Raspberry Pi-side server for your wound-healing photo tunnel prototype.

What this file provides:
- Human-facing Web UI (enter patient ID + wound location + Start)
- MQTT-based triggering for ESP32 cameras
- HTTP image upload endpoint for ESP32s (multipart JPEG)
- Session storage on disk (images + session.json)
- Status page to monitor arrivals
- Simple bearer "secrets" for admin/UI and devices

This is designed for a LAN prototype. You can later add HTTPS/TLS and move
in-memory dictionaries into SQLite if you want persistence across restarts.
"""

import os
import time
import json
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Set, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

# ---- MQTT (Pi publishes commands; ESP32 subscribes) -------------------------
# You need a broker (e.g., Mosquitto) running in LAN; ESP32s connect there.
import paho.mqtt.client as mqtt


# =========================
# Configuration via ENV VAR
# =========================

# Admin bearer protects operator endpoints like /trigger and /sessions/*.
# This is the "password" the UI uses under the hood.
ADMIN_BEARER = os.getenv("ADMIN_BEARER", "Bearer change-me-admin")

# Device bearer is a shared secret for ESP32 HTTP endpoints (/upload) if you keep /register or add more.
# For this prototype we only enforce token on /upload, but you could add headers too.
DEVICE_BEARER = os.getenv("DEVICE_BEARER", "Bearer change-me-device")

# Where to write sessions on disk
STORAGE = Path(os.getenv("STORAGE_ROOT", "data/uploads"))
STORAGE.mkdir(parents=True, exist_ok=True)

# Basic timing/token settings
DEFAULT_TRIGGER_DELAY_MS = int(os.getenv("DEFAULT_TRIGGER_DELAY_MS", "300"))
TOKEN_TTL_SEC = int(os.getenv("TOKEN_TTL_SEC", "120"))

# MQTT broker config (the Pi often runs Mosquitto locally)
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "pi_server")
MQTT_PASS = os.getenv("MQTT_PASS", "change-me")
MQTT_RIG_PREFIX = os.getenv("MQTT_RIG_PREFIX", "wound/rig01")  # topic root, e.g., wound/rig01


# =========================
# App + CORS
# =========================
app = FastAPI(title="Wound 3D Capture (LAN + MQTT)", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # LAN only; for prod, restrict this
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


# =========================
# In-memory state (MVP)
# You can swap this for SQLite later.
# =========================

# Known cameras (if you keep a /register or parse MQTT birth messages into here later)
CAMERAS: Dict[str, dict] = {}  # camera_id -> {"last_seen_ms": int, "firmware": str?}

# Mapping session -> targeted cameras (string IDs)
SESSION_TARGETS: Dict[str, Set[str]] = {}

# Mapping session -> uploads per camera
# e.g., SESSION_UPLOADS["session_X"]["cam01"] = { filename, ts_ms, sha256, size }
SESSION_UPLOADS: Dict[str, Dict[str, dict]] = {}


# =========================
# Utilities
# =========================
def now_ms() -> int:
    """Server time in epoch milliseconds (int)."""
    return int(time.time() * 1000)


def require_admin(auth: Optional[str]):
    """Guard for operator endpoints (/trigger, /sessions/*)."""
    if auth != ADMIN_BEARER:
        raise HTTPException(status_code=401, detail="unauthorized (admin)")


def session_dir(session_id: str) -> Path:
    """
    Ensure the session directory structure exists and return its path.
    Structure:
      STORAGE/<session_id>/
        images/
        session.json
    """
    d = STORAGE / session_id
    (d / "images").mkdir(parents=True, exist_ok=True)
    return d


def sha256_file(p: Path) -> str:
    """Compute SHA-256 of a file for integrity/debugging."""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def make_upload_token(session_id: str, camera_id: str, ttl_sec: int) -> str:
    """
    Create a simple time-limited token to guard /upload.
    Format: session:camera:expiry_ms:sha1( DEVICE_BEARER + payload )
    This is NOT strong crypto; good enough for LAN prototype.
    """
    expiry = now_ms() + ttl_sec * 1000
    payload = f"{session_id}:{camera_id}:{expiry}".encode()
    # NOTE: we reuse DEVICE_BEARER as a "secret". In production, keep a distinct secret.
    sig = hashlib.sha1(DEVICE_BEARER.encode() + payload).hexdigest()
    return f"{session_id}:{camera_id}:{expiry}:{sig}"


def parse_upload_token(token: str):
    """
    Parse and validate token (format enforced above).
    Returns (session_id, camera_id, expiry_ms, sig_hex)
    """
    try:
        s, c, exp_s, sig = token.split(":")
        return s, c, int(exp_s), sig
    except Exception:
        raise HTTPException(status_code=400, detail="invalid token")


# =========================
# MQTT client (publisher)
# We use this to publish "capture" commands to cameras.
# =========================
_mqtt = mqtt.Client(client_id="pi_server")
_mqtt.username_pw_set(MQTT_USER, MQTT_PASS)
_mqtt.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
_mqtt.loop_start()  # background thread

def mqtt_publish(topic: str, payload: dict, qos: int = 1, retain: bool = False):
    """
    Publish a JSON payload to MQTT.
    We use QoS 1 for at-least-once delivery (good trade-off for commands).
    """
    data = json.dumps(payload, separators=(",", ":"))
    _mqtt.publish(topic, data, qos=qos, retain=retain)


# =========================
# Device (ESP32) HTTP endpoint(s)
# We keep only /upload here; all triggering flows via MQTT.
# =========================

@app.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    camera_id: str = Form(...),     # ESP32's ID (e.g., cam01)
    session_id: str = Form(...),    # assigned by server in /trigger and sent via MQTT
    token: str = Form(...),         # per-camera token generated in /trigger
    ts_ms: Optional[int] = Form(None),  # ESP32's capture timestamp (optional)
):
    """
    ESP32 sends a multipart/form-data POST with JPEG + fields above.
    We verify the token matches the session/camera and is not expired,
    then store the file to STORAGE/<session>/images/<camera_id>.jpg
    """
    s_id, cam, expiry, sig = parse_upload_token(token)
    if s_id != session_id or cam != camera_id:
        raise HTTPException(status_code=401, detail="token mismatch")
    if now_ms() > expiry:
        raise HTTPException(status_code=401, detail="token expired")

    # Save image
    d = session_dir(session_id) / "images"
    dest = d / f"{camera_id}.jpg"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    digest = sha256_file(dest)

    # Record arrival in memory
    rec = {
        "filename": str(dest),
        "ts_ms": ts_ms or now_ms(),
        "sha256": digest,
        "size": dest.stat().st_size,
    }
    SESSION_UPLOADS.setdefault(session_id, {})
    SESSION_UPLOADS[session_id][camera_id] = rec

    return {"ok": True, "stored_as": dest.name, "sha256": digest}


# =========================
# Operator/Admin API
# - /trigger creates a session and publishes MQTT "capture" commands
# - /sessions/<id>/status shows arrivals & missing
# =========================

@app.post("/trigger")
def trigger_capture(
    authorization: Optional[str] = Header(None),
    # "session label" metadata collected by UI form:
    patient_id: Optional[str] = Form(None),
    wound_location: Optional[str] = Form(None),
    operator: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    # optional manual session_id; otherwise timestamp-based
    session_id: Optional[str] = Form(None),
    # optional CSV to target a subset of cameras; otherwise all known (from UI perspective)
    cameras_csv: Optional[str] = Form(None),
    # override default delay to scheduled capture time
    delay_ms: Optional[int] = Form(None),
):
    """
    Creates a new session, writes session.json,
    generates per-camera upload tokens, and broadcasts MQTT capture commands.

    The ESP32s should be subscribed to:
      - f"{MQTT_RIG_PREFIX}/cmd/capture"        (broadcast)
      - f"{MQTT_RIG_PREFIX}/cmd/capture/<id>"   (per-camera with token)

    We send a generic message on the broadcast, and a tokenized message per camera on the per-camera topic.
    """
    require_admin(authorization)

    # 1) Determine session_id and capture time
    sid = session_id or datetime.now(timezone.utc).strftime("session_%Y%m%dT%H%M%S")
    delay = delay_ms if delay_ms is not None else DEFAULT_TRIGGER_DELAY_MS
    capture_at = now_ms() + max(100, int(delay))

    # 2) Decide which cameras to target
    # For MQTT, you can target "all cameras that subscribe", but for status accounting,
    # we need a target list. If none provided, use the cameras we currently "know".
    # (You can also store a static list or let the UI list cameras.)
    if cameras_csv:
        targets = [c.strip() for c in cameras_csv.split(",") if c.strip()]
    else:
        targets = sorted(list(CAMERAS.keys()))  # may be empty on first runs

    if not targets:
        # We allow "zero targets" in case you still want to broadcast (new cams may join),
        # but it's usually better to add cameras via CAMERAS or provide CSV.
        # Here we choose to block to avoid confusion.
        raise HTTPException(status_code=400, detail="no cameras targeted/known")

    # 3) Initialize session directory + write session.json (metadata)
    sd = session_dir(sid)
    meta = {
        "session_id": sid,
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "patient_id": patient_id or "temp",
        "wound_location": wound_location or "unspecified",
        "operator": operator or "",
        "notes": notes or "",
        "targeted_cameras": targets,
        "upload_url": f"http://{os.getenv('PI_HOSTNAME', 'pi.local')}:{os.getenv('UVICORN_PORT','8000')}/upload",
        "capture_at_ms": capture_at,
        "rig_topic_prefix": MQTT_RIG_PREFIX,
    }
    with (sd / "session.json").open("w") as f:
        json.dump(meta, f, indent=2)

    # 4) Remember targets and prepare upload bookkeeping
    SESSION_TARGETS[sid] = set(targets)
    SESSION_UPLOADS.setdefault(sid, {})

    # 5) Publish MQTT commands
    # Broadcast payload (no token inside, informational)
    base_payload = {
        "capture_id": sid,
        "capture_at_ms": capture_at,
        "upload": {
            "url": meta["upload_url"],
            "session_id": sid
        },
        "camera_ids": targets,
        "delay_ms": delay,
    }
    # Broadcast command (cameras can ignore if they require per-camera token)
    mqtt_publish(f"{MQTT_RIG_PREFIX}/cmd/capture", base_payload, qos=1, retain=False)

    # Per-camera command with token
    for cam in targets:
        token = make_upload_token(sid, cam, TOKEN_TTL_SEC)
        per_cam_payload = dict(base_payload)
        per_cam_payload["upload"] = dict(base_payload["upload"])
        per_cam_payload["upload"]["token"] = token
        mqtt_publish(f"{MQTT_RIG_PREFIX}/cmd/capture/{cam}", per_cam_payload, qos=1, retain=False)

    # 6) Return a short summary to the UI
    return {"session_id": sid, "capture_at_ms": capture_at, "targeted_cameras": targets}


@app.get("/sessions/{session_id}/status")
def session_status(session_id: str, authorization: Optional[str] = Header(None)):
    """
    Operator endpoint to inspect which cameras have uploaded vs. are still missing.
    """
    require_admin(authorization)
    targets = SESSION_TARGETS.get(session_id, set())
    uploads = SESSION_UPLOADS.get(session_id, {})
    return {
        "session_id": session_id,
        "targeted": sorted(list(targets)),
        "received": sorted(list(uploads.keys())),
        "missing": sorted(list(targets - set(uploads.keys()))),
        "uploads": uploads,  # includes filename/sha256/size/ts_ms for each received camera
    }


# =========================
# Super-simple Web UI
# - /ui : capture form
# - /ui/start : POST -> calls /trigger
# - /ui/status/<sid> : live status (auto-refresh)
# =========================

def html_page(body: str) -> HTMLResponse:
    """Tiny HTML wrapper + styles."""
    css = """
    <style>
      body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;max-width:860px}
      .card{border:1px solid #ddd;border-radius:12px;padding:16px;margin:16px 0}
      input,button,textarea{padding:10px;border-radius:8px;border:1px solid #ccc;width:100%;box-sizing:border-box}
      label{font-weight:600;margin-top:8px;display:block}
      button{cursor:pointer}
      .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
      .muted{color:#666}
      table{border-collapse:collapse;width:100%}
      th,td{border-bottom:1px solid #eee;padding:8px;text-align:left}
      .ok{color:green}.warn{color:#b15b00}.err{color:#b00020}
      .pill{display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid #ccc;margin-right:4px}
    </style>
    """
    return HTMLResponse(f"<!doctype html><meta charset='utf-8'><title>Wound 3D Capture</title>{css}{body}")


@app.get("/ui")
def ui_home():
    """
    Simple form: patient ID, wound location, optional operator/notes, optional CSV cameras, delay.
    """
    cams = sorted(CAMERAS.keys())
    cams_badge = f"<span class='muted'>{len(cams)} camera(s) known</span>" if cams else "<span class='warn'>no cameras known</span>"
    body = f"""
    <h1>Wound 3D Capture (LAN + MQTT)</h1>
    <div class="card">
      <form method="post" action="/ui/start">
        <div class="grid">
          <div><label>Patient ID (pseudonym)</label><input name="patient_id" placeholder="e.g. pA17" required></div>
          <div><label>Wound Location</label><input name="wound_location" placeholder="e.g. left_ankle" required></div>
        </div>
        <div class="grid">
          <div><label>Operator</label><input name="operator" placeholder="e.g. Caroline"></div>
          <div><label>Notes</label><input name="notes" placeholder="optional"></div>
        </div>
        <div class="grid">
          <div><label>Subset Cameras (CSV, optional)</label><input name="cameras_csv" placeholder="cam01,cam02"></div>
          <div><label>Delay (ms)</label><input name="delay_ms" type="number" value="{DEFAULT_TRIGGER_DELAY_MS}"></div>
        </div>
        <div style="margin-top:12px">
          <button type="submit">Start Capture</button>
          <div class="muted" style="margin-top:6px;">{cams_badge}</div>
        </div>
      </form>
    </div>

    <div class="card">
      <h3>Known Cameras</h3>
      <p class="muted">This list is optional (for CSV convenience). You can also broadcast to all subscribing cameras.</p>
      <div>{"".join(f"<span class='pill'>{c}</span>" for c in cams) or "<em class='muted'>none yet</em>"}</div>
    </div>
    """
    return html_page(body)


@app.post("/ui/start")
async def ui_start(request: Request):
    """
    Handle the form submit and call /trigger internally with ADMIN_BEARER.
    """
    form = await request.form()
    fields = {k: (v if v != "" else None) for k, v in form.items()}
    # Call /trigger in-process (no HTTP round-trip) reusing the same function
    resp = trigger_capture(
        authorization=ADMIN_BEARER,
        patient_id=fields.get("patient_id"),
        wound_location=fields.get("wound_location"),
        operator=fields.get("operator"),
        notes=fields.get("notes"),
        session_id=None,
        cameras_csv=fields.get("cameras_csv"),
        delay_ms=int(fields.get("delay_ms") or DEFAULT_TRIGGER_DELAY_MS),
    )
    sid = resp["session_id"]
    # Redirect to the status page for this session
    return RedirectResponse(url=f"/ui/status/{sid}", status_code=303)


@app.get("/ui/status/{session_id}")
def ui_status(session_id: str):
    """
    Auto-refreshing status page. Green if a camera uploaded; orange if pending.
    """
    try:
        st = session_status(session_id, authorization=ADMIN_BEARER)
    except HTTPException:
        return html_page("<h1>Session not found</h1><a href='/ui'>&larr; back</a>")

    rows = []
    for cid in st["targeted"]:
        mark = "ok" if cid in st["received"] else "warn"
        rows.append(f"<tr><td>{cid}</td><td class='{mark}'>{'received' if cid in st['received'] else 'pending'}</td></tr>")
    table = "<table><tr><th>Camera</th><th>Status</th></tr>" + "".join(rows) + "</table>"

    body = f"""
    <h1>Session {st['session_id']}</h1>
    <div class="card">
      <p><b>Targeted:</b> {len(st['targeted'])} &nbsp; <b>Received:</b> {len(st['received'])} &nbsp; <b>Missing:</b> {len(st['missing'])}</p>
      {table}
      <p class="muted">This page auto-refreshes every 1 s.</p>
      <p><a href="/ui">&larr; New capture</a></p>
    </div>
    <script>setTimeout(()=>location.reload(),1000)</script>
    """
    return html_page(body)


@app.get("/healthz")
def healthz():
    """Simple health endpoint for monitoring."""
    return {"ok": True}
