"""
WebRTC Server & Media Engine for PECH NDI WebRTC Streaming Bridge
FastAPI-based WHEP / WebSocket streaming server with dynamic state & pause message overlay.
"""

import asyncio
import fractions
import json
import logging
import os
import socket
import time
from typing import Set, Dict, Optional, Any

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel

from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
    RTCConfiguration,
)
import aiortc.codecs.h264
import aiortc.codecs.vpx
import aiortc.rtcpeerconnection
import aiortc.rtcrtpsender
from aiortc.codecs import CODECS
from aiortc.codecs.h264 import H264Encoder
from aiortc.rtcrtpsender import get_encoder as _aiortc_get_encoder
from aiortc.rtcrtpparameters import RTCRtpCodecParameters, RTCRtcpFeedback
from aiortc.sdp import H264Profile, parse_h264_profile_level_id
from av.video.frame import PictureType

from ndi_core import NDIReceiver, NDIFinder, FOURCC_UYVY, FOURCC_BGRA, FOURCC_BGRX, FOURCC_RGBA, FOURCC_RGBX
from config_manager import ConfigManager

logger = logging.getLogger("webrtc_server")


def get_local_ip() -> str:
    """Finds the primary local network IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def apply_encoder_bitrate_settings(config: ConfigManager):
    """Applies video.bitrate_kbps as the encoders' start and ceiling bitrate."""
    kbps = int(config.get("video", "bitrate_kbps", 0) or 0)
    if kbps <= 0:
        return
    bps = kbps * 1000
    for mod in (aiortc.codecs.h264, aiortc.codecs.vpx):
        mod.DEFAULT_BITRATE = bps
        mod.MAX_BITRATE = max(bps, mod.MIN_BITRATE)


class H264HighProfileEncoder(H264Encoder):
    """Encodes H.264 High profile (CABAC + 8x8 transforms) for sharper text/detail."""

    def _encode_frame(self, frame, force_keyframe):
        if self.codec and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
            or abs(self.target_bitrate - self.codec.bit_rate) / self.codec.bit_rate > 0.1
        ):
            self.buffer_data = b""
            self.buffer_pts = None
            self.codec = None

        if force_keyframe:
            frame.pict_type = PictureType.I
        else:
            frame.pict_type = PictureType.NONE

        if self.codec is None:
            self.codec = av.CodecContext.create("libx264", "w")
            self.codec.width = frame.width
            self.codec.height = frame.height
            self.codec.bit_rate = self.target_bitrate
            self.codec.pix_fmt = "yuv420p"
            self.codec.framerate = fractions.Fraction(aiortc.codecs.h264.MAX_FRAME_RATE, 1)
            self.codec.time_base = fractions.Fraction(1, aiortc.codecs.h264.MAX_FRAME_RATE)
            self.codec.options = {
                "level": "51" if frame.width * frame.height > 1920 * 1080 else "42",
                "tune": "zerolatency",
                "preset": "veryfast",
            }
            self.codec.profile = "High"

        data_to_send = b""
        for package in self.codec.encode(frame):
            data_to_send += bytes(package)

        if data_to_send:
            yield from self._split_bitstream(data_to_send)


_H264_HIGH_PROFILES = (H264Profile.PROFILE_HIGH, H264Profile.PROFILE_CONSTRAINED_HIGH)
_H264_HIGH_APPLIED = False


