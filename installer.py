"""
PECH NDI-to-WebRTC Bridge - Standalone Windows Setup Installer
Installs PECH_NDI_WebRTC.exe, settings.json, and start_server.bat, creates shortcuts, and launches the server.
"""

import os
import sys
import shutil
import subprocess


def get_bundle_dir():
    """Gets bundle directory inside PyInstaller or current script directory."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def create_shortcut(target, shortcut_path, description="PECH NDI-to-WebRTC Bridge"):
    try:
        ps_script = (
            f"$WshShell = New-Object -ComObject WScript.Shell; "
            f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}'); "
            f"$Shortcut.TargetPath = '{target}'; "
            f"$Shortcut.WorkingDirectory = '{os.path.dirname(target)}'; "
            f"$Shortcut.Description = '{description}'; "
            f"$Shortcut.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True)
    except Exception:
        pass


def main():
    print("=" * 64)
    print(" PECH NDI-to-WebRTC Bridge - Windows Setup Installer")
    print(" Version: 1.0.19")
    print(" Target:  Low-Latency WebRTC Tablet Streaming for Churches")
    print("=" * 64)

    is_silent = any(arg.lower() in ("-s", "/s", "--silent", "-y", "--yes") for arg in sys.argv[1:])

    default_install_dir = os.path.join(os.environ.get("SystemDrive", "C:"), "\\PECH_NDI_Bridge")
    if not os.path.exists(default_install_dir):
        try:
            os.makedirs(default_install_dir, exist_ok=True)
        except Exception:
            default_install_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PECH_NDI_Bridge")

    install_dir = default_install_dir
    if not is_silent:
        print(f"\nDefault install folder: {default_install_dir}")
        user_input = input("Enter destination folder (Press ENTER to use default): ").strip()
        if user_input:
            install_dir = os.path.abspath(user_input)

    os.makedirs(install_dir, exist_ok=True)
    print(f"\n[1/4] Installing application files to: {install_dir}")

    bundle_dir = get_bundle_dir()

    # Files to install
    files_to_copy = [
        ("PECH_NDI_WebRTC.exe", True),     # always overwrite binary on update
        ("start_server.bat", True),        # always overwrite launcher
        ("settings.json", False),          # preserve user configuration if already present
    ]

    for fname, overwrite in files_to_copy:
        src = os.path.join(bundle_dir, fname)
        if not os.path.exists(src):
            # Fallback to dist or script dir
            alt_src = os.path.join(os.path.dirname(bundle_dir), "dist", fname)
            if os.path.exists(alt_src):
                src = alt_src
            else:
                src = os.path.join(bundle_dir, "dist", fname)

        dst = os.path.join(install_dir, fname)
        if os.path.exists(src):
            if os.path.exists(dst) and not overwrite:
                print(f"  --> Preserving existing user settings: {dst}")
            else:
                shutil.copy2(src, dst)
                print(f"  --> Installed: {fname}")
        else:
            print(f"  --> [Warning] Source file not found: {fname}")

    print("\n[2/4] Creating Windows Shortcuts...")
    target_bat = os.path.join(install_dir, "start_server.bat")

    # Desktop shortcut
    try:
        desktop_dir = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
        if os.path.exists(desktop_dir):
            shortcut_desktop = os.path.join(desktop_dir, "PECH NDI Bridge.lnk")
            create_shortcut(target_bat, shortcut_desktop)
            print(f"  --> Desktop shortcut created: {shortcut_desktop}")
    except Exception as e:
        print(f"  --> Could not create Desktop shortcut: {e}")

    # Start Menu shortcut
    try:
        programs_dir = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
        if os.path.exists(programs_dir):
            app_menu_dir = os.path.join(programs_dir, "PECH NDI Bridge")
            os.makedirs(app_menu_dir, exist_ok=True)
            shortcut_menu = os.path.join(app_menu_dir, "PECH NDI Bridge.lnk")
            create_shortcut(target_bat, shortcut_menu)
            print(f"  --> Start Menu shortcut created: {shortcut_menu}")
    except Exception as e:
        print(f"  --> Could not create Start Menu shortcut: {e}")

    print("\n[3/4] Validating Installation...")
    if os.path.exists(os.path.join(install_dir, "PECH_NDI_WebRTC.exe")):
        print("  --> Verification successful: Executable present and ready.")
    else:
        print("  --> Verification warning: Executable not found in install directory.")

    print("\n" + "=" * 64)
    print(" INSTALLATION COMPLETE!")
    print(f" Location: {install_dir}")
    print(" Launch:   Double-click 'PECH NDI Bridge' on your Desktop or run:")
    print(f"           {target_bat}")
    print("=" * 64)

    start_now = True
    if not is_silent:
        ans = input("\nStart PECH NDI-to-WebRTC Bridge server now? [Y/n]: ").strip().lower()
        start_now = (ans == "" or ans.startswith("y"))

    if start_now:
        print("\nStarting server...")
        subprocess.Popen(["cmd.exe", "/c", target_bat], cwd=install_dir)


if __name__ == "__main__":
    main()
