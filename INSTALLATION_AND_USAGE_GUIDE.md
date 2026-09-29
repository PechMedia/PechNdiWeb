# PECH NDI-to-WebRTC Streaming Bridge
## Installation, Configuration & Operator's Guide
**Version:** 1.0.18  
**Target:** Low-Latency WebRTC Tablet Streaming for Churches & Visually Impaired Members

---

## 1. System Overview

**PECH NDI-to-WebRTC Streaming Bridge** is an ultra-low-latency Windows application designed to capture live NDI slide streams (e.g. from vMix or OBS) and transcode them in real-time to WebRTC/WHEP for viewing on Android tablets.

The system is specifically tailored for church members with visual impairments, featuring:
- **Sub-50ms Glass-to-Glass Latency**: 1-frame fresh buffer pipeline eliminates video lag.
- **Strictly Muted Video-Only Stream**: 100% compliant with mobile browser autoplay policies, guaranteeing that Android tablets start playing instantly with **zero user taps or clicks required**.
- **Dual-Layer Pause Messaging**:
  1. *Video Track Layer*: When paused via vMix or the REST API, the bridge halts live NDI frames and broadcasts a clean, static black video frame with the message centered (rendered dynamically via Pillow).
  2. *DOM Overlay Layer*: Connected tablets receive real-time WebSocket state updates, rendering the message in large, crisp, high-contrast typography suited for visually impaired readers.
- **Kiosk Hardened**: Context menu (right-click) is disabled, gesture zoom and pinch-to-zoom are locked, and the Screen Wake Lock API keeps tablet displays awake throughout church services.
- **Standalone Windows Deployment**: Available as both a **Windows Setup Installer (`PECH_NDI_WebRTC_Setup.exe`)** and a **single portable executable (`PECH_NDI_WebRTC.exe`)** with no Python installation required on the target machine.

---

## 2. System Requirements

