"""
NDI Core - Wrapper for NDI 6 SDK on Windows
Handles discovery and low-latency video/audio frame capture.
"""

import os
import sys
import ctypes
from ctypes import (
    Structure, c_char_p, c_int, c_int64, c_uint32, c_float,
    POINTER, byref, c_void_p, c_bool, cast
)
import numpy as np
import threading
import time
import logging

logger = logging.getLogger("ndi_core")

# NDI Constants & Enums
NDILIB_RECV_COLOR_FORMAT_BGRX_BGRA = 0
NDILIB_RECV_COLOR_FORMAT_UYVY_BGRA = 1
NDILIB_RECV_COLOR_FORMAT_RGBX_RGBA = 2
NDILIB_RECV_COLOR_FORMAT_UYVY_RGBA = 3
NDILIB_RECV_COLOR_FORMAT_FASTEST = 100
NDILIB_RECV_COLOR_FORMAT_BEST = 101

NDILIB_RECV_BANDWIDTH_METADATA_ONLY = -10
NDILIB_RECV_BANDWIDTH_AUDIO_ONLY = 10
NDILIB_RECV_BANDWIDTH_LOWEST = 0
NDILIB_RECV_BANDWIDTH_HIGHEST = 100

NDILIB_FRAME_TYPE_NONE = 0
NDILIB_FRAME_TYPE_VIDEO = 1
NDILIB_FRAME_TYPE_AUDIO = 2
NDILIB_FRAME_TYPE_METADATA = 3
NDILIB_FRAME_TYPE_ERROR = 4
NDILIB_FRAME_TYPE_STATUS_CHANGE = 100

# FourCC Codes
FOURCC_UYVY = 0x59565955
FOURCC_BGRA = 0x41524742
FOURCC_BGRX = 0x58524742
FOURCC_RGBA = 0x41424752
FOURCC_RGBX = 0x58424752


class NDIlib_source_t(Structure):
    _fields_ = [
        ("p_ndi_name", c_char_p),
        ("p_url_address", c_char_p),
    ]


class NDIlib_find_create_t(Structure):
    _fields_ = [
        ("show_local_sources", c_bool),
        ("p_groups", c_char_p),
        ("p_extra_ips", c_char_p),
    ]


class NDIlib_recv_create_v3_t(Structure):
    _fields_ = [
        ("source_to_connect_to", NDIlib_source_t),
        ("color_format", c_int),
        ("bandwidth", c_int),
        ("allow_video_fields", c_bool),
        ("p_ndi_recv_name", c_char_p),
    ]


class NDIlib_video_frame_v2_t(Structure):
    _fields_ = [
        ("xres", c_int),
        ("yres", c_int),
        ("FourCC", c_uint32),
        ("frame_rate_N", c_int),
        ("frame_rate_D", c_int),
        ("picture_aspect_ratio", c_float),
        ("frame_format_type", c_int),
        ("timecode", c_int64),
        ("p_data", POINTER(ctypes.c_uint8)),
        ("line_stride_in_bytes", c_int),
        ("p_metadata", c_char_p),
        ("timestamp", c_int64),
    ]


class NDIlib_audio_frame_v2_t(Structure):
    _fields_ = [
        ("sample_rate", c_int),
        ("no_channels", c_int),
        ("no_samples", c_int),
        ("timecode", c_int64),
        ("p_data", POINTER(c_float)),
        ("channel_stride_in_bytes", c_int),
        ("p_metadata", c_char_p),
        ("timestamp", c_int64),
    ]


