# Project Quality Criteria

## Title
**3D Wound-Healing Reconstruction Prototype**

## Description
The project aims to build a prototype system that captures and visualizes the wound-healing process over time using multiple ESP32 cameras in a fixed tunnel setup.  
Images are captured simultaneously, collected via a Raspberry Pi, and processed through a Gaussian Splatting pipeline (e.g., Nerfstudio) to create time-stamped 3D models.  
The result should demonstrate the feasibility of automated, reproducible 3D documentation for clinical applications.

---

### Criterion 1: Reliable Image Capture and Synchronization
**Description:**  
All ESP32 cameras can be triggered simultaneously via MQTT, and captured images are successfully received and stored with metadata.

| Quality Level | Description | Points |
|----------------|--------------|--------|
| **Minimum (50%)** | One ESP32-CAM can be triggered manually or via MQTT and successfully uploads its image to the server. | 5 |
| **Target (75%)** | Several cameras (≥3) can capture simultaneously via MQTT and upload images to the Raspberry Pi reliably. | 7 |
| **Optimal (100%)** | 10+ cameras capture in synchronization with timestamp accuracy <100 ms, and all uploads are automatically verified and logged. | 10 |

**Max Points:** 10  

---

### Criterion 2: Functional Data Pipeline and Server
**Description:**  
The Raspberry Pi collects images and metadata, manages sessions, and forwards data to the reconstruction environment.

| Quality Level | Description | Points |
|----------------|--------------|--------|
| **Minimum (50%)** | FastAPI server accepts uploads and stores session data locally. | 5 |
| **Target (75%)** | Server includes a working web UI to trigger captures and monitor uploads. | 7 |
| **Optimal (100%)** | Automated transfer of sessions to GPU/cloud and complete session tracking with metadata and logs. | 10 |

**Max Points:** 10  

---

### Criterion 3: 3D Reconstruction and Visualization
**Description:**  
Captured images are processed into a 3D representation using Gaussian Splatting (e.g., Nerfstudio).

| Quality Level | Description | Points |
|----------------|--------------|--------|
| **Minimum (50%)** | A static dataset can be processed manually into a 3D model using an existing Gaussian Splatting tool. | 5 |
| **Target (75%)** | The Pi-generated sessions can be reconstructed with a semi-automated script in a GPU environment. | 7 |
| **Optimal (100%)** | Fully integrated pipeline: automatic upload, processing, and visualization of 3D models in a viewer or via screenshots. | 15 |

**Max Points:** 15  

---

### Criterion 4: Usability and Documentation
**Description:**  
The system should be understandable and usable by non-technical users (clinicians) and reproducible by others.

| Quality Level | Description | Points |
|----------------|--------------|--------|
| **Minimum (50%)** | Basic setup and usage instructions documented in README. | 3 |
| **Target (75%)** | User can start capture and view reconstruction results via a simple UI or command. | 4 |
| **Optimal (100%)** | Clean, documented workflow with UI, troubleshooting guide, and reproducible pipeline instructions. | 5 |

**Max Points:** 5  

---

### Total Max Points: **50**
