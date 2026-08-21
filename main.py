"""
PECH NDI-to-WebRTC Near-Zero Latency Streaming Bridge
Main Entry Point (Supports both Headless & UI Modes)
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
import time

from config_manager import ConfigManager
from webrtc_server import WebRTCStreamServer
from ui_app import launch_ui

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pechndiweb")


def parse_args():
    parser = argparse.ArgumentParser(
        description="PECH NDI-to-WebRTC Bridge - Ultra Low Latency LAN Streaming",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no GUI window, purely background server)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override HTTP / WebRTC port (default from settings.json or 8080)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Override NDI stream source name to decode",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="settings.json",
        help="Path to JSON configuration file",
    )
    parser.add_argument(
        "--bind",
        type=str,
        default=None,
        help="IP address to bind the web server to (e.g. 0.0.0.0)",
    )
    return parser.parse_args()


class AsyncServerThread(threading.Thread):
    """Runs the asyncio web server loop in a dedicated background thread for UI mode."""

    def __init__(self, server: WebRTCStreamServer):
        super().__init__(name="WebRTC_Server_Thread", daemon=True)
        self.server = server
        self.loop = None

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.server.start())
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"Server loop error: {e}")
        finally:
            self.loop.run_until_complete(self.server.stop())
            self.loop.close()

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)


def main():
    args = parse_args()

    # Determine base directories (supporting PyInstaller --onefile mode)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        bundle_dir = getattr(sys, "_MEIPASS", exe_dir)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
        bundle_dir = exe_dir

    web_dir = os.path.join(bundle_dir, "web")
    config_file_path = args.config if os.path.isabs(args.config) else os.path.join(exe_dir, args.config)

    # Load / create configuration
    config = ConfigManager(config_path=config_file_path)

    # Apply CLI overrides
    updates = {}
    if args.port:
        updates.setdefault("server", {})["http_port"] = args.port
    if args.bind:
        updates.setdefault("server", {})["bind_address"] = args.bind
    if args.source:
        updates.setdefault("ndi", {})["source_name"] = args.source

    if updates:
        config.update(updates)

    port = config.get("server", "http_port", 8080)
    server = WebRTCStreamServer(config, web_dir)

    print("=" * 60)
    print(" PECH NDI-to-WebRTC Near-Zero Latency Bridge")
    print(f" Mode: {'HEADLESS (CLI)' if args.headless else 'DESKTOP UI'}")
    print(f" Config: {args.config}")
    print("=" * 60)

    if args.headless:
        # Run directly on main thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def handle_signal():
            logger.info("Termination signal received. Shutting down...")
            loop.create_task(server.stop())
            loop.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except (NotImplementedError, AttributeError):
                # Windows signal compatibility
                pass

        try:
            loop.run_until_complete(server.start())
            logger.info("Headless server active. Press Ctrl+C to terminate.")
            loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Ctrl+C pressed. Exiting...")
        finally:
            loop.run_until_complete(server.stop())
            loop.close()
            logger.info("Shutdown complete.")
    else:
        # UI Mode: start server in background thread, open WebView2 on main thread
        server_thread = AsyncServerThread(server)
        server_thread.start()

        # Brief wait for server startup
        time.sleep(0.5)

        try:
            launch_ui(port=port, title=config.get("app", "title", "PECH NDI-to-WebRTC Bridge"))
        except KeyboardInterrupt:
            pass
        finally:
            logger.info("Closing desktop window, stopping background server...")
            server_thread.stop()
            server_thread.join(timeout=2.0)
            logger.info("Application closed successfully.")


if __name__ == "__main__":
    main()
