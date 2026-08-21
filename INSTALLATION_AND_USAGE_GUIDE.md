# PECH NDI-to-WebRTC Bridge
## Comprehensive Installation & User Guide

---

## 1. System Overview

**PECH NDI-to-WebRTC Bridge** is an ultra-low-latency Windows application designed to decode live NDI and NDI|HX video/audio streams on your local network and transcode them in real time into WebRTC streams.

### Key Capabilities
- **Sub-50ms Latency**: 1-frame fresh buffer strategy eliminates video/audio queue lag.
- **NDI & NDI|HX**: Compatible with full-bandwidth NDI (SpeedHQ) and NDI|HX (H.264/HEVC) sources.
- **Cross-Platform LAN Viewing**: Any device on the same local network (iPhone, iPad, Android, Mac, Windows, Linux, Smart TV) can watch the stream instantly in standard web browsers with no plugins or apps required.
- **Dual Execution Modes**:
  1. **UI Mode**: Modern desktop window for interactive discovery, parameter tuning, and live preview.
  2. **Headless Mode**: Lightweight CLI background service reading from `settings.json`.

---

## 2. Prerequisites & Requirements

### Supported Operating Systems
- Windows 11 (64-bit) — *Recommended*
- Windows 10 (64-bit, version 1809 or later)

### Required Software Components
1. **NDI 6 Runtime or NDI 6 Tools**:
   - Download the free [NDI 6 Runtime / Tools for Windows](https://ndi.video/tools/).
   - The installer places `Processing.NDI.Lib.x64.dll` in `C:\Program Files\NDI\NDI 6 Runtime\v6\`.
2. **Python 3.10 – 3.12 (64-bit)**:
   - Ensure `Add Python to PATH` was checked during installation.
3. **Microsoft Edge WebView2 Runtime**:
   - Built into Windows 11 and modern Windows 10 installations (used for Desktop UI mode).

---

## 3. Installation Guide

### Step 1: Clone or Download the Repository
Open PowerShell or Command Prompt:
```powershell
git clone https://github.com/PechMedia/PechNdiWeb.git D:\PECHNDIWEB
cd D:\PECHNDIWEB
```

### Step 2: Install Python Dependencies
Install the required Python packages:
```powershell
pip install aiortc aiohttp numpy av websockets pywebview
```

*(Optional: If you plan to compile a standalone `.exe`, also install PyInstaller:)*
```powershell
pip install pyinstaller
```

---

## 4. Running the Application

### Option A: Desktop UI Mode (Interactive)
To launch with the desktop configuration window:
```powershell
python main.py
```
**Features available in UI Mode:**
- **Live Discovery**: Auto-detects all active NDI video sources on your LAN.
- **Stream Controls**: Select source, set target resolution, frame rate, bitrate, and audio sample rate.
- **Live Preview Stage**: Embedded real-time WebRTC player showing stream health and FPS.
- **Save Settings**: Writes directly to `settings.json`.
- **Instant LAN Share**: Displays the local network URL and a scannable QR code for phones and tablets.

---

### Option B: Headless Mode (CLI / Service)
To run as a silent background server using saved configuration:
```powershell
python main.py --headless
```

#### Command-Line Arguments
You can override configuration parameters directly from the command line:

| Argument | Description | Example |
| :--- | :--- | :--- |
| `--headless` | Run in headless mode without desktop window | `python main.py --headless` |
| `--port <PORT>` | Set web and signaling HTTP port (default: `8080`) | `python main.py --headless --port 8080` |
| `--source "<NAME>"` | Set the NDI stream source name to decode | `python main.py --headless --source "STUDIO-PC (OBS)"` |
| `--config <PATH>` | Specify a custom JSON configuration file | `python main.py --headless --config custom_settings.json` |
| `--bind <IP>` | Bind to specific network interface IP | `python main.py --headless --bind 0.0.0.0` |

---

## 5. Configuration Reference (`settings.json`)

The application automatically reads and saves configuration to `settings.json`.

```json
{
  "server": {
    "http_port": 8080,
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

### Parameter Explanations
- **`server.http_port`**: The port used for web players and WebRTC signaling.
- **`server.bind_address`**: Set to `0.0.0.0` to allow access from any device on your LAN.
- **`ndi.source_name`**: Exact name of the NDI source (e.g. `MY-PC (OBS NDI)`).
- **`ndi.low_bandwidth`**: `true` requests a low-bandwidth proxy stream from NDI sources that provide one.
- **`video.target_width` & `video.target_height`**: `0` preserves native source resolution (e.g., 1920x1080 or 3840x2160). You can also explicitly set downscaling (e.g., `1280` and `720`).
- **`video.target_fps`**: `0` matches source framerate (e.g., 60 or 59.94).
- **`video.bitrate_kbps`**: Target WebRTC video encoding bitrate in kilobits per second.
- **`audio.sample_rate`**: Recommended `48000` (48 kHz) for standard WebRTC Opus audio.

---

## 6. How Clients Connect on LAN

1. Ensure the viewing device (phone, laptop, iPad, Smart TV) is connected to the **same local Wi-Fi or Ethernet network**.
2. Open any modern web browser (Google Chrome, Apple Safari, Microsoft Edge, Mozilla Firefox).
3. Navigate to:
   ```text
   http://<HOST_WINDOWS_PC_IP>:8080
   ```
   *(Example: `http://192.168.1.40:8080`)*
4. **Mobile Devices**: Scan the QR code shown in the Admin dashboard (`/admin`) or Share dialog to open the stream immediately.
5. **Audio Playback**: Web browsers require a user interaction to play unmuted audio. Click the **"Unmute Audio"** banner when prompted.

---

## 7. Building Standalone Windows Executable

To compile into a standalone `.exe` package that does not require Python on the target machine:

```powershell
python build_exe.py
```

The output bundle will be created at:
```text
dist\PECH_NDI_WebRTC\PECH_NDI_WebRTC.exe
```

You can distribute the `dist\PECH_NDI_WebRTC\` folder directly to other Windows 10/11 machines with the NDI 6 Runtime installed.

---

## 8. Troubleshooting & Optimization

### 1. NDI Source Not Appearing in Discovery List
- **Check Network Subnet**: Make sure the NDI sender and the Windows bridge machine are on the same subnet.
- **NDI Discovery Server / Access Manager**: If using NDI Discovery Server across VLANs, configure the discovery server IP in NDI Access Manager.
- **Windows Firewall**: If Windows Firewall blocks NDI mDNS discovery, allow incoming UDP traffic for Python / `PECH_NDI_WebRTC.exe`.

### 2. Stream Latency Optimization
- **Ethernet Connection**: For zero latency, connect the host PC via Gigabit Ethernet rather than 2.4 GHz Wi-Fi.
- **Resolution**: Streaming native 1080p60 typically incurs only 30–50ms glass-to-glass latency.

### 3. Windows Firewall Configuration
To allow LAN devices to connect to port 8080:
1. Open Windows Defender Firewall -> Advanced Settings.
2. Add an **Inbound Rule** for **TCP Port 8080**.
3. Set action to **Allow the connection**.
