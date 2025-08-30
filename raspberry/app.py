# app.py
import os, time, uuid, hashlib, shutil, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Set, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse

# -------------------
# basic settings
# -------------------
ADMIN_BEARER = os.getenv("ADMIN_BEARER", "Bearer change-me-admin")
DEVICE_BEARER = os.getenv("DEVICE_BEARER", "Bearer change-me-device")
STORAGE = Path("data/uploads"); STORAGE.mkdir(parents=True, exist_ok=True)
DEFAULT_TRIGGER_DELAY_MS = 300
TOKEN_TTL_SEC = 120

# -------------------
# in-memory state (simple; swap to SQLite later if needed)
# -------------------
class CameraState(dict): pass  # camera_id -> {last_seen_ms, firmware?, capabilities?}
CAMERAS: Dict[str, CameraState] = {}

class CaptureCommand(dict): pass  # {session_id, capture_at_ms, token}
PENDING: Dict[str, CaptureCommand] = {}  # camera_id -> command

SESSION_TARGETS: Dict[str, Set[str]] = {}  # session_id -> set(camera_ids)
SESSION_UPLOADS: Dict[str, Dict[str, dict]] = {}  # session_id -> camera_id -> info

# -------------------
# helpers
# -------------------
def now_ms() -> int: return int(time.time() * 1000)

def require_admin(value: Optional[str]):
    if value != ADMIN_BEARER:
        raise HTTPException(status_code=401, detail="unauthorized (admin)")

def verify_device(value: Optional[str]):
    if value != DEVICE_BEARER:
        raise HTTPException(status_code=401, detail="unauthorized (device)")

def session_dir(session_id: str) -> Path:
    d = STORAGE / session_id
    (d / "images").mkdir(parents=True, exist_ok=True)
    return d

def make_upload_token(session_id: str, camera_id: str, ttl_sec: int) -> str:
    expiry = now_ms() + ttl_sec * 1000
    secret = DEVICE_BEARER.encode()
    payload = f"{session_id}:{camera_id}:{expiry}".encode()
    sig = hashlib.sha1(secret + payload).hexdigest()
    return f"{session_id}:{camera_id}:{expiry}:{sig}"

def parse_token(token: str):
    try:
        session_id, camera_id, exp_str, sig = token.split(":")
        expiry = int(exp_str)
        return session_id, camera_id, expiry, sig
    except Exception:
        raise HTTPException(status_code=400, detail="invalid token")

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""): h.update(chunk)
    return h.hexdigest()

# -------------------
# app
# -------------------
app = FastAPI(title="Wound 3D Capture (LAN)", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True
)

# -------------------
# device endpoints (ESP32)
# -------------------
@app.post("/register")
def register(camera_id: str = Form(...),
            firmware: Optional[str] = Form(None),
            authorization: Optional[str] = Header(None)):
    verify_device(authorization)
    CAMERAS[camera_id] = {"last_seen_ms": now_ms(), "firmware": firmware}
    return {"server_time_ms": now_ms()}

@app.post("/heartbeat")
def heartbeat(camera_id: str = Form(...),
              authorization: Optional[str] = Header(None)):
    verify_device(authorization)
    if camera_id not in CAMERAS:
        CAMERAS[camera_id] = {"last_seen_ms": 0}
    CAMERAS[camera_id]["last_seen_ms"] = now_ms()
    cmd = PENDING.pop(camera_id, None)
    return {"server_time_ms": now_ms(), "command": cmd}

@app.post("/upload")
async def upload(file: UploadFile = File(...),
                 camera_id: str = Form(...),
                 session_id: str = Form(...),
                 token: str = Form(...),
                 ts_ms: Optional[int] = Form(None)):
    s_id, cam_id, expiry, sig = parse_token(token)
    if s_id != session_id or cam_id != camera_id:
        raise HTTPException(status_code=401, detail="token mismatch")
    if now_ms() > expiry:
        raise HTTPException(status_code=401, detail="token expired")

    d = session_dir(session_id) / "images"
    dest = d / f"{camera_id}.jpg"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    digest = sha256_file(dest)
    info = {"filename": str(dest), "ts_ms": ts_ms or now_ms(), "sha256": digest, "size": dest.stat().st_size}
    SESSION_UPLOADS.setdefault(session_id, {})[camera_id] = info
    return {"ok": True, "stored_as": dest.name, "sha256": digest}

@app.get("/time")
def server_time(): return {"server_time_ms": now_ms()}