### Host Machine (Server)
- **Operating System**: Windows 11 (64-bit) or Windows 10 (64-bit, version 1809+)
- **NDI 6 Runtime**: Download the free [NDI 6 Tools / Runtime for Windows](https://ndi.video/tools/) (installs `Processing.NDI.Lib.x64.dll`).
- **Network**: Local Area Network (Gigabit Ethernet recommended for the server machine; 5 GHz Wi-Fi or Wi-Fi 6 recommended for tablets).

### Client Tablets
- **Devices**: Any Android tablet (Samsung Galaxy Tab, Lenovo Tab, Amazon Fire, etc.) or iPad.
- **Browsers**: Google Chrome, Samsung Internet, Microsoft Edge, or Fully Kiosk Browser. No plugins or native app installation required.

---

## 3. Installation Options

All distribution files are located in the `dist\` folder of the repository.

### Option A: Windows Setup Installer (Recommended)
1. Double-click [`dist\PECH_NDI_WebRTC_Setup.exe`](file:///d:/PECHNDIWEB/dist/PECH_NDI_WebRTC_Setup.exe).
2. Press **Enter** to install to the default location (`C:\PECH_NDI_Bridge`) or specify a custom folder.
3. The installer will:
   - Extract `PECH_NDI_WebRTC.exe`, `settings.json`, and `start_server.bat`.
   - Preserve any existing `settings.json` so your stream configuration is never erased upon updating.
   - Create a **Desktop Shortcut** and **Start Menu entry** named `PECH NDI Bridge`.
   - Offer to launch the server immediately.
4. *Unattended/Silent Installation:*
   ```cmd
   PECH_NDI_WebRTC_Setup.exe --silent
   ```

### Option B: Standalone Portable Run
1. Copy the `dist\` folder to any location on your PC.
2. Double-click `start_server.bat` (or `PECH_NDI_WebRTC.exe`).
3. The server starts immediately using the parameters in `settings.json`.

### Option C: Running from Python Source
1. Ensure Python 3.10+ (64-bit) is installed.
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
3. Run:
   ```powershell
   python main.py
   ```
   *(Or double-click `start_server.bat`)*

---

## 4. Configuration Reference (`settings.json`)

The bridge reads from [`settings.json`](file:///d:/PECHNDIWEB/settings.json) located in the same directory as the executable.

```json
{
  "port": 8123,
  "server": {
    "http_port": 8123,
    "bind_address": "0.0.0.0"
  },
  "ndi": {
    "source_name": "STUDIO-PC (vMix - Output 1)",
    "color_format": "BGRX",
    "low_bandwidth": false
  },
  "video": {
    "target_width": 1280,
    "target_height": 720,
    "target_fps": 30,
    "bitrate_kbps": 2500,
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

### Key Parameters Explained

| Section | Key | Default | Description |
| :--- | :--- | :--- | :--- |
| **Root** | `"port"` | `8123` | Port used for the Web Player, WebRTC/WHEP, WebSocket, and REST API. |
| **`server`** | `"http_port"` | `8123` | Synced with top-level `"port"`. |
| | `"bind_address"` | `"0.0.0.0"` | Network interface to bind to (`0.0.0.0` listens on all LAN interfaces). |
| **`ndi`** | `"source_name"` | `""` | Exact name of the NDI stream (e.g. `"STUDIO-PC (vMix - Output 1)"`). Leave blank or scan via REST API. |
| | `"low_bandwidth"` | `false` | When `true`, requests NDI\|HX or low-bandwidth proxy stream from source if supported. |
| **`video`** | `"target_width"` | `1280` | Target horizontal resolution (720p optimizes bandwidth for multiple tablets). Set `0` for source native. |
| | `"target_height"` | `720` | Target vertical resolution. Set `0` for source native. |
| | `"target_fps"` | `30` | Framerate ceiling. 30 FPS significantly reduces tablet decoder load while keeping slides smooth. |
| | `"bitrate_kbps"` | `2500` | Target video bitrate (2.5 Mbps provides sharp slide text without Wi-Fi congestion). |
| | `"codec"` | `"H264"` | Video codec used for WebRTC (H.264 High Profile level 4.2 with zerolatency tuning). |
| **`app`** | `"auto_start"` | `true` | When `true`, automatically connects to the configured NDI source on startup. |

### Command-Line Overrides
You can override configuration values on the fly without editing `settings.json`:
```powershell
.\PECH_NDI_WebRTC.exe --port 8123 --source "STUDIO-PC (vMix - Output 1)"
```

---

## 5. REST API & State Control Guide

The bridge includes a FastAPI backend that allows operators, vMix macros, Stream Decks, and Companion controllers to pause, resume, and inspect the stream over the local network.

### 1. Pause / Resume Stream Control
**Endpoint:** `POST /api/stream/control`  
**Content-Type:** `application/json`

#### To Pause (with custom message):
```json
{
  "action": "pause",
  "message": "Pausing - slides will show again after video has played"
}
```
*What happens:*
1. Live NDI video capture pauses.
2. The WebRTC video track broadcasts a static black frame with the centered text message.
3. Connected tablets receive an instant WebSocket notification and display the message in large, high-contrast text.

#### To Resume (live slides):
```json
{
  "action": "resume"
}
```
*What happens:*
1. The overlay smoothly hides on all tablets.
2. Live NDI slides resume streaming immediately.

### 2. Convenience Endpoints (Quick HTTP Triggers)
Ideal for vMix Web Controller scripting, Stream Deck HTTP shortcuts, or simple curl commands:
- **Pause:** `POST http://<SERVER_IP>:8123/api/stream/pause?message=Pausing`
- **Resume:** `POST http://<SERVER_IP>:8123/api/stream/resume`

### 3. Stream Status
**Endpoint:** `GET /api/stream/status`  
Returns current stream health, pause status, viewer count, and active NDI stream:
```json
{
  "status": "ok",
  "action": "resume",
  "is_paused": false,
  "message": "",
  "ndi_source": "STUDIO-PC (vMix - Output 1)",
  "connected": true,
  "fps": 30.0,
  "width": 1280,
  "height": 720,
  "active_viewers": 4,
  "lan_ip": "192.168.1.50",
  "lan_url": "http://192.168.1.50:8123",
  "port": 8123
}
```

### 4. Remote NDI Source Discovery & Configuration
- **Discover Active Sources:** `GET /api/sources` (returns all active NDI senders on the LAN).
- **Inspect Settings:** `GET /api/settings`
- **Update Settings Remotely:** `POST /api/settings` (send JSON matching `settings.json` format).
- **Start Stream:** `POST /api/stream/start` (body: `{"source_name": "STUDIO-PC (vMix - Output 1)"}`)
- **Stop Stream:** `POST /api/stream/stop`

---

## 6. vMix Integration & Automation

You can easily trigger pauses from vMix whenever video playback starts or slides end:

### Method A: vMix Scripting (VB.NET)
In vMix **Settings > Scripting**, create a script named `PauseTablets`:
```vb
Dim url as String = "http://127.0.0.1:8123/api/stream/control"
Dim payload as String = "{""action"": ""pause"", ""message"": ""Pausing - slides will show again after video has played""}"

Dim request as System.Net.HttpWebRequest = System.Net.WebRequest.Create(url)
request.Method = "POST"
request.ContentType = "application/json"
Dim bytes() as Byte = System.Text.Encoding.UTF8.GetBytes(payload)
request.ContentLength = bytes.Length
Dim os as System.IO.Stream = request.GetRequestStream()
os.Write(bytes, 0, bytes.Length)
os.Close()
Dim resp as System.Net.WebResponse = request.GetResponse()
resp.Close()
```

Create a second script named `ResumeTablets`:
```vb
Dim url as String = "http://127.0.0.1:8123/api/stream/control"
Dim payload as String = "{""action"": ""resume""}"

Dim request as System.Net.HttpWebRequest = System.Net.WebRequest.Create(url)
request.Method = "POST"
request.ContentType = "application/json"
Dim bytes() as Byte = System.Text.Encoding.UTF8.GetBytes(payload)
request.ContentLength = bytes.Length
Dim os as System.IO.Stream = request.GetRequestStream()
os.Write(bytes, 0, bytes.Length)
os.Close()
Dim resp as System.Net.WebResponse = request.GetResponse()
resp.Close()
```

### Method B: vMix Triggers
Attach `ScriptStart` triggers to your video inputs:
- **OnTransitionIn**: Run script `PauseTablets`
- **OnTransitionOut**: Run script `ResumeTablets`

---

## 7. Android Tablet Setup (Kiosk Deployment)

1. Connect the tablet to your church local Wi-Fi network.
2. Open Google Chrome on the tablet and browse to:
   ```text
   http://<SERVER_IP>:8123
   ```
   *(e.g., `http://192.168.1.50:8123`)*
3. **Behavior on Tablet:**
   - The stream fills the entire screen edge-to-edge with no address bars or UI buttons.
   - If the server is offline or vMix has not yet started, the screen displays **"Waiting for Slides..."**.
   - As soon as the vMix stream starts, slides appear instantly without needing any physical screen interaction.
   - Right-click, pinch zoom, and double-tap zoom are locked to prevent accidental user manipulation.
   - Screen Wake Lock is automatically engaged so the screen will not turn off.

### Recommended Kiosk Lock-down (Optional)
To prevent church attendees from exiting the browser:
- **Android App Pinning**: Open Settings > Security > App Pinning (Pin Chrome).
- **Fully Kiosk Browser**: Install the free Fully Kiosk Browser APK and set `http://<SERVER_IP>:8123` as the start URL with full-screen and kiosk lock enabled.

---

## 8. Rebuilding the Standalone Executable & Installer

If you make modifications to the Python code or web assets:

1. Open PowerShell in the project directory.
2. Run:
   ```powershell
   python build_exe.py
   ```
3. The build script will:
   - Package `PECH_NDI_WebRTC.exe` via PyInstaller with all FastAPI, Uvicorn, and aiortc dependencies.
   - Sync `settings.json` and generate `start_server.bat`.
   - Package `PECH_NDI_WebRTC_Setup.exe` (Windows Setup Installer).
   - Generate `PECH_NDI_WebRTC_InnoSetup.iss`.
4. Outputs are saved to:
   - `dist\PECH_NDI_WebRTC.exe`
   - `dist\PECH_NDI_WebRTC_Setup.exe`
   - `dist\start_server.bat`
   - `dist\settings.json`
