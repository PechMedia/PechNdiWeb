"""
WebRTC Server & Media Engine for PECH NDI WebRTC Streaming Bridge
Provides near-zero latency WebRTC streaming (WHEP & WebSocket) and REST API.
"""

import asyncio
import fractions
import json
import logging
import os
import socket
import time
from typing import Set, Dict, Optional

import av
import numpy as np
from aiohttp import web
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCRtpSender,
    VideoStreamTrack,
    AudioStreamTrack,
    RTCConfiguration,
    RTCIceServer,
)
from aiortc.mediastreams import MediaStreamError

from ndi_core import NDIReceiver, NDIFinder, FOURCC_UYVY, FOURCC_BGRA, FOURCC_BGRX, FOURCC_RGBA, FOURCC_RGBX
from config_manager import ConfigManager

logger = logging.getLogger("webrtc_server")


def get_local_ip():
    """Finds the primary local network IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable, just forces socket to determine outgoing interface
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class NDIVideoTrack(VideoStreamTrack):
    """
    Ultra-low latency Video Track that bridges NDI frames into WebRTC.
    Uses a 1-frame fresh buffer to eliminate buffer lag.
    """
    kind = "video"

    def __init__(self, receiver: NDIReceiver, config: ConfigManager):
        super().__init__()
        self.receiver = receiver
        self.config = config
        self._start_time = None
        self._last_pts = 0
        self._frame_count = 0
        self._clock_rate = 90000
        self._time_base = fractions.Fraction(1, self._clock_rate)
        self._standby_frame = None

    def _create_standby_frame(self, width=1280, height=720, text="NO NDI SOURCE"):
        """Generates a placeholder dark test card when no source is connected."""
        arr = np.zeros((height, width, 3), dtype=np.uint8)
        # Add subtle dark gradient
        arr[:, :, 0] = 20
        arr[:, :, 1] = 24
        arr[:, :, 2] = 30
        frame = av.VideoFrame.from_ndarray(arr, format="bgr24")
        return frame

    async def recv(self):
        if self._start_time is None:
            self._start_time = time.perf_counter()

        # Wait up to 33ms for fresh frame
        frame_info = None
        for _ in range(7):
            with self.receiver._lock:
                frame_info = self.receiver.latest_video_frame
            if frame_info and (time.perf_counter() - frame_info.get("receive_time", 0)) < 0.5:
                break
            await asyncio.sleep(0.005)

        now = time.perf_counter()
        elapsed = now - self._start_time
        pts = int(elapsed * self._clock_rate)
        if pts <= self._last_pts:
            pts = self._last_pts + 1
        self._last_pts = pts

        if frame_info and "data" in frame_info:
            try:
                width = frame_info["width"]
                height = frame_info["height"]
                stride = frame_info["stride"]
                raw_data = frame_info["data"]
                fourcc = frame_info["fourcc"]

                # Handle BGRX / BGRA / UYVY formats
                if fourcc in (FOURCC_BGRX, FOURCC_BGRA):
                    # Direct 4-channel BGR0 / BGRA
                    row_bytes = width * 4
                    if stride == row_bytes:
                        img_arr = raw_data.reshape((height, width, 4))
                    else:
                        img_arr = raw_data.reshape((height, stride // 4, 4))[:, :width, :]
                    
                    # Convert to VideoFrame directly (av format 'bgr0' or 'bgra')
                    video_frame = av.VideoFrame.from_ndarray(img_arr[:, :, :3], format="bgr24")
                elif fourcc in (FOURCC_RGBA, FOURCC_RGBX):
                    row_bytes = width * 4
                    if stride == row_bytes:
                        img_arr = raw_data.reshape((height, width, 4))
                    else:
                        img_arr = raw_data.reshape((height, stride // 4, 4))[:, :width, :]
                    video_frame = av.VideoFrame.from_ndarray(img_arr[:, :, :3], format="rgb24")
                else:
                    # Fallback default
                    img_arr = raw_data[: height * width * 4].reshape((height, width, 4))
                    video_frame = av.VideoFrame.from_ndarray(img_arr[:, :, :3], format="bgr24")

                video_frame.pts = pts
                video_frame.time_base = self._time_base
                return video_frame

            except Exception as e:
                logger.warning(f"Error packing video frame: {e}")

        # If no frame or error, output standby frame
        if self._standby_frame is None:
            self._standby_frame = self._create_standby_frame()

        standby = av.VideoFrame.from_ndarray(self._standby_frame.to_ndarray(format="bgr24"), format="bgr24")
        standby.pts = pts
        standby.time_base = self._time_base
        return standby


class NDIAudioTrack(AudioStreamTrack):
    """
    Low latency Audio Track that bridges NDI audio into WebRTC (Opus).
    """
    kind = "audio"

    def __init__(self, receiver: NDIReceiver, config: ConfigManager):
        super().__init__()
        self.receiver = receiver
        self.config = config
        self._sample_rate = 48000
        self._channels = 2
        self._clock_rate = 48000
        self._time_base = fractions.Fraction(1, self._clock_rate)
        self._start_time = None
        self._last_pts = 0

    async def recv(self):
        if self._start_time is None:
            self._start_time = time.perf_counter()

        audio_info = None
        with self.receiver._lock:
            audio_info = self.receiver.latest_audio_frame

        # Opus typically consumes 960 samples per frame (20ms at 48kHz)
        samples_per_frame = 960

        now = time.perf_counter()
        elapsed = now - self._start_time
        pts = int(elapsed * self._clock_rate)
        if pts <= self._last_pts:
            pts = self._last_pts + samples_per_frame
        self._last_pts = pts

        if audio_info and (now - audio_info.get("receive_time", 0)) < 0.5:
            try:
                data = audio_info["data"]  # (channels, samples) float32
                channels = audio_info["channels"]
                samples = audio_info["samples"]

                if samples >= samples_per_frame:
                    chunk = data[:2, :samples_per_frame]
                else:
                    chunk = np.zeros((2, samples_per_frame), dtype=np.float32)
                    chunk[:min(channels, 2), :samples] = data[:min(channels, 2), :]

                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
                frame.sample_rate = self._sample_rate
                frame.pts = pts
                frame.time_base = self._time_base
                return frame
            except Exception as e:
                logger.warning(f"Error packing audio frame: {e}")

        # Silence packet
        silence = np.zeros((2, samples_per_frame), dtype=np.float32)
        frame = av.AudioFrame.from_ndarray(silence, format="fltp", layout="stereo")
        frame.sample_rate = self._sample_rate
        frame.pts = pts
        frame.time_base = self._time_base
        return frame


class WebRTCStreamServer:
    """
    Full WebRTC Server managing NDI Ingestion, Peer Connections, WHEP & WebSocket signaling,
    and HTTP API/Static Web serving.
    """

    def __init__(self, config: ConfigManager, web_dir: str):
        self.config = config
        self.web_dir = web_dir
        self.receiver = NDIReceiver(
            source_name=self.config.get("ndi", "source_name", ""),
            low_bandwidth=self.config.get("ndi", "low_bandwidth", False),
        )
        self.pcs: Set[RTCPeerConnection] = set()
        self.finder = None
        self.app = web.Application()
        self.runner = None
        self.site = None
        self._setup_routes()

    def _setup_routes(self):
        # API Routes
        self.app.router.add_get("/api/status", self._handle_status)
        self.app.router.add_get("/api/sources", self._handle_sources)
        self.app.router.add_get("/api/settings", self._handle_get_settings)
        self.app.router.add_post("/api/settings", self._handle_save_settings)
        self.app.router.add_post("/api/stream/start", self._handle_stream_start)
        self.app.router.add_post("/api/stream/stop", self._handle_stream_stop)

        # Signaling Routes
        self.app.router.add_post("/api/whep", self._handle_whep)
        self.app.router.add_get("/ws", self._handle_websocket)

        # Static Web App
        self.app.router.add_static("/static", os.path.join(self.web_dir, "static"), name="static")
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/admin", self._handle_admin)

    async def _handle_index(self, request):
        index_file = os.path.join(self.web_dir, "index.html")
        if os.path.exists(index_file):
            return web.FileResponse(index_file)
        return web.Response(text="PECH NDI WebRTC Player - Index file missing", status=404)

    async def _handle_admin(self, request):
        admin_file = os.path.join(self.web_dir, "admin.html")
        if os.path.exists(admin_file):
            return web.FileResponse(admin_file)
        return web.FileResponse(os.path.join(self.web_dir, "index.html"))

    async def _handle_status(self, request):
        local_ip = get_local_ip()
        port = self.config.get("server", "http_port", 8080)
        with self.receiver._lock:
            stats = dict(self.receiver.stats)

        response_data = {
            "ndi_source": self.receiver.source_name or "None",
            "connected": stats.get("connected", False),
            "fps": stats.get("fps", 0.0),
            "width": stats.get("width", 0),
            "height": stats.get("height", 0),
            "frames_received": stats.get("frames_received", 0),
            "active_viewers": len(self.pcs),
            "lan_ip": local_ip,
            "lan_url": f"http://{local_ip}:{port}",
            "settings": self.config.settings,
        }
        return web.json_response(response_data)

    async def _handle_sources(self, request):
        try:
            if not self.finder:
                self.finder = NDIFinder()
            sources = await asyncio.to_thread(self.finder.get_sources, 1000)
            return web.json_response({"sources": sources})
        except Exception as e:
            logger.error(f"Failed to find NDI sources: {e}")
            return web.json_response({"sources": [], "error": str(e)}, status=500)

    async def _handle_get_settings(self, request):
        return web.json_response(self.config.settings)

    async def _handle_save_settings(self, request):
        try:
            data = await request.json()
            self.config.update(data)
            # If source name changed, re-connect receiver
            new_source = self.config.get("ndi", "source_name", "")
            if new_source != self.receiver.source_name:
                self.receiver.connect(new_source)
            return web.json_response({"status": "ok", "settings": self.config.settings})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=400)

    async def _handle_stream_start(self, request):
        try:
            data = await request.json() if request.can_read_body else {}
            source_name = data.get("source_name", self.config.get("ndi", "source_name", ""))
            if source_name:
                self.config.update({"ndi": {"source_name": source_name}})
                self.receiver.connect(source_name)
            self.receiver.start()
            return web.json_response({"status": "ok", "active_source": self.receiver.source_name})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_stream_stop(self, request):
        self.receiver.stop()
        return web.json_response({"status": "ok", "message": "Stream stopped"})

    async def _create_peer_connection(self) -> RTCPeerConnection:
        # Standard configuration for LAN WebRTC
        config = RTCConfiguration(iceServers=[])
        pc = RTCPeerConnection(configuration=config)
        self.pcs.add(pc)

        video_track = NDIVideoTrack(self.receiver, self.config)
        audio_track = NDIAudioTrack(self.receiver, self.config)

        pc.addTrack(video_track)
        pc.addTrack(audio_track)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"PeerConnection state is {pc.connectionState}")
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await pc.close()
                self.pcs.discard(pc)

        return pc

    async def _handle_whep(self, request):
        """WebRTC HTTP Egress Protocol (WHEP) implementation."""
        offer_sdp = await request.text()
        if not offer_sdp:
            return web.Response(status=400, text="Missing SDP offer in request body")

        pc = await self._create_peer_connection()
        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
        await pc.setRemoteDescription(offer)

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        response_headers = {
            "Content-Type": "application/sdp",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
        return web.Response(text=pc.localDescription.sdp, headers=response_headers, status=201)

    async def _handle_websocket(self, request):
        """WebSocket signaling endpoint for browser clients."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        pc = await self._create_peer_connection()

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "offer":
                        offer = RTCSessionDescription(sdp=data["sdp"], type="offer")
                        await pc.setRemoteDescription(offer)
                        answer = await pc.createAnswer()
                        await pc.setLocalDescription(answer)

                        await ws.send_str(json.dumps({
                            "type": "answer",
                            "sdp": pc.localDescription.sdp,
                        }))

                    elif msg_type == "ice":
                        # Add candidate if available
                        candidate = data.get("candidate")
                        if candidate:
                            pass
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
        finally:
            await pc.close()
            self.pcs.discard(pc)

        return ws

    async def start(self):
        port = self.config.get("server", "http_port", 8080)
        host = self.config.get("server", "bind_address", "0.0.0.0")

        # Auto-start NDI receiver if enabled
        if self.config.get("app", "auto_start", True):
            source_name = self.config.get("ndi", "source_name", "")
            if source_name:
                self.receiver.connect(source_name)
            self.receiver.start()

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()

        local_ip = get_local_ip()
        logger.info(f"==================================================")
        logger.info(f" PECH NDI WebRTC Server is RUNNING")
        logger.info(f" Local Web View:   http://localhost:{port}")
        logger.info(f" Network Web View: http://{local_ip}:{port}")
        logger.info(f" Admin Dashboard:  http://{local_ip}:{port}/admin")
        logger.info(f"==================================================")

    async def stop(self):
        logger.info("Stopping WebRTC server...")
        for pc in list(self.pcs):
            await pc.close()
        self.pcs.clear()

        self.receiver.stop()
        if self.finder:
            self.finder.close()
            self.finder = None

        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
