# PECH NDI-to-WebRTC Bridge
## Standalone Executable Installation & User Guide

---

## 1. System Overview

**PECH NDI-to-WebRTC Bridge** is an ultra-low-latency Windows application that discovers and decodes live NDI and NDI|HX streams across your local network and transcodes them into WebRTC streams with sub-50ms glass-to-glass latency.

The entire application is packaged as a **single standalone Windows executable (`PECH_NDI_WebRTC.exe`)** with no Python installation required on the target machine.

### Key Capabilities
- **Sub-50ms Latency**: 1-frame fresh buffer pipeline eliminates video/audio queue delay.
- **NDI & NDI|HX Support**: Discovers and decodes full-bandwidth NDI (SpeedHQ) and NDI|HX (H.264/HEVC) sources via the official NDI 6 SDK.
- **Single File Executable (`.exe`)**: All web assets, WebRTC engines, and UI libraries are self-contained inside `PECH_NDI_WebRTC.exe`.
- **Any-Device Playback**: Any phone, tablet, PC, Mac, or Smart TV on the same LAN/Wi-Fi can watch the stream in standard browsers with zero plugins.
- **Dual Execution Modes**:
  1. **Interactive Desktop UI**: Double-click `PECH_NDI_WebRTC.exe` to open the configuration dashboard with live stream discovery and embedded preview player.
  2. **Headless Mode**: Run `PECH_NDI_WebRTC.exe --headless` from the command line or as a background Windows service reading from `settings.json`.

---

## 2. System Requirements

- **Operating System**: Windows 11 (64-bit) or Windows 10 (64-bit, version 1809+)
- **NDI 6 Runtime**: Download the free [NDI 6 Tools / Runtime for Windows](https://ndi.video/tools/) (installs `Processing.NDI.Lib.x64.dll`).
- **Network**: Gigabit Ethernet or 5 GHz Wi-Fi on the same local subnet.

---

## 3. How to Run `PECH_NDI_WebRTC.exe`

### Mode 1: Interactive Desktop UI (Default)
Simply **double-click** `PECH_NDI_WebRTC.exe` (or run from PowerShell/CMD):
```powershell
.\PECH_NDI_WebRTC.exe
```

**Features in UI Mode:**
- **Auto-Discovery**: Scans and lists all active NDI video sources on your local network.
- **Stream Configuration**: Select NDI source, customize resolution (Native, 1080p, 720p, 4K), framerate (60, 50, 30 fps), bitrate, and audio sample rate.
- **Live Preview Stage**: Embedded real-time WebRTC player showing stream health, active FPS, and latency diagnostics.
- **Save Settings**: Automatically persists your preferences into `settings.json` next to the executable.
- **QR Code & LAN Share**: Displays the direct LAN stream URL (`http://<LAN_IP>:8080`) and a scannable QR code for phones and tablets.

---

### Mode 2: Headless Mode (CLI / Background Service)
Run with the `--headless` switch to start as a lightweight background server without opening a GUI window:
```powershell
.\dist\PECH_NDI_WebRTC.exe --headless
```
*Or simply double-click the included batch launcher:*
```powershell
.\dist\start_headless.bat
```

#### Command-Line Options

| Flag | Description | Example |
| :--- | :--- | :--- |
| `--headless` | Runs without desktop window (CLI/service mode) | `.\PECH_NDI_WebRTC.exe --headless` |
| `--port <PORT>` | Sets HTTP web and WebRTC signaling port (default: `8025`) | `.\PECH_NDI_WebRTC.exe --headless --port 8025` |
| `--source "<NAME>"` | Specifies the exact NDI stream source name to decode | `.\PECH_NDI_WebRTC.exe --headless --source "STUDIO-PC (Camera 1)"` |
| `--config <PATH>` | Custom path to JSON configuration file | `.\PECH_NDI_WebRTC.exe --headless --config custom_settings.json` |
| `--bind <IP>` | Binds server to specific network interface IP | `.\PECH_NDI_WebRTC.exe --headless --bind 0.0.0.0` |

---

## 4. Configuration Reference (`settings.json`)

`PECH_NDI_WebRTC.exe` automatically reads from and writes to `settings.json` located in the same directory as the executable:

```json
{
  "server": {
    "http_port": 8025,
    "bind_address": "0.0.0.0"
  },
  "ndi": {
    "source_name": "STUDIO-PC (Camera 1)",
    "color_format": "BGRX",
    "low_bandwidth": false
  },
  "video": {
    "target_width": 0,
    "target_height": 0,
    "target_fps": 0,
    "bitrate_kbps": 6000,
    "codec": "H264"
  },
  "audio": {
    "channels": 2,
    "sample_rate": 48000,
    "bitrate_kbps": 128,
    "codec": "opus"
  },
  "app": {
    "auto_start": true,
    "title": "PECH NDI-to-WebRTC Bridge"
  }
}
```

---

## 5. How LAN Clients Connect & View

1. Connect viewing devices (iPhones, Android phones, iPads, PCs, Macs) to the **same Wi-Fi or Ethernet network**.
2. Open any browser (Chrome, Safari, Edge, Firefox) and navigate to:
   ```text
   http://<WINDOWS_PC_IP>:8025
   ```
   *(Example: `http://192.168.1.40:8025`)*
3. **Mobile Devices**: Scan the QR code displayed in the Desktop UI or click **"Share LAN URL"** to view instantly.
4. **Audio**: Click **"Unmute Audio"** when prompted by the browser.

---

## 6. Building / Recompiling the Executable

Whenever source code modifications are made, run the automated build script:
```powershell
python build_exe.py
```
This produces the updated standalone single file at:
```text
dist\PECH_NDI_WebRTC.exe
```
