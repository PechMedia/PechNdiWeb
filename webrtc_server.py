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

import datetime
import ipaddress
import ssl
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def ensure_ssl_certificates(cert_path="cert.pem", key_path="key.pem", ip="127.0.0.1"):
    """Auto-generates self-signed TLS certificates with SAN for localhost and local IP."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_full = os.path.join(base_dir, cert_path)
    key_full = os.path.join(base_dir, key_path)

    if os.path.exists(cert_full) and os.path.exists(key_full):
        return cert_full, key_full

    try:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "PECH NDI Bridge"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PechMedia"),
        ])
        
        san_list = [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
        if ip and ip not in ("127.0.0.1", "0.0.0.0"):
            try:
                san_list.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
            except Exception:
                pass

        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .sign(key, hashes.SHA256())
        )

        with open(key_full, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))

        with open(cert_full, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        return cert_full, key_full
    except Exception as e:
        logger.warning(f"Failed to auto-generate SSL certs: {e}")
        return cert_full, key_full



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


def apply_encoder_bitrate_settings(config: ConfigManager):
    """Applies video.bitrate_kbps as the encoders' start and ceiling bitrate.

    aiortc exposes no sender bitrate API; its H.264/VP8 encoders read these
    module globals at construction and REMB only adjusts within [MIN, MAX].
    Affects peer connections created after the call.
    """
    kbps = int(config.get("video", "bitrate_kbps", 0) or 0)
    if kbps <= 0:
        return
    bps = kbps * 1000
    for mod in (aiortc.codecs.h264, aiortc.codecs.vpx):
        mod.DEFAULT_BITRATE = bps
        mod.MAX_BITRATE = max(bps, mod.MIN_BITRATE)


class H264HighProfileEncoder(H264Encoder):
    """Encodes H.264 High profile (CABAC + 8x8 transforms) for sharper text/detail.

    Mirrors aiortc 1.15 H264Encoder._encode_frame, replacing the hardcoded
    Baseline profile / level 3.1 with High profile and a resolution-appropriate level.
    """

    def _encode_frame(self, frame, force_keyframe):
        if self.codec and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
            # we only adjust bitrate if it changes by over 10%
            or abs(self.target_bitrate - self.codec.bit_rate) / self.codec.bit_rate
            > 0.1
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
    """Advertises and encodes H.264 High profile when the viewer's browser offers it.

    aiortc 1.15 only advertises Baseline (42001f/42e01f) and encodes Baseline
    level 3.1, which softens text and fine detail. This patch adds High /
    Constrained-High level 4.2 entries, prefers them in negotiation, and routes
    them to H264HighProfileEncoder. Browsers offering only Baseline keep the
    original behavior. Idempotent.
    """
    global _H264_HIGH_APPLIED
    if _H264_HIGH_APPLIED:
        return
    _H264_HIGH_APPLIED = True

    # 1) Advertise Constrained-High and High level 4.2 (level-asymmetry allowed)
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

    # 2) Prefer High-family entries so they become the selected codec
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

    # 3) Encode High only when a High-family profile was actually negotiated
    def _get_encoder(codec):
        if codec.mimeType.lower() == "video/h264" and _h264_profile(codec) in _H264_HIGH_PROFILES:
            return H264HighProfileEncoder()
        return _aiortc_get_encoder(codec)

    aiortc.rtcrtpsender.get_encoder = _get_encoder


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
        self._last_processed_receive_time = 0.0
        self._last_emit_time = 0.0

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

        # Pace output to the configured target framerate (0 = native source pacing)
        target_fps = int(self.config.get("video", "target_fps", 0) or 0)
        if target_fps > 0 and self._last_emit_time > 0:
            wait = (self._last_emit_time + 1.0 / target_fps) - time.perf_counter()
            if wait > 0:
                await asyncio.sleep(wait)

        # Wait up to 100ms for a new fresh frame
        frame_info = None
        for _ in range(20):
            with self.receiver._lock:
                fi = self.receiver.latest_video_frame
            if fi and fi.get("receive_time", 0) > getattr(self, '_last_processed_receive_time', 0):
                frame_info = fi
                self._last_processed_receive_time = frame_info["receive_time"]
                break
            await asyncio.sleep(0.005)

        if not frame_info:
            # If no new frame, check if we can reuse the last frame if it's recent (e.g. within 1 second)
            with self.receiver._lock:
                fi = self.receiver.latest_video_frame
            if fi and (time.perf_counter() - fi.get("receive_time", 0)) < 1.0:
                frame_info = fi

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
                if fourcc == FOURCC_UYVY:
                    row_bytes = width * 2
                    video_frame = av.VideoFrame(width, height, format="uyvy422")
                    if stride == row_bytes:
                        # Zero-copy: feed the capture buffer straight into the plane
                        video_frame.planes[0].update(raw_data)
                    else:
                        img_arr = raw_data.reshape((height, stride // 2, 2))[:, :width, :]
                        video_frame.planes[0].update(img_arr.tobytes())
                elif fourcc in (FOURCC_BGRX, FOURCC_BGRA):
                    # Direct 4-channel BGR0 / BGRA with zero-copy bgr0 packing
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
                    # Fallback default
                    img_arr = raw_data[: height * width * 4].reshape((height, width, 4))
                    video_frame = av.VideoFrame.from_ndarray(img_arr[:, :, :3], format="bgr24")

                target_w = int(self.config.get("video", "target_width", 0) or 0)
                target_h = int(self.config.get("video", "target_height", 0) or 0)
                if target_w > 0 and target_h > 0 and (video_frame.width != target_w or video_frame.height != target_h):
                    video_frame = video_frame.reformat(width=target_w, height=target_h)

                video_frame.pts = pts
                video_frame.time_base = self._time_base
                self._last_emit_time = time.perf_counter()
                return video_frame

            except Exception as e:
                logger.warning(f"Error packing video frame: {e}")

        # If no frame or error, output standby frame
        if self._standby_frame is None:
            self._standby_frame = self._create_standby_frame()

        standby = av.VideoFrame.from_ndarray(self._standby_frame.to_ndarray(format="bgr24"), format="bgr24")
        standby.pts = pts
        standby.time_base = self._time_base
        self._last_emit_time = time.perf_counter()
        return standby


class NDIAudioTrack(AudioStreamTrack):
    """
    Low latency Audio Track that bridges NDI audio into WebRTC (Opus).
    Formats signed 16-bit interleaved PCM with sample-accurate timestamps.
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
        self._audio_pts = 0
        self._samples_per_frame = 960  # 20ms at 48kHz
        self._read_pos = None  # absolute byte cursor in the shared PCM stream

    async def recv(self):
        if self._start_time is None:
            self._start_time = time.perf_counter()
            self._audio_pts = 0

        samples = self._samples_per_frame
        
        # Calculate monotonic PTS based on exact sample count
        pts = self._audio_pts
        self._audio_pts += samples

        frame = av.AudioFrame(format="s16", layout="stereo", samples=samples)
        frame.sample_rate = self._sample_rate
        frame.pts = pts
        frame.time_base = self._time_base

        # 960 samples * 2 channels * 2 bytes/sample = 3840 bytes per 20ms frame
        bytes_needed = samples * 4
        
        # Wait for audio data (up to 100ms) to ensure we don't spin CPU on empty buffers
        # Non-destructive broadcast read: every viewer reads its own window of the ring
        chunk = None
        for _ in range(10):
            with self.receiver._audio_lock:
                start = self.receiver.audio_buffer_start
                end = start + len(self.receiver.audio_pcm_buffer)
                if self._read_pos is None:
                    # Join at the live edge for lowest latency
                    self._read_pos = end
                if self._read_pos < start:
                    # Fell behind the trimmed ring; snap forward to stay live
                    self._read_pos = start
                if end - self._read_pos >= bytes_needed:
                    rel = self._read_pos - start
                    chunk = bytes(self.receiver.audio_pcm_buffer[rel:rel + bytes_needed])
                    self._read_pos += bytes_needed
                    break
            await asyncio.sleep(0.01)

        if chunk and len(chunk) == bytes_needed:
            frame.planes[0].update(chunk)
            return frame

        # Silence fallback if buffer empty; advance cursor so we resume at the live edge
        if self._read_pos is not None:
            self._read_pos += bytes_needed
        silence = b"\x00" * bytes_needed
        frame.planes[0].update(silence)
        return frame


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """Global CORS and Private Network Access middleware."""
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


