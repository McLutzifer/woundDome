# Project Summary: Wound-Healing 3D Reconstruction Prototype

# Open Questions and Undecided Points

## Hardware
- Do we need one ESP32 module per camera?  
- Do the cams have fixed focus?  
- How to handle power supply for the cameras?
- Do we need a flash light?
- How amny cameras do we need?

## Calibration
- What format (e.g., `transforms.json`) and parameters does Gaussian Splatting require?

## Data Collection & Networking
- Should we keep the Raspberry Pi as the local “hub” (collecting images and metadata) or upload directly to a cloud service?  
- How should the Raspberry Pi forward completed sessions to the GPU machine or cloud instance (e.g., rsync, scp, API call)?  
- How do we organize and store session metadata (patient/wound IDs, timestamps) in a standardized structure?  

## Triggering
- Should the capture be triggered from a web interface (mobile-friendly GUI) or via a physical hardware button?  
- Is it feasible and secure to host the web interface on the Raspberry Pi and access it from a smartphone over the local network?  

## Gaussian Splatting / Reconstruction
- Which reconstruction tool should we use:  
  - Nerfstudio or Jawset Postshot ?  
- What preprocessing is needed for the images (background removal, resizing, masking) before splatting?  
- Where should the reconstruction happen:  
  - Local GPU workstation? 
  - Cloud GPU instance?  
- If using cloud GPUs, what is the expected cost?  
- Should the reconstruction be triggered automatically after upload or started manually?

## Output & Visualization
- How should the resulting 3D models be stored, accessed, or displayed?  
- If models are produced in the cloud, how do we transfer or visualize them locally (e.g., download `.ply`, host web viewer, screenshots)?



---
  

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

| Area | Task 
|------|-------|
| Cameras | Decide whether to use one ESP32-CAM per camera or multiplexed setup. | 
| Calibration | Create or generate a fixed-rig `transforms.json`. |
| Raspberry Pi Server | Finalize FastAPI + MQTT server implementation. |
| Web UI | Add smartphone-friendly web form or consider physical button trigger. |
| Cloud GPU | Check with supervisor whether cloud GPU usage (AWS, RunPod) is acceptable. | 
| Data Sync | Define method to sync session folders from Pi to GPU/cloud (rsync, scp, API). | 
| 3D Reconstruction | Test a small dataset with Nerfstudio on GPU. | 
| Visualization | Decide on visualization method (interactive viewer vs static renders). | 



# Open Questions and Undecided Points

## Hardware
- Do we need one ESP32 module per camera, or is there a simpler way to connect multiple small cameras to one board (e.g., via multiplexing)?  
- What resolution, exposure control, and lens type are optimal for the 3D reconstruction?  
- How should we handle power supply and cable management for 20–30 cameras in the tunnel?

## Calibration
- Is one-time calibration of the fixed camera setup sufficient, or should we recalibrate periodically?  
- What exact format (e.g., `transforms.json`) and parameters does Gaussian Splatting require for reproducible results?

## Data Collection & Networking
- Should we keep the Raspberry Pi as the local “hub” (collecting images and metadata) or upload directly to a cloud service?  
- How should the Raspberry Pi forward completed sessions to the GPU machine or cloud instance (e.g., rsync, scp, API call)?  
- How do we organize and store session metadata (patient/wound IDs, timestamps) in a standardized structure?  

## Triggering
- Should the capture be triggered from a web interface (mobile-friendly GUI) or via a physical hardware button?  
- Is it feasible and secure to host the web interface on the Raspberry Pi and access it from a smartphone over the local network?  
- Can the second professor assist with the web UI design and frontend implementation?

## Gaussian Splatting / Reconstruction
- Which reconstruction tool should we ultimately use:  
  - Nerfstudio (open source, cloud-compatible)  
  - Jawset Postshot (GUI, commercial, limited automation)?  
- What preprocessing is needed for the images (background removal, resizing, masking) before splatting?  
- Where should the reconstruction happen:  
  - Local GPU workstation (faster, but needs hardware)  
  - Cloud GPU instance (e.g., AWS, RunPod)?  
- If using cloud GPUs, is the expected cost per session acceptable for our project budget?  
- Should the reconstruction be triggered automatically after upload or started manually?

## Output & Visualization
- How should the resulting 3D models be stored, accessed, or displayed?  
- Should clinicians view results in the interactive Nerfstudio viewer, or should we generate static renders/screenshots?  
- If models are produced in the cloud, how do we transfer or visualize them locally (e.g., download `.ply`, host web viewer, screenshots)?

## Collaboration & Supervision
- Which professor supervises which part (hardware, software, cloud processing, visualization)?  
- What scope of prototype (number of cameras, automation level) is realistic for this semester’s milestone?  