def apply_h264_high_profile_support():
    """Advertises and encodes H.264 High profile when supported."""
    global _H264_HIGH_APPLIED
    if _H264_HIGH_APPLIED:
        return
    _H264_HIGH_APPLIED = True

    for pt, plid in ((103, "640c2a"), (104, "64002a")):
        CODECS["video"].append(
            RTCRtpCodecParameters(
                mimeType="video/H264",
                clockRate=90000,
                payloadType=pt,
                rtcpFeedback=[
                    RTCRtcpFeedback(type="nack"),
                    RTCRtcpFeedback(type="nack", parameter="pli"),
                    RTCRtcpFeedback(type="goog-remb"),
                ],
                parameters={
                    "level-asymmetry-allowed": "1",
                    "packetization-mode": "1",
                    "profile-level-id": plid,
                },
            )
        )

    def _h264_profile(codec):
        try:
            return parse_h264_profile_level_id(
                str(codec.parameters.get("profile-level-id", "42E01F"))
            )[0]
        except ValueError:
            return None

    _orig_find_common = aiortc.rtcpeerconnection.find_common_codecs

    def _find_common_codecs_prefer_high(local_codecs, remote_codecs):
        common = _orig_find_common(local_codecs, remote_codecs)
        high = []
        rest = []
        for c in common:
            if c.mimeType.lower() == "video/h264" and _h264_profile(c) in _H264_HIGH_PROFILES:
                high.append(c)
            else:
                rest.append(c)
        high.sort(key=lambda c: 0 if _h264_profile(c) == H264Profile.PROFILE_HIGH else 1)
        return high + rest

    aiortc.rtcpeerconnection.find_common_codecs = _find_common_codecs_prefer_high

    def _get_encoder(codec):
        if codec.mimeType.lower() == "video/h264" and _h264_profile(codec) in _H264_HIGH_PROFILES:
            return H264HighProfileEncoder()
        return _aiortc_get_encoder(codec)

    aiortc.rtcrtpsender.get_encoder = _get_encoder


