"""
UI Application Wrapper for Windows
Opens a native Windows 11 window with embedded Edge WebView2 pointing to the local dashboard.
"""

import webview
import logging
import sys

logger = logging.getLogger("ui_app")


def launch_ui(port=8080, title="PECH NDI-to-WebRTC Bridge"):
    """Launches the desktop GUI window using Windows WebView2."""
    url = f"http://localhost:{port}/admin"
    logger.info(f"Opening desktop UI window at {url}...")

    window = webview.create_window(
        title=title,
        url=url,
        width=1280,
        height=820,
        min_size=(900, 600),
        text_select=True,
        background_color="#0a0e17",
    )

    webview.start(debug=False)
