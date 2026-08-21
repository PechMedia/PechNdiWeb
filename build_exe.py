"""
Build script for packaging PECH NDI-to-WebRTC Bridge into a single standalone Windows .exe
Uses PyInstaller --onefile with all required web assets and WebRTC/NDI dependencies.
"""

import os
import subprocess
import sys


def build():
    print("=" * 60)
    print(" Packaging PECH NDI-to-WebRTC Bridge into a Single .EXE")
    print("=" * 60)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.join(base_dir, "web")

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "PECH_NDI_WebRTC",
        "--add-data", f"{web_dir}{os.pathsep}web",
        "--hidden-import", "aiortc",
        "--hidden-import", "aiortc.mediastreams",
        "--hidden-import", "aiohttp",
        "--hidden-import", "av",
        "--hidden-import", "numpy",
        "--hidden-import", "websockets",
        "--hidden-import", "webview",
        "--hidden-import", "clr_loader",
        "main.py",
    ]

    print("Running PyInstaller:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=base_dir)
    exe_path = os.path.join(base_dir, "dist", "PECH_NDI_WebRTC.exe")
    print("\n" + "=" * 60)
    print(f"[SUCCESS] Standalone single executable created:")
    print(f"  --> {exe_path}")
    print("=" * 60)


if __name__ == "__main__":
    build()
