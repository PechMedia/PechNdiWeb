# PECH NDI-to-WebRTC Low-Latency LAN Streaming Bridge

A high-performance Windows application packaged as a **single standalone executable (`PECH_NDI_WebRTC.exe`)** that decodes live **NDI** and **NDI|HX** video/audio streams and encodes them into **near-zero latency (<50ms)** WebRTC streams for real-time viewing on any browser or device across your Local Area Network (LAN).

---

## Key Features

- **Single Standalone Executable**: All web assets, WebRTC engines, and UI libraries bundled into `PECH_NDI_WebRTC.exe` (no Python installation required).
- **Near-Zero Latency**: Direct 1-frame uncompressed NDI memory pipeline to WebRTC RTP/SRTP over UDP.
- **NDI & NDI|HX Support**: Discovers and decodes full-bandwidth NDI (SpeedHQ/BGRX) and NDI|HX streams via NDI 6 SDK.
- **Dual Execution Modes**:
  - **Interactive Desktop UI (Default)**: Double-click `PECH_NDI_WebRTC.exe` to launch the Windows 11 dashboard with live NDI discovery, parameter tuning, preview monitor, and QR code sharing.
  - **Headless Mode (`--headless`)**: Runs quietly in the background as a CLI app or Windows service, reading from `settings.json`.
- **Any-Device LAN Playback**: Any phone, tablet, PC, Mac, or Smart TV on the same Wi-Fi/LAN can open the stream without installing any apps or browser extensions.
- **JSON Configuration**: Complete settings persistence in `settings.json`.

---

## Quick Start

### 1. Requirements
- Windows 10 / Windows 11 (64-bit)
- NDI 6 Runtime or NDI 6 Tools installed (`Processing.NDI.Lib.x64.dll`)

### 2. Running with Desktop UI
Double-click `PECH_NDI_WebRTC.exe` or run:
```powershell
.\PECH_NDI_WebRTC.exe
```

### 3. Running in Headless Mode
```powershell
.\PECH_NDI_WebRTC.exe --headless
```

#### CLI Options
```powershell
.\PECH_NDI_WebRTC.exe --headless --port 8080 --source "STUDIO-PC (Camera 1)"
```
- `--headless`: Run as a background service/daemon without UI.
- `--port <PORT>`: Web / WebRTC signaling port (default: 8080).
- `--source "<NAME>"`: Override NDI source name.
- `--config <PATH>`: Custom path to JSON configuration file.
- `--bind <IP>`: IP address to bind to (default: `0.0.0.0`).

---

## Rebuilding the Single `.exe`
```powershell
python build_exe.py
```
Output: `dist\PECH_NDI_WebRTC.exe`