class NDISDK:
    _instance = None
    _dll = None
    _initialized = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._load_dll()

    def _load_dll(self):
        possible_paths = [
            r"C:\Program Files\NDI\NDI 6 Runtime\v6\Processing.NDI.Lib.x64.dll",
            r"C:\Program Files\NDI\NDI 6 SDK\Lib\x64\Processing.NDI.Lib.x64.dll",
            r"C:\Program Files\NDI\NDI 5 Runtime\v5\Processing.NDI.Lib.x64.dll",
            "Processing.NDI.Lib.x64.dll",
        ]

        dll_path = None
        for p in possible_paths:
            if os.path.exists(p):
                dll_path = p
                break

        if not dll_path:
            # Check environment variables
            env_v6 = os.environ.get("NDI_RUNTIME_DIR_V6")
            if env_v6 and os.path.exists(os.path.join(env_v6, "Processing.NDI.Lib.x64.dll")):
                dll_path = os.path.join(env_v6, "Processing.NDI.Lib.x64.dll")

        if not dll_path:
            raise FileNotFoundError(
                "NDI Runtime DLL (Processing.NDI.Lib.x64.dll) was not found. "
                "Please ensure NDI 6 Runtime or SDK is installed."
            )

        logger.info(f"Loading NDI DLL from: {dll_path}")
        self._dll = ctypes.CDLL(dll_path)
        self._setup_signatures()

        if not self._dll.NDIlib_initialize():
            raise RuntimeError("NDIlib_initialize failed!")
        self._initialized = True
        logger.info("NDI SDK initialized successfully.")

    def _setup_signatures(self):
        dll = self._dll

        # Initialize / Destroy
        dll.NDIlib_initialize.restype = c_bool
        dll.NDIlib_initialize.argtypes = []
        dll.NDIlib_destroy.restype = None
        dll.NDIlib_destroy.argtypes = []

        # Find API
        dll.NDIlib_find_create_v2.restype = c_void_p
        dll.NDIlib_find_create_v2.argtypes = [POINTER(NDIlib_find_create_t)]
        dll.NDIlib_find_destroy.restype = None
        dll.NDIlib_find_destroy.argtypes = [c_void_p]
        dll.NDIlib_find_wait_for_sources.restype = c_bool
        dll.NDIlib_find_wait_for_sources.argtypes = [c_void_p, c_uint32]
        dll.NDIlib_find_get_current_sources.restype = POINTER(NDIlib_source_t)
        dll.NDIlib_find_get_current_sources.argtypes = [c_void_p, POINTER(c_uint32)]

        # Recv API
        dll.NDIlib_recv_create_v3.restype = c_void_p
        dll.NDIlib_recv_create_v3.argtypes = [POINTER(NDIlib_recv_create_v3_t)]
        dll.NDIlib_recv_destroy.restype = None
        dll.NDIlib_recv_destroy.argtypes = [c_void_p]
        dll.NDIlib_recv_connect.restype = None
        dll.NDIlib_recv_connect.argtypes = [c_void_p, POINTER(NDIlib_source_t)]
        dll.NDIlib_recv_capture_v2.restype = c_int
        dll.NDIlib_recv_capture_v2.argtypes = [
            c_void_p,
            POINTER(NDIlib_video_frame_v2_t),
            POINTER(NDIlib_audio_frame_v2_t),
            c_void_p,  # metadata
            c_uint32,  # timeout_ms
        ]
        dll.NDIlib_recv_free_video_v2.restype = None
        dll.NDIlib_recv_free_video_v2.argtypes = [c_void_p, POINTER(NDIlib_video_frame_v2_t)]
        dll.NDIlib_recv_free_audio_v2.restype = None
        dll.NDIlib_recv_free_audio_v2.argtypes = [c_void_p, POINTER(NDIlib_audio_frame_v2_t)]

    @property
    def dll(self):
        return self._dll

    def cleanup(self):
        if self._initialized and self._dll:
            try:
                self._dll.NDIlib_destroy()
            except Exception:
                pass
            self._initialized = False


class NDIFinder:
    """Discovers NDI sources on the local network."""

    def __init__(self, show_local_sources=True):
        self.sdk = NDISDK.get_instance()
        create_settings = NDIlib_find_create_t(show_local_sources, None, None)
        self._p_find = self.sdk.dll.NDIlib_find_create_v2(byref(create_settings))
        if not self._p_find:
            raise RuntimeError("Failed to create NDI Finder instance.")

    def get_sources(self, timeout_ms=500):
        """Returns a list of dicts: [{'name': '...', 'url': '...'}]"""
        self.sdk.dll.NDIlib_find_wait_for_sources(self._p_find, timeout_ms)
        num_sources = c_uint32(0)
        p_sources = self.sdk.dll.NDIlib_find_get_current_sources(self._p_find, byref(num_sources))

        sources = []
        for i in range(num_sources.value):
            src = p_sources[i]
            name = src.p_ndi_name.decode("utf-8", errors="ignore") if src.p_ndi_name else ""
            url = src.p_url_address.decode("utf-8", errors="ignore") if src.p_url_address else ""
            if name:
                sources.append({"name": name, "url": url})
        return sources

    def close(self):
        if self._p_find:
            self.sdk.dll.NDIlib_find_destroy(self._p_find)
            self._p_find = None

    def __del__(self):
        self.close()