class WebRTCStreamServer:
    """
    Full WebRTC Server managing NDI Ingestion, Peer Connections, WHEP & WebSocket signaling,
    and HTTP API/Static Web serving.
    """

    def __init__(self, config: ConfigManager, web_dir: str):
        self.config = config
        self.web_dir = web_dir
        apply_encoder_bitrate_settings(config)
        apply_h264_high_profile_support()
        self.receiver = NDIReceiver(
            source_name=self.config.get("ndi", "source_name", ""),
            low_bandwidth=self.config.get("ndi", "low_bandwidth", False),
        )
        self.pcs: Set[RTCPeerConnection] = set()
        self.finder = None
        self.app = web.Application(middlewares=[cors_middleware])
        self.runner = None
        self.site = None
        self.https_site = None
        self._setup_routes()

    def _setup_routes(self):
        # Options preflight handler
        self.app.router.add_route("OPTIONS", "/{tail:.*}", self._handle_options)

        # API Routes
        self.app.router.add_get("/api/status", self._handle_status)
        self.app.router.add_get("/api/sources", self._handle_sources)
        self.app.router.add_get("/api/settings", self._handle_get_settings)
        self.app.router.add_post("/api/settings", self._handle_save_settings)
        self.app.router.add_post("/api/stream/start", self._handle_stream_start)
        self.app.router.add_post("/api/stream/stop", self._handle_stream_stop)

        # Signaling Routes (WHEP on /api/whep and root /)
        self.app.router.add_post("/api/whep", self._handle_whep)
        self.app.router.add_post("/", self._handle_whep)
        self.app.router.add_get("/ws", self._handle_websocket)

        # Static Web App
        self.app.router.add_static("/static", os.path.join(self.web_dir, "static"), name="static")
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/admin", self._handle_admin)

    async def _handle_options(self, request):
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Private-Network": "true",
                "Access-Control-Max-Age": "86400",
            },
        )

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
        port = self.config.get("server", "http_port", 8025)
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
            apply_encoder_bitrate_settings(self.config)
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
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Private-Network": "true",
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
        port = self.config.get("server", "http_port", 8025)
        host = self.config.get("server", "bind_address", "0.0.0.0")

        # Auto-start NDI receiver if enabled
        if self.config.get("app", "auto_start", True):
            source_name = self.config.get("ndi", "source_name", "")
            if source_name:
                self.receiver.connect(source_name)
            self.receiver.start()

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        # HTTP Site (port 8025)
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()

        local_ip = get_local_ip()
        https_port = self.config.get("server", "https_port", port + 1)
        has_https = False
        try:
            cert_path, key_path = ensure_ssl_certificates(ip=local_ip)
            if os.path.exists(cert_path) and os.path.exists(key_path):
                ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_ctx.load_cert_chain(cert_path, key_path)
                self.https_site = web.TCPSite(self.runner, host, https_port, ssl_context=ssl_ctx)
                await self.https_site.start()
                has_https = True
        except Exception as e:
            logger.warning(f"Could not start HTTPS listener on port {https_port}: {e}")

        logger.info(f"==================================================")
        logger.info(f" PECH NDI WebRTC Server is RUNNING")
        logger.info(f" HTTP Local:       http://localhost:{port}")
        logger.info(f" HTTP Network:     http://{local_ip}:{port}")
        if has_https:
            logger.info(f" HTTPS Network:    https://{local_ip}:{https_port}")
            logger.info(f" HTTPS WHEP:       https://{local_ip}:{https_port}/api/whep")
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

        if self.https_site:
            await self.https_site.stop()
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
