# Project Summary: Wound-Healing 3D Reconstruction Prototype

## 1. What We Already Have / Agreed Upon

### Core Concept
- Build a fixed camera tunnel to observe wound (or object) healing over time.  
- ESP32-CAM modules take synchronized photos from multiple angles.  
- Photos are processed into a 3D reconstruction using Gaussian Splatting.  
- Output: 3D model with timestamp to compare healing progress visually.

### Current Prototype Setup
- Currently one ESP32-CAM working; plan for ~20–30 small cameras.  
- Cameras are triggered via MQTT and send JPEGs to the server via HTTP POST.  
- The server (Raspberry Pi)  
  - Hosts a FastAPI service (web UI + API).  
  - Publishes the MQTT trigger command to all cameras.  
  - Receives uploaded images and stores them per session (`session.json` + `images/`).  
  - Optionally forwards session folders to a GPU or cloud machine for reconstruction.

### Software Stack
- **ESP32 firmware:** subscribes to MQTT topic, captures image, HTTP upload.  
- **Mosquitto broker:** runs on the Raspberry Pi (local network).  
- **FastAPI server:** web UI, upload endpoint, MQTT publisher, session tracking.  
- **Nerfstudio (planned):** reconstructs Gaussian Splat models from each session.

---

## 2. Open / Design Questions

### 1. Hardware & Cameras
- Multiple cameras per ESP32?  
  - Each ESP32-CAM board controls one camera natively.  
  - Using multiple cameras per board requires multiplexers and is complex.  
  - The simpler and common solution is one ESP32-CAM per physical camera.
- Calibration  
  - If the rig is completely fixed, one-time calibration (intrinsics + extrinsics) is sufficient.  
  - The calibration defines camera poses required for Gaussian Splatting / NeRF training.  
  - For a fixed tunnel, store this as `transforms.json` and reuse it for every session.

### 2. Data Collection & Processing Flow
- Do we still need the Raspberry Pi if the reconstruction happens elsewhere?  
  - Yes, as a lightweight capture hub and web UI.  
    - Triggers captures (MQTT).  
    - Receives images (HTTP).  
    - Adds metadata (patient ID, wound location).  
    - Syncs folders to GPU or cloud.  
  - If cameras uploaded directly to the cloud, networking and authentication would become more complex.
- Where should the photos go?  
  - Option A (local GPU workstation): fastest and secure but requires dedicated hardware.  
  - Option B (cloud GPU instance): suitable for a prototype and inexpensive for small sessions.

### 3. Cloud vs Local Reconstruction
- Cloud feasibility  
  - No GDPR risk since only synthetic or non-patient data is used.  
  - GPU instances are inexpensive for short runs (approx. $0.30–0.50 per session).  
  - Each session folder (images + `transforms.json`) can be uploaded to the cloud, processed in Nerfstudio, and the resulting model or screenshots downloaded.
- Workflow question  
  - Should the Pi automatically push new sessions to the cloud VM and trigger reconstruction?  
  - Or will the reconstruction be started manually for now?  
  - Later, this could be automated via a script or API call.

### 4. Triggering the Capture
- How to start the capture  
  - Option A: small web GUI on the Raspberry Pi, accessible from any phone or tablet.  
  - Option B: physical button wired to the Raspberry Pi.  
  - MQTT publish happens from whichever trigger method is used.
- Questions for the second professor  
  - Is a mobile web UI practical and secure?  
  - Could he assist with the frontend (HTML + Bootstrap + mobile layout)?

### 5. Gaussian Splatting / 3D Reconstruction
- Tool choice: still deciding between  
  - Nerfstudio (Splatfacto) — open source, scriptable, cloud-friendly.  
  - Jawset Postshot — GUI-only, commercial, limited API integration.  
  - Most likely: Nerfstudio for pipeline integration.
- Inputs required  
  - Folder of images per session.  
  - `transforms.json` (camera poses + intrinsics).  
  - Optional masks/background cleanup for improved quality.
- Outputs  
  - Gaussian Splat model (`.ply`) and configuration.  
  - Viewer URL (`localhost:7007` on GPU machine).  
  - Optional static renders (PNG screenshots) for comparison over time.

### 6. Displaying the Result
- On the cloud GPU  
  - Nerfstudio includes a built-in web viewer accessible via browser.  
  - The viewer can be accessed through SSH port forwarding or hosted snapshots.  
- For offline viewing  
  - Export `.ply` files and use MeshLab or a simple web-based viewer.  
  - Alternatively, export fixed-angle screenshots for longitudinal analysis.

---

## 3. Next Steps / Action Items

| Area | Task | Responsible / Question |
|------|-------|------------------------|
| Cameras | Decide whether to use one ESP32-CAM per camera or multiplexed setup. | Confirm feasibility with hardware supervisor. |
| Calibration | Create or generate a fixed-rig `transforms.json`. | Lukas & Felix |
| Raspberry Pi Server | Finalize FastAPI + MQTT server implementation. | Lukas |
| Web UI | Add smartphone-friendly web form or consider physical button trigger. | Ask professor for input. |
| Cloud GPU | Check with supervisor whether cloud GPU usage (AWS, RunPod) is acceptable. | Lukas |
| Data Sync | Define method to sync session folders from Pi to GPU/cloud (rsync, scp, API). | TBD |
| 3D Reconstruction | Test a small dataset with Nerfstudio on GPU. | Lukas & Caroline |
| Visualization | Decide on visualization method (interactive viewer vs static renders). | Team decision |