class NDIReceiver:
    """Receives and extracts uncompressed video/audio frames from a selected NDI source."""

    def __init__(self, source_name=None, color_format=NDILIB_RECV_COLOR_FORMAT_BGRX_BGRA, low_bandwidth=False):
        self.sdk = NDISDK.get_instance()
        self.source_name = source_name
        self.color_format = color_format
        self.bandwidth = NDILIB_RECV_BANDWIDTH_LOWEST if low_bandwidth else NDILIB_RECV_BANDWIDTH_HIGHEST

        source = NDIlib_source_t()
        if source_name:
            source.p_ndi_name = source_name.encode("utf-8")
        else:
            source.p_ndi_name = None
        source.p_url_address = None

        recv_create = NDIlib_recv_create_v3_t(
            source,
            self.color_format,
            self.bandwidth,
            False,
            b"PECH_NDI_WebRTC_Bridge",
        )

        self._p_recv = self.sdk.dll.NDIlib_recv_create_v3(byref(recv_create))
        if not self._p_recv:
            raise RuntimeError("Failed to create NDI receiver instance.")

        self._running = False
        self._thread = None
        self.latest_video_frame = None
        self.latest_audio_frame = None
        self.on_video_frame = None
        self.on_audio_frame = None
        self._lock = threading.Lock()
        self.stats = {
            "fps": 0.0,
            "width": 0,
            "height": 0,
            "frames_received": 0,
            "audio_samples_received": 0,
            "connected": False,
            "last_frame_time": 0.0,
        }

    def connect(self, source_name, url=None):
        """Connect or switch to an NDI source."""
        self.source_name = source_name
        src = NDIlib_source_t(
            source_name.encode("utf-8") if source_name else None,
            url.encode("utf-8") if url else None,
        )
        self.sdk.dll.NDIlib_recv_connect(self._p_recv, byref(src))
        logger.info(f"NDI receiver connected to source: {source_name}")

    def start(self):
        """Start the capture background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, name="NDI_Capture_Thread", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop capture."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _capture_loop(self):
        v_frame = NDIlib_video_frame_v2_t()
        a_frame = NDIlib_audio_frame_v2_t()
        frame_count = 0
        last_stat_calc = time.perf_counter()

        while self._running:
            frame_type = self.sdk.dll.NDIlib_recv_capture_v2(
                self._p_recv,
                byref(v_frame),
                byref(a_frame),
                None,
                50,  # 50ms timeout
            )

            now = time.perf_counter()

            if frame_type == NDILIB_FRAME_TYPE_VIDEO:
                # Video received
                width = v_frame.xres
                height = v_frame.yres
                stride = v_frame.line_stride_in_bytes
                fourcc = v_frame.FourCC

                if v_frame.p_data and width > 0 and height > 0:
                    # Direct buffer copy to numpy without intermediate serialization
                    data_size = stride * height
                    buf = (ctypes.c_uint8 * data_size).from_address(ctypes.addressof(v_frame.p_data.contents))
                    raw_arr = np.frombuffer(buf, dtype=np.uint8)

                    video_info = {
                        "width": width,
                        "height": height,
                        "stride": stride,
                        "fourcc": fourcc,
                        "fps_num": v_frame.frame_rate_N,
                        "fps_den": v_frame.frame_rate_D,
                        "timestamp": v_frame.timestamp,
                        "data": raw_arr.copy(),
                        "receive_time": now,
                    }

                    with self._lock:
                        self.latest_video_frame = video_info
                        self.stats["width"] = width
                        self.stats["height"] = height
                        self.stats["frames_received"] += 1
                        self.stats["connected"] = True
                        self.stats["last_frame_time"] = now

                    if self.on_video_frame:
                        try:
                            self.on_video_frame(video_info)
                        except Exception as e:
                            logger.error(f"Error in on_video_frame callback: {e}")

                    frame_count += 1

                self.sdk.dll.NDIlib_recv_free_video_v2(self._p_recv, byref(v_frame))

            elif frame_type == NDILIB_FRAME_TYPE_AUDIO:
                # Audio received
                sample_rate = a_frame.sample_rate
                channels = a_frame.no_channels
                samples = a_frame.no_samples
                stride = a_frame.channel_stride_in_bytes

                if a_frame.p_data and samples > 0 and channels > 0:
                    # Planar float32 audio
                    total_floats = (stride // 4) * channels if stride else samples * channels
                    buf = (c_float * total_floats).from_address(ctypes.addressof(a_frame.p_data.contents))
                    raw_audio = np.frombuffer(buf, dtype=np.float32)

                    # Reshape planar audio if needed (channels x samples)
                    if stride and stride != samples * 4:
                        stride_samples = stride // 4
                        planar = np.zeros((channels, samples), dtype=np.float32)
                        for ch in range(channels):
                            planar[ch] = raw_audio[ch * stride_samples : ch * stride_samples + samples]
                    else:
                        planar = raw_audio[: channels * samples].reshape((channels, samples))

                    audio_info = {
                        "sample_rate": sample_rate,
                        "channels": channels,
                        "samples": samples,
                        "timestamp": a_frame.timestamp,
                        "data": planar.copy(),
                        "receive_time": now,
                    }

                    with self._lock:
                        self.latest_audio_frame = audio_info
                        self.stats["audio_samples_received"] += samples
                        self.stats["connected"] = True

                    if self.on_audio_frame:
                        try:
                            self.on_audio_frame(audio_info)
                        except Exception as e:
                            logger.error(f"Error in on_audio_frame callback: {e}")

                self.sdk.dll.NDIlib_recv_free_audio_v2(self._p_recv, byref(a_frame))

            # FPS computation every 1 second
            if now - last_stat_calc >= 1.0:
                elapsed = now - last_stat_calc
                with self._lock:
                    self.stats["fps"] = round(frame_count / elapsed, 1)
                    if now - self.stats["last_frame_time"] > 2.5:
                        self.stats["connected"] = False
                frame_count = 0
                last_stat_calc = now

    def close(self):
        self.stop()
        if self._p_recv:
            self.sdk.dll.NDIlib_recv_destroy(self._p_recv)
            self._p_recv = None

    def __del__(self):
        self.close()
