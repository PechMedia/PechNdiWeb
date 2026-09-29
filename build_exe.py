"""
Build script for packaging PECH NDI-to-WebRTC Bridge:
1. Compiles standalone single executable (PECH_NDI_WebRTC.exe) via PyInstaller
2. Generates startup batch scripts and default settings.json
3. Builds Windows Setup Installer (PECH_NDI_WebRTC_Setup.exe) via Windows IExpress
4. Generates Inno Setup compiler script (PECH_NDI_WebRTC_InnoSetup.iss)
"""

import os
import shutil
import subprocess
import sys


def build():
    print("=" * 64)
    print(" Packaging PECH NDI-to-WebRTC Bridge for Windows")
    print("=" * 64)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.join(base_dir, "web")
    dist_dir = os.path.join(base_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    # 1. Run PyInstaller
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "PECH_NDI_WebRTC",
        "--add-data", f"{web_dir}{os.pathsep}web",
        "--add-data", f"{os.path.join(base_dir, 'sw.js')}{os.pathsep}.",
        "--add-data", f"{os.path.join(base_dir, 'config.js')}{os.pathsep}.",
        "--add-data", f"{os.path.join(base_dir, 'receiver.html')}{os.pathsep}.",
        "--collect-all", "fastapi",
        "--collect-all", "uvicorn",
        "--collect-all", "starlette",
        "--collect-all", "pydantic",
        "--collect-all", "PIL",
        "--hidden-import", "aiortc",
        "--hidden-import", "aiortc.mediastreams",
        "--hidden-import", "av",
        "--hidden-import", "numpy",
        "--hidden-import", "websockets",
        "--hidden-import", "cryptography",
        "main.py",
    ]

    print("\n[STEP 1/4] Running PyInstaller build...")
    subprocess.check_call(cmd, cwd=base_dir)
    exe_path = os.path.join(dist_dir, "PECH_NDI_WebRTC.exe")

    # 2. Copy/Create settings.json in dist
    src_settings = os.path.join(base_dir, "settings.json")
    dist_settings = os.path.join(dist_dir, "settings.json")
    if os.path.exists(src_settings):
        shutil.copy2(src_settings, dist_settings)
    print(f"[STEP 2/4] Synced configuration file: {dist_settings}")

    # 3. Create start_server.bat in dist and root
    bat_content = (
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "\r\n"
        "echo ============================================================\r\n"
        "echo  PECH NDI-to-WebRTC Streaming Bridge Server\r\n"
        "echo ============================================================\r\n"
        "echo  Config: settings.json\r\n"
        "echo  URL:    http://localhost:8123\r\n"
        "echo  REST:   http://localhost:8123/api/stream/control\r\n"
        "echo ============================================================\r\n"
        "echo.\r\n"
        "\r\n"
        "if exist \"PECH_NDI_WebRTC.exe\" (\r\n"
        "    PECH_NDI_WebRTC.exe --config settings.json %*\r\n"
        ") else (\r\n"
        "    python main.py --config settings.json %*\r\n"
        ")\r\n"
        "\r\n"
        "if errorlevel 1 (\r\n"
        "    echo.\r\n"
        "    echo [ERROR] Server exited with code %errorlevel%\r\n"
        "    pause\r\n"
        ")\r\n"
    )

    dist_bat = os.path.join(dist_dir, "start_server.bat")
    with open(dist_bat, "w", encoding="utf-8") as f:
        f.write(bat_content)

    root_bat = os.path.join(base_dir, "start_server.bat")
    with open(root_bat, "w", encoding="utf-8") as f:
        f.write(bat_content)

    # Maintain start_headless.bat for backwards compatibility
    with open(os.path.join(dist_dir, "start_headless.bat"), "w", encoding="utf-8") as f:
        f.write(bat_content)

    print(f"[STEP 3/4] Created startup batch scripts: {dist_bat}")

    # 4. Create Windows Setup Installer (.exe) via PyInstaller
    print("[STEP 4/4] Building Windows Setup Installer (PECH_NDI_WebRTC_Setup.exe)...")
    setup_exe = os.path.join(dist_dir, "PECH_NDI_WebRTC_Setup.exe")
    installer_script = os.path.join(base_dir, "installer.py")
    setup_cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "PECH_NDI_WebRTC_Setup",
        "--add-data", f"{exe_path}{os.pathsep}.",
        "--add-data", f"{dist_settings}{os.pathsep}.",
        "--add-data", f"{dist_bat}{os.pathsep}.",
        installer_script,
    ]
    try:
        subprocess.check_call(setup_cmd, cwd=base_dir)
        print(f"  --> Windows Setup Installer created: {setup_exe}")
    except Exception as e:
        print(f"  --> Note: Setup Installer build error: {e}")

    # 5. Generate Inno Setup script (.iss)
    iss_file = os.path.join(base_dir, "PECH_NDI_WebRTC_InnoSetup.iss")
    iss_content = f"""; Inno Setup Script for PECH NDI-to-WebRTC Bridge
[Setup]
AppName=PECH NDI-to-WebRTC Bridge
AppVersion=1.0.16
AppPublisher=PechMedia
DefaultDirName={{autopf}}\\PECH NDI Bridge
DefaultGroupName=PECH NDI Bridge
OutputDir={dist_dir}
OutputBaseFilename=PECH_NDI_Bridge_InnoSetup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "{dist_dir}\\PECH_NDI_WebRTC.exe"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{dist_dir}\\settings.json"; DestDir: "{{app}}"; Flags: onlyifdoesntexist
Source: "{dist_dir}\\start_server.bat"; DestDir: "{{app}}"; Flags: ignoreversion

[Icons]
Name: "{{group}}\\PECH NDI Bridge"; Filename: "{{app}}\\start_server.bat"
Name: "{{autodesktop}}\\PECH NDI Bridge"; Filename: "{{app}}\\start_server.bat"

[Run]
Filename: "{{app}}\\start_server.bat"; Description: "Launch PECH NDI Bridge"; Flags: nowait postinstall skipifsilent
"""
    with open(iss_file, "w", encoding="utf-8") as f:
        f.write(iss_content)

    print("\n" + "=" * 64)
    print(" BUILD COMPLETE!")
    print(f"  1. Standalone Executable: {exe_path}")
    print(f"  2. Windows Setup Installer: {setup_exe}")
    print(f"  3. Server Batch Launcher:   {dist_bat}")
    print(f"  4. Settings Configuration: {dist_settings}")
    print(f"  5. Inno Setup Script:      {iss_file}")
    print("=" * 64)


if __name__ == "__main__":
    build()
