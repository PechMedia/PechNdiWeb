# PECH NDI-to-WebRTC Low-Latency LAN Streaming Bridge

A high-performance Windows application that decodes live **NDI** and **NDI|HX** video/audio streams and encodes them into **near-zero latency (<50ms)** WebRTC streams for real-time viewing on any browser or device across your Local Area Network (LAN).

---

## Key Features

- **Near-Zero Latency**: Direct 1-frame uncompressed NDI memory pipeline directly to WebRTC RTP/SRTP over UDP.
- **NDI & NDI|HX Support**: Discovers and decodes full-bandwidth NDI (SpeedHQ/BGRX) and NDI|HX streams via NDI 6 SDK.
- **Dual Execution Modes**:
  - **Headless Mode (`--headless`)**: Runs quietly in the background (as a CLI app or Windows service), reading from `settings.json`.
  - **UI Mode (Default)**: Opens a modern Windows 11 desktop window (powered by Microsoft Edge WebView2) with live stream discovery, stream controls, real-time preview player, and QR code sharing.
- **Any-Device Playback**: Any phone, tablet, PC, Mac, or Smart TV on the same Wi-Fi/LAN can open the stream without installing any apps or browser extensions.
- **JSON Configuration**: Complete settings persistence in `settings.json`.
- **WHEP & WebSocket Signaling**: Native WebRTC HTTP Egress Protocol (WHEP) and WebSocket support.

---

## Quick Start

### 1. Requirements
- Windows 10 / Windows 11 (64-bit)
- NDI 6 Runtime or NDI 6 SDK installed (`Processing.NDI.Lib.x64.dll`)
- Python 3.10+ (or prebuilt `.exe`)

### 2. Running with Desktop UI
```bash
python main.py
```
*Opens the desktop configuration window where you can discover NDI sources, adjust parameters, preview the live stream, and copy/scan the LAN URL.*

### 3. Running in Headless Mode
```bash
python main.py --headless
```
*Starts the server using parameters from `settings.json` without opening a GUI window.*

#### CLI Options
```bash
python main.py --headless --port 8080 --source "STUDIO-PC (Camera 1)"
```
- `--headless`: Run as a background service/daemon without UI.
- `--port <PORT>`: Web / WebRTC signaling port (default: 8080).
- `--source "<NAME>"`: Override NDI source name.
- `--config <PATH>`: Custom path to JSON configuration file.
- `--bind <IP>`: IP address to bind to (default: `0.0.0.0`).

---

## Configuration (`settings.json`)

```json
{
  "server": {
    "http_port": 8080,
    "bind_address": "0.0.0.0"
  },
  "ndi": {
    "source_name": "DESKTOP-ABC (OBS NDI)",
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

## Building Standalone Windows Executable

To bundle into a standalone executable:
```bash
python build_exe.py
```
Output will be generated in `dist/PECH_NDI_WebRTC/PECH_NDI_WebRTC.exe`.
