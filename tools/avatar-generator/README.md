# 🎭 Sovereign Talking Head Avatar Generator

An advanced, fully local, open-source alternative to **HeyGen** and **Tavus**. 

This repository packages a state-of-the-art portrait animation and lip-syncing engine designed to run completely offline on local consumer GPUs. It yields cinematic **60 FPS 4K** talking-head videos from a single portrait photo and an audio file, and supports **real-time WebRTC conversational streaming** with local LLM brains.

---

## ✨ Features & Architecture

Our architecture integrates the newest and most capable models as of **August 29, 2026**:

1. **Facial Dynamics & Expression Reenactment (LivePortrait)**:
   Animates a static portrait photo with high-fidelity eye blinks, facial movement, and realistic pose dynamics using Kwai's *LivePortrait* driver.
2. **High-Fidelity Lip Synchronization (MuseTalk & EchoMimic)**:
   Uses audio-driven warping (*MuseTalk* or *EchoMimic*) to precisely synchronize the mouth movements of the animated video to any input speech audio.
3. **Natural Human Motion (LongCat-Video-Avatar Integration)**:
   Applies *Speech-Motion Decoupling* and *Reference Skip Attention* to prevent the robotic "rigid body" look common in legacy avatars. It strategically incorporates reference cues to preserve facial identity while preventing excessive image leakage.
4. **Cinematic Post-Processing (60 FPS 4K)**:
   Surgically upscales and pads the output to 4K resolution (`2160x3840`) and interpolates frames using FFmpeg's `minterpolate` motion-compensated algorithm (`fps=60:mi_mode=mci:mc_mode=aobmc`) for buttery-smooth digital twin output.
5. **Real-time WebRTC Conversational Gateway**:
   Spawns WebRTC-enabled sessions allowing users to hold live, bidirectional face-to-face video conversations with local AI twins.

---

## 🛠️ Prerequisites & Setup

### 1. Requirements
*   **Operating System**: Windows 10/11 or Ubuntu Linux
*   **GPU**: NVIDIA GPU with CUDA 12.0+ and ≥8GB VRAM
*   **System Tools**: [FFmpeg](https://ffmpeg.org/) (must be added to your system `PATH`)

### 2. Installation
Clone the repository and install the dependencies in a virtual environment:
```bash
git clone git@github.com:kguinternational/codex.git
cd codex/tools/avatar-generator

# Setup python environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install required libraries
pip install -r requirements.txt
```

### 3. Model Weights Download
To run the generator locally, you must download the pretrained weights from HuggingFace and place them in the correct directories:

#### LivePortrait Weights
Create directory `LivePortrait/pretrained_weights/` and download:
*   `stitching_retargeting_module.pth`
*   `landmark.onnx`
*   `detection_resnet50.onnx`
*   `appearance_feature_extractor.pth`
*   `motion_extractor.pth`
*   `warping_spade.pth`
*   `spade_generator.pth`

#### MuseTalk Weights
Create directory `MuseTalk/models/` and download:
*   `musetalkV15/unet.pth`
*   `musetalk/pytorch_model.bin`
*   `sd-vae/diffusion_pytorch_model.bin`
*   `syncnet/latentsync_syncnet.pt`
*   `face-parse-bisent/79999_iter.pth`

---

## 🚀 Running the Server

Start the interactive Video Studio and WebRTC command HUD:

```bash
# Double click run_avatar_app.bat (on Windows) or run:
python server.py
```

Open your browser and navigate to:
*   **Video Studio & Persona Hub**: `http://localhost:8085/static/studio.html`
*   **Palantir-Style Swarm Command Center**: `http://localhost:8085/static/index-KGU.html`

---

## 🔌 API Reference

### Render Talking Head Video
*   **Endpoint**: `POST /api/video/render`
*   **Payload**:
    ```json
    {
      "text": "Hi Certified Air Care team! I built a local AI voice receptionist for you.",
      "personality": "ceo",
      "client_id": "jc-coffey-foundation",
      "sentiment": "happy",
      "engine": "musetalk"
    }
    ```
*   **Response**:
    ```json
    {
      "status": "success",
      "video_url": "/static/animations/render_ceo_1785645546.mp4"
    }
    ```

### Upload Custom Portrait
*   **Endpoint**: `POST /api/avatar/upload-portrait`
*   **Payload**: `multipart/form-data` with fields `file` (Image), `client_id`, and `persona`.
