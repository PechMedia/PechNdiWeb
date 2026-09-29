# PECH NDI-to-WebRTC Low-Latency Tablet Streaming Bridge

A high-performance Windows application packaged as a **single standalone executable (`PECH_NDI_WebRTC.exe`)** and a **Windows Setup Installer (`PECH_NDI_WebRTC_Setup.exe`)** that decodes live **NDI** and **NDI|HX** slide streams and transcodes them into **near-zero latency (<50ms)** WebRTC streams for kiosk Android tablets used by visually impaired church members.

---

## Key Features

- **Windows Setup Installer**: Automated single-file installer (`PECH_NDI_WebRTC_Setup.exe`) that creates Desktop and Start Menu shortcuts.
- **Standalone Executable**: Portable single-file binary (`PECH_NDI_WebRTC.exe`) with no Python installation required.
- **Near-Zero Latency**: Direct 1-frame fresh buffer pipeline eliminates buffer lag (<50ms latency).
- **Strictly Muted Video-Only Stream**: 100% compliant with mobile browser autoplay policies, ensuring Android tablets play immediately without needing any screen tap.
- **REST API State Control & Pause Overlay**: `POST /api/stream/control` allows vMix or operators to pause the stream and display custom text in both the video frame (Pillow static black card) and the tablet DOM overlay (large, high-contrast text).
- **Kiosk Hardened**: Context menu, gesture zoom, and double-tap zoom disabled; Screen Wake Lock API prevents tablet screen sleep.
- **JSON Configuration**: Default port `8123` and 720p 30fps streaming parameters in `settings.json`.

---

## Quick Start

### 1. Requirements
- Windows 10 / Windows 11 (64-bit)
- Free [NDI 6 Tools / Runtime for Windows](https://ndi.video/tools/) installed (`Processing.NDI.Lib.x64.dll`)

### 2. Running the Server
Double-click `start_server.bat` or run:
```powershell
.\dist\PECH_NDI_WebRTC.exe --config settings.json
```

Or from Python source:
```powershell
pip install -r requirements.txt
python main.py
```

### 3. Viewing on Tablets
Open any browser on the Android tablet and browse to:
```text
http://<WINDOWS_PC_IP>:8123
```

---

## REST API Control

- **Pause with Message:**
  ```http
  POST /api/stream/control
  Content-Type: application/json

  {
    "action": "pause",
    "message": "Pausing - slides will show again after video has played"
  }
  ```
- **Resume Live Slides:**
  ```http
  POST /api/stream/control
  Content-Type: application/json

  { "action": "resume" }
  ```
- **Inspect Stream Health:** `GET /api/stream/status`

For complete instructions, vMix automation scripts, and configuration references, see the **[INSTALLATION_AND_USAGE_GUIDE.md](file:///d:/PECHNDIWEB/INSTALLATION_AND_USAGE_GUIDE.md)**.
