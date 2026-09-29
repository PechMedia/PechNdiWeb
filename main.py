"""
PECH NDI-to-WebRTC Streaming Bridge
Main Server Entry Point (FastAPI & aiortc WHEP Media Bridge)
"""

import argparse
import asyncio
import logging
import os
import signal
import sys

from config_manager import ConfigManager
from webrtc_server import WebRTCStreamServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pechndiweb")


def parse_args():
    parser = argparse.ArgumentParser(
        description="PECH NDI-to-WebRTC Bridge - Ultra-Low Latency Tablet Streaming",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override HTTP / WebRTC / REST API port (default: from settings.json or 8123)",
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
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run in headless server mode (maintained for backward compatibility)",
    )
    return parser.parse_args()


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
        updates["port"] = args.port
        updates.setdefault("server", {})["http_port"] = args.port
    if args.bind:
        updates.setdefault("server", {})["bind_address"] = args.bind
    if args.source:
        updates.setdefault("ndi", {})["source_name"] = args.source

    if updates:
        config.update(updates)

    port = int(config.settings.get("port") or config.get("server", "http_port", 8123))
    server = WebRTCStreamServer(config, web_dir)

    print("=" * 64)
    print(" PECH NDI-to-WebRTC Streaming Bridge for Tablets")
    print(f" Port:   {port}")
    print(f" Config: {args.config}")
    print(f" Source: {config.get('ndi', 'source_name') or '(None selected)'}")
    print("=" * 64)

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
            pass

    try:
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        logger.info("Ctrl+C pressed. Exiting...")
    finally:
        loop.run_until_complete(server.stop())
        loop.close()
        logger.info("Server process closed successfully.")


if __name__ == "__main__":
    main()