# -------------------
# operator/admin endpoints
# -------------------
@app.post("/trigger")
def trigger(authorization: Optional[str] = Header(None),
            session_id: Optional[str] = Form(None),
            patient_id: Optional[str] = Form(None),
            wound_location: Optional[str] = Form(None),
            operator: Optional[str] = Form(None),
            notes: Optional[str] = Form(None),
            cameras_csv: Optional[str] = Form(None),
            delay_ms: Optional[int] = Form(None)):
    require_admin(authorization)
    session_id = session_id or datetime.now(timezone.utc).strftime("session_%Y%m%dT%H%M%S")
    capture_at = now_ms() + max(100, delay_ms or DEFAULT_TRIGGER_DELAY_MS)
    targets = [c.strip() for c in cameras_csv.split(",")] if cameras_csv else list(CAMERAS.keys())
    if not targets:
        raise HTTPException(status_code=400, detail="no cameras registered")

    # write session.json immediately
    sd = session_dir(session_id)
    meta = {
        "session_id": session_id,
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "patient_id": patient_id or "temp",
        "wound_location": wound_location or "unspecified",
        "operator": operator or "",
        "notes": notes or "",
        "targeted_cameras": sorted(targets)
    }
    with (sd / "session.json").open("w") as f: json.dump(meta, f, indent=2)

    SESSION_TARGETS[session_id] = set(targets)
    SESSION_UPLOADS.setdefault(session_id, {})

    for cam in targets:
        token = make_upload_token(session_id, cam, TOKEN_TTL_SEC)
        PENDING[cam] = {"session_id": session_id, "capture_at_ms": capture_at, "token": token}

    return {"session_id": session_id, "capture_at_ms": capture_at, "targeted_cameras": targets}

@app.get("/sessions/{session_id}/status")
def status(session_id: str, authorization: Optional[str] = Header(None)):
    require_admin(authorization)
    targets = SESSION_TARGETS.get(session_id, set())
    uploads = SESSION_UPLOADS.get(session_id, {})
    return {
        "session_id": session_id,
        "targeted": sorted(list(targets)),
        "received": sorted(list(uploads.keys())),
        "missing": sorted(list(targets - set(uploads.keys()))),
        "uploads": uploads
    }

# -------------------
# super-simple web UI (LAN)
# -------------------
def html_page(body: str) -> HTMLResponse:
    base_css = """
    <style>
      body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;max-width:860px}
      .card{border:1px solid #ddd;border-radius:12px;padding:16px;margin:16px 0}
      input,button,select,textarea{padding:10px;border-radius:8px;border:1px solid #ccc;width:100%;box-sizing:border-box}
      label{font-weight:600;margin-top:8px;display:block}
      button{cursor:pointer}
      .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
      .muted{color:#666}
      table{border-collapse:collapse;width:100%}
      th,td{border-bottom:1px solid #eee;padding:8px;text-align:left}
      .ok{color:green}.warn{color:#b15b00}.err{color:#b00020}
    </style>
    """
    return HTMLResponse(f"<!doctype html><meta charset='utf-8'><title>Wound 3D Capture</title>{base_css}{body}")

@app.get("/ui")
def ui_home():
    cams = sorted(CAMERAS.keys())
    cams_badge = f"<span class='muted'>{len(cams)} camera(s) registered)</span>" if cams else "<span class='warn'>no cameras yet</span>"
    body = f"""
    <h1>Wound 3D Capture (LAN)</h1>
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
          <div><label>Subset Cameras (optional CSV)</label><input name="cameras_csv" placeholder="cam01,cam02"></div>
          <div><label>Delay (ms)</label><input name="delay_ms" type="number" value="{DEFAULT_TRIGGER_DELAY_MS}"></div>
        </div>
        <div style="margin-top:12px">
          <button type="submit">Start Capture</button>
          <div class="muted" style="margin-top:6px;">{cams_badge}</div>
        </div>
      </form>
    </div>

    <div class="card">
      <h3>Registered Cameras</h3>
      <table><tr><th>ID</th><th>Last seen</th></tr>
      {''.join(f"<tr><td>{c}</td><td>{(now_ms() - CAMERAS[c]['last_seen_ms'])//1000 if 'last_seen_ms' in CAMERAS[c] else '-'} s ago</td></tr>" for c in cams)}
      </table>
    </div>
    """
    return html_page(body)

@app.post("/ui/start")
async def ui_start(request: Request):
    form = await request.form()
    fields = {k: (v if v != "" else None) for k, v in form.items()}
    # call /trigger internally
    resp = trigger(
        authorization=ADMIN_BEARER,
        session_id=None,
        patient_id=fields.get("patient_id"),
        wound_location=fields.get("wound_location"),
        operator=fields.get("operator"),
        notes=fields.get("notes"),
        cameras_csv=fields.get("cameras_csv"),
        delay_ms=int(fields.get("delay_ms") or DEFAULT_TRIGGER_DELAY_MS),
    )
    sid = resp["session_id"]
    return RedirectResponse(url=f"/ui/status/{sid}", status_code=303)

@app.get("/ui/status/{session_id}")
def ui_status(session_id: str):
    try:
        st = status(session_id, authorization=ADMIN_BEARER)
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
      <p class="muted">This page auto-refreshes every 1s.</p>
      <p><a href="/ui">&larr; New capture</a></p>
    </div>
    <script>setTimeout(()=>location.reload(),1000)</script>
    """
    return html_page(body)

@app.get("/healthz")
def healthz(): return {"ok": True}
