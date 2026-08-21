"""
Build script for packaging PECH NDI-to-WebRTC Bridge into a single Windows .exe
Uses PyInstaller with all required web assets and NDI dependencies.
"""

import os
import subprocess
import sys

def build():
    print("Building PECH NDI-to-WebRTC Bridge executable...")

    ndi_dll = r"C:\Program Files\NDI\NDI 6 Runtime\v6\Processing.NDI.Lib.x64.dll"
    if not os.path.exists(ndi_dll):
        print(f"Warning: NDI Runtime DLL not found at {ndi_dll}. Ensure NDI 6 is installed.")

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--name", "PECH_NDI_WebRTC",
        "--add-data", f"web{os.pathsep}web",
        "--add-data", f"settings.json{os.pathsep}.",
        "--hidden-import", "aiortc",
        "--hidden-import", "aiohttp",
        "--hidden-import", "av",
        "--hidden-import", "numpy",
        "--hidden-import", "webview",
        "main.py"
    ]

    print("Running command:", " ".join(cmd))
    subprocess.check_call(cmd)
    print("\n[SUCCESS] Build complete! Executable located in: dist/PECH_NDI_WebRTC/PECH_NDI_WebRTC.exe")

if __name__ == "__main__":
    build()