def create_text_frame(text: str, width: int = 1280, height: int = 720) -> np.ndarray:
    """Renders high-contrast centered text on a black 16:9 canvas using PIL."""
    img = Image.new("RGB", (width, height), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = max(28, int(height * 0.055))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    max_text_width = width - 160
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_w = bbox[2] - bbox[0]
        if line_w > max_text_width:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
        else:
            current_line.append(word)
    if current_line:
        lines.append(" ".join(current_line))

    line_height = int(font_size * 1.4)
    total_height = len(lines) * line_height
    start_y = max(40, (height - total_height) // 2)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        y = start_y + i * line_height
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    return np.array(img)


class StreamStateManager:
    """Manages stream pause/resume state and pushes broadcast updates to clients."""

    def __init__(self):
        self.action: str = "resume"
        self.message: str = ""
        self.ws_clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._cached_frame: Optional[np.ndarray] = None
        self._cached_key: Optional[str] = None

    @property
    def is_paused(self) -> bool:
        return self.action == "pause"

    async def set_state(self, action: str, message: Optional[str] = None):
        async with self._lock:
            self.action = action
            if message is not None:
                self.message = message
            elif action == "resume":
                self.message = ""

            msg_payload = {
                "type": "status",
                "action": self.action,
                "message": self.message,
                "is_paused": self.is_paused,
            }

        # Broadcast update to connected WebSockets
        for ws in list(self.ws_clients):
            try:
                await ws.send_json(msg_payload)
            except Exception:
                self.ws_clients.discard(ws)

    def get_pause_frame(self, width: int = 1280, height: int = 720) -> np.ndarray:
        key = f"{self.message}_{width}_{height}"
        if self._cached_frame is None or self._cached_key != key:
            text = self.message or "Stream Paused"
            self._cached_frame = create_text_frame(text, width=width, height=height)
            self._cached_key = key
        return self._cached_frame


class NDIVideoTrack(VideoStreamTrack):
    """
    Ultra-low latency Video Track bridging NDI frames into WebRTC.
    When paused, broadcasts a clean static black frame with centered text.
    """
    kind = "video"

    def __init__(self, receiver: NDIReceiver, config: ConfigManager, state_mgr: StreamStateManager):
        super().__init__()
        self.receiver = receiver
        self.config = config
        self.state_mgr = state_mgr
        self._start_time = None
        self._last_pts = 0
        self._clock_rate = 90000
        self._time_base = fractions.Fraction(1, self._clock_rate)
        self._standby_frame_arr = None
        self._last_processed_receive_time = 0.0
        self._last_emit_time = 0.0

    def _get_target_dims(self):
        target_w = int(self.config.get("video", "target_width", 1280) or 1280)
        target_h = int(self.config.get("video", "target_height", 720) or 720)
        return target_w, target_h

    def _get_standby_frame(self, width: int, height: int) -> np.ndarray:
        if self._standby_frame_arr is None or self._standby_frame_arr.shape[:2] != (height, width):
            self._standby_frame_arr = create_text_frame("Waiting for Slides...", width=width, height=height)
        return self._standby_frame_arr

    async def recv(self):
        if self._start_time is None:
            self._start_time = time.perf_counter()

        target_fps = int(self.config.get("video", "target_fps", 30) or 30)
        if target_fps > 0 and self._last_emit_time > 0:
            wait = (self._last_emit_time + 1.0 / target_fps) - time.perf_counter()
            if wait > 0:
                await asyncio.sleep(wait)

        now = time.perf_counter()
        elapsed = now - self._start_time
        pts = int(elapsed * self._clock_rate)
        if pts <= self._last_pts:
            pts = self._last_pts + 1
        self._last_pts = pts

        target_w, target_h = self._get_target_dims()

        # 1. Check if stream is in paused state
        if self.state_mgr.is_paused:
            frame_arr = self.state_mgr.get_pause_frame(target_w, target_h)
            video_frame = av.VideoFrame.from_ndarray(frame_arr, format="rgb24")
            video_frame.pts = pts
            video_frame.time_base = self._time_base
            self._last_emit_time = time.perf_counter()
            return video_frame

        # 2. Check for live NDI frame
        frame_info = None
        for _ in range(10):
            with self.receiver._lock:
                fi = self.receiver.latest_video_frame
            if fi and fi.get("receive_time", 0) > getattr(self, '_last_processed_receive_time', 0):
                frame_info = fi
                self._last_processed_receive_time = frame_info["receive_time"]
                break
            await asyncio.sleep(0.005)

        if not frame_info:
            with self.receiver._lock:
                fi = self.receiver.latest_video_frame
            if fi and (time.perf_counter() - fi.get("receive_time", 0)) < 1.0:
                frame_info = fi

        if frame_info and "data" in frame_info:
            try:
                width = frame_info["width"]
                height = frame_info["height"]
                stride = frame_info["stride"]
                raw_data = frame_info["data"]
                fourcc = frame_info["fourcc"]

                if fourcc == FOURCC_UYVY:
                    row_bytes = width * 2
                    video_frame = av.VideoFrame(width, height, format="uyvy422")
                    if stride == row_bytes:
                        video_frame.planes[0].update(raw_data)
                    else:
                        img_arr = raw_data.reshape((height, stride // 2, 2))[:, :width, :]
                        video_frame.planes[0].update(img_arr.tobytes())
                elif fourcc in (FOURCC_BGRX, FOURCC_BGRA):
                    row_bytes = width * 4
                    if stride == row_bytes:
                        img_arr = raw_data.reshape((height, width, 4))
                    else:
                        img_arr = raw_data.reshape((height, stride // 4, 4))[:, :width, :]
                    video_frame = av.VideoFrame.from_ndarray(img_arr, format="bgr0")
                elif fourcc in (FOURCC_RGBA, FOURCC_RGBX):
                    row_bytes = width * 4
                    if stride == row_bytes:
                        img_arr = raw_data.reshape((height, width, 4))
                    else:
                        img_arr = raw_data.reshape((height, stride // 4, 4))[:, :width, :]
                    video_frame = av.VideoFrame.from_ndarray(img_arr[:, :, :3], format="rgb24")
                else:
                    img_arr = raw_data[: height * width * 4].reshape((height, width, 4))
                    video_frame = av.VideoFrame.from_ndarray(img_arr[:, :, :3], format="bgr24")

                # Scale to target resolution (e.g. 720p for low-bandwidth tablet streaming)
                if target_w > 0 and target_h > 0 and (video_frame.width != target_w or video_frame.height != target_h):
                    video_frame = video_frame.reformat(width=target_w, height=target_h)

                video_frame.pts = pts
                video_frame.time_base = self._time_base
                self._last_emit_time = time.perf_counter()
                return video_frame
            except Exception as e:
                logger.warning(f"Error packing video frame: {e}")

        # 3. No live frames yet: output waiting standby frame
        standby_arr = self._get_standby_frame(target_w, target_h)
        standby = av.VideoFrame.from_ndarray(standby_arr, format="rgb24")
        standby.pts = pts
        standby.time_base = self._time_base
        self._last_emit_time = time.perf_counter()
        return standby


class StreamControlRequest(BaseModel):
    action: str
    message: Optional[str] = ""


class WebRTCStreamServer:
    """
    FastAPI WebRTC Streaming Bridge Server.
    Provides WHEP & WebSocket signaling, REST state controls, and serves kiosk Web UI.
    """

    def __init__(self, config: ConfigManager, web_dir: str):
        self.config = config
        self.web_dir = web_dir
        apply_encoder_bitrate_settings(config)
        apply_h264_high_profile_support()

        self.state_mgr = StreamStateManager()
        self.receiver = NDIReceiver(
            source_name=self.config.get("ndi", "source_name", ""),
            low_bandwidth=self.config.get("ndi", "low_bandwidth", False),
        )
        self.pcs: Set[RTCPeerConnection] = set()
        self.finder = None

        self.app = FastAPI(
            title="PECH NDI-to-WebRTC Streaming Bridge",
            description="Ultra-low latency NDI to WebRTC/WHEP tablet streamer with REST state control",
            version="1.0.16",
        )

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Location", "Content-Type"],
        )

        self.server = None
        self._setup_routes()

    def _setup_routes(self):
        app = self.app

        # Mount static directory
        static_path = os.path.join(self.web_dir, "static")
        if os.path.exists(static_path):
            app.mount("/static", StaticFiles(directory=static_path), name="static")

        # Root Kiosk Web App for Android Tablets
        @app.get("/", response_class=FileResponse)
        async def get_index():
            index_file = os.path.join(self.web_dir, "index.html")
            if os.path.exists(index_file):
                return FileResponse(index_file, media_type="text/html")
            raise HTTPException(status_code=404, detail="index.html not found")

        # Static assets at root for PWA / Service Worker / Cast receiver
        @app.get("/sw.js", response_class=FileResponse)
        async def get_sw():
            p = os.path.join(os.path.dirname(self.web_dir), "sw.js")
            if os.path.exists(p):
                return FileResponse(p, media_type="application/javascript")
            raise HTTPException(status_code=404)

        @app.get("/config.js", response_class=FileResponse)
        async def get_config_js():
            p = os.path.join(os.path.dirname(self.web_dir), "config.js")
            if os.path.exists(p):
                return FileResponse(p, media_type="application/javascript")
            raise HTTPException(status_code=404)

        @app.get("/receiver.html", response_class=FileResponse)
        async def get_receiver():
            p = os.path.join(os.path.dirname(self.web_dir), "receiver.html")
            if os.path.exists(p):
                return FileResponse(p, media_type="text/html")
            raise HTTPException(status_code=404)

        # ------------------------------------------------------------------
        # Core REST Control Endpoint (Pause / Resume / Message Overlay)
        # ------------------------------------------------------------------
        @app.post("/api/stream/control")
        async def post_stream_control(req: StreamControlRequest):
            action = req.action.strip().lower()
            if action not in ("pause", "resume", "stop", "start"):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid action. Expected 'pause' or 'resume'."
                )

            # Map start/stop to resume/pause
            normalized_action = "pause" if action in ("pause", "stop") else "resume"
            await self.state_mgr.set_state(normalized_action, req.message)
            logger.info(f"Stream control executed: action={normalized_action}, message='{req.message}'")

            return {
                "status": "ok",
                "action": self.state_mgr.action,
                "is_paused": self.state_mgr.is_paused,
                "message": self.state_mgr.message,
            }

        # Convenience aliases for vMix / macros / scripts
        @app.post("/api/stream/pause")
        async def post_stream_pause(message: Optional[str] = "Pausing - slides will show again shortly"):
            await self.state_mgr.set_state("pause", message)
            return {
                "status": "ok",
                "action": "pause",
                "is_paused": True,
                "message": self.state_mgr.message,
            }

        @app.post("/api/stream/resume")
        async def post_stream_resume():
            await self.state_mgr.set_state("resume", "")
            return {
                "status": "ok",
                "action": "resume",
                "is_paused": False,
                "message": "",
            }

        # ------------------------------------------------------------------
        # Status & Diagnostics
        # ------------------------------------------------------------------
        @app.get("/api/stream/status")
        @app.get("/api/status")
        async def get_status():
            local_ip = get_local_ip()
            port = self.config.settings.get("port") or self.config.get("server", "http_port", 8123)
            with self.receiver._lock:
                stats = dict(self.receiver.stats)

            return {
                "status": "ok",
                "action": self.state_mgr.action,
                "is_paused": self.state_mgr.is_paused,
                "message": self.state_mgr.message,
                "ndi_source": self.receiver.source_name or "None",
                "connected": stats.get("connected", False),
                "fps": stats.get("fps", 0.0),
                "width": stats.get("width", 0),
                "height": stats.get("height", 0),
                "frames_received": stats.get("frames_received", 0),
                "active_viewers": len(self.pcs),
                "lan_ip": local_ip,
                "lan_url": f"http://{local_ip}:{port}",
                "port": port,
                "settings": self.config.settings,
            }

        # ------------------------------------------------------------------
        # NDI Source Discovery & Configuration API
        # ------------------------------------------------------------------
        @app.get("/api/sources")
        async def get_sources():
            try:
                if not self.finder:
                    self.finder = NDIFinder()
                sources = await asyncio.to_thread(self.finder.get_sources, 1000)
                return {"sources": sources}
            except Exception as e:
                logger.error(f"Failed to find NDI sources: {e}")
                return JSONResponse(status_code=500, content={"sources": [], "error": str(e)})

        @app.get("/api/settings")
        async def get_settings():
            return self.config.settings

        @app.post("/api/settings")
        async def save_settings(request: Request):
            try:
                data = await request.json()
                self.config.update(data)
                apply_encoder_bitrate_settings(self.config)
                new_source = self.config.get("ndi", "source_name", "")
                if new_source != self.receiver.source_name:
                    self.receiver.connect(new_source)
                return {"status": "ok", "settings": self.config.settings}
            except Exception as e:
                return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

        @app.post("/api/stream/start")
        async def start_stream(request: Request):
            try:
                body = await request.body()
                data = json.loads(body.decode()) if body else {}
                source_name = data.get("source_name", self.config.get("ndi", "source_name", ""))
                if source_name:
                    self.config.update({"ndi": {"source_name": source_name}})
                    self.receiver.connect(source_name)
                self.receiver.start()
                return {"status": "ok", "active_source": self.receiver.source_name}
            except Exception as e:
                return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

        @app.post("/api/stream/stop")
        async def stop_stream():
            self.receiver.stop()
            return {"status": "ok", "message": "Stream stopped"}

        # ------------------------------------------------------------------
        # WHEP Signaling (WebRTC HTTP Egress Protocol)
        # ------------------------------------------------------------------
        @app.options("/api/whep")
        @app.options("/whep")
        @app.options("/")
        async def whep_options():
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Expose-Headers": "Location",
                },
            )

        @app.post("/api/whep")
        @app.post("/whep")
        async def whep_post(request: Request):
            body = await request.body()
            offer_sdp = body.decode("utf-8")
            if not offer_sdp:
                raise HTTPException(status_code=400, detail="Missing SDP offer in request body")

            pc = await self._create_peer_connection()
            offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
            await pc.setRemoteDescription(offer)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            return Response(
                content=pc.localDescription.sdp,
                media_type="application/sdp",
                status_code=201,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Expose-Headers": "Location",
                    "Location": "/api/whep",
                },
            )

        # ------------------------------------------------------------------
        # WebSocket Signaling & Real-time State Updates
        # ------------------------------------------------------------------
        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.state_mgr.ws_clients.add(websocket)

            # Send immediate stream state on connect
            await websocket.send_json({
                "type": "status",
                "action": self.state_mgr.action,
                "message": self.state_mgr.message,
                "is_paused": self.state_mgr.is_paused,
            })

            pc: Optional[RTCPeerConnection] = None

            try:
                while True:
                    data_str = await websocket.receive_text()
                    data = json.loads(data_str)
                    msg_type = data.get("type")

                    if msg_type == "offer":
                        if pc is None:
                            pc = await self._create_peer_connection()
                        offer = RTCSessionDescription(sdp=data["sdp"], type="offer")
                        await pc.setRemoteDescription(offer)
                        answer = await pc.createAnswer()
                        await pc.setLocalDescription(answer)

                        await websocket.send_json({
                            "type": "answer",
                            "sdp": pc.localDescription.sdp,
                        })

                    elif msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

            except (WebSocketDisconnect, Exception):
                pass
            finally:
                self.state_mgr.ws_clients.discard(websocket)
                if pc:
                    await pc.close()
                    self.pcs.discard(pc)

    async def _create_peer_connection(self) -> RTCPeerConnection:
        """Creates a strictly video-only WebRTC PeerConnection for mobile autoplay."""
        config = RTCConfiguration(iceServers=[])
        pc = RTCPeerConnection(configuration=config)
        self.pcs.add(pc)

        # Add video track ONLY (strictly no audio track to comply with mobile autoplay policies)
        video_track = NDIVideoTrack(self.receiver, self.config, self.state_mgr)
        pc.addTrack(video_track)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"PeerConnection state is {pc.connectionState}")
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await pc.close()
                self.pcs.discard(pc)

        return pc

    async def start(self):
        """Starts the NDI receiver and launches the Uvicorn ASGI server."""
        port = int(self.config.settings.get("port") or self.config.get("server", "http_port", 8123))
        host = self.config.get("server", "bind_address", "0.0.0.0")

        if self.config.get("app", "auto_start", True):
            source_name = self.config.get("ndi", "source_name", "")
            if source_name:
                self.receiver.connect(source_name)
            self.receiver.start()

        local_ip = get_local_ip()
        logger.info("==================================================")
        logger.info(" PECH NDI-to-WebRTC Bridge (FastAPI Backend)")
        logger.info(f" Web Player (Kiosk): http://{local_ip}:{port}")
        logger.info(f" REST API Control:   POST http://{local_ip}:{port}/api/stream/control")
        logger.info(f" Stream Status:      GET  http://{local_ip}:{port}/api/stream/status")
        logger.info(f" WHEP Endpoint:      POST http://{local_ip}:{port}/api/whep")
        logger.info(f" WebSocket Endpoint: ws://{local_ip}:{port}/ws")
        logger.info("==================================================")

        uvicorn_config = uvicorn.Config(
            self.app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
        )
        self.server = uvicorn.Server(uvicorn_config)
        await self.server.serve()

    async def stop(self):
        """Gracefully tears down active connections, receiver, and ASGI server."""
        logger.info("Stopping WebRTC streaming server...")
        if self.server:
            self.server.should_exit = True

        for pc in list(self.pcs):
            try:
                await pc.close()
            except Exception:
                pass
        self.pcs.clear()

        self.receiver.stop()
        if self.finder:
            self.finder.close()
            self.finder = None
        logger.info("Server shutdown complete.")
