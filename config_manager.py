"""
Configuration Manager for PECH NDI WebRTC Streaming Bridge
Handles loading, saving, and defaulting settings.json.
"""

import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger("config_manager")

DEFAULT_SETTINGS = {
    "server": {
        "http_port": 8080,
        "bind_address": "0.0.0.0",
    },
    "ndi": {
        "source_name": "",
        "color_format": "BGRX",
        "low_bandwidth": False,
    },
    "video": {
        "target_width": 0,    # 0 = keep source resolution
        "target_height": 0,   # 0 = keep source resolution
        "target_fps": 0,      # 0 = keep source fps
        "bitrate_kbps": 6000,
        "codec": "H264",
    },
    "audio": {
        "channels": 2,
        "sample_rate": 48000,
        "bitrate_kbps": 128,
        "codec": "opus",
    },
    "app": {
        "auto_start": True,
        "title": "PECH NDI-to-WebRTC Bridge",
    }
}


class ConfigManager:
    def __init__(self, config_path="settings.json"):
        self.config_path = config_path
        self.settings: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        """Loads configuration from JSON file or creates it with defaults."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_data = json.load(f)
                    self.settings = self._merge_defaults(user_data, DEFAULT_SETTINGS)
                    logger.info(f"Loaded configuration from {self.config_path}")
                    return self.settings
            except Exception as e:
                logger.error(f"Failed to read {self.config_path}: {e}. Using defaults.")
                self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        else:
            self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
            self.save()
        return self.settings

    def save(self) -> bool:
        """Saves current configuration to JSON file."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
            logger.info(f"Saved configuration to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save {self.config_path}: {e}")
            return False

    def update(self, updates: Dict[str, Any]) -> bool:
        """Updates settings in memory and writes to file."""
        for section, values in updates.items():
            if isinstance(values, dict) and section in self.settings:
                self.settings[section].update(values)
            else:
                self.settings[section] = values
        return self.save()

    def get(self, section: str, key: str = None, default=None):
        if key is None:
            return self.settings.get(section, default)
        return self.settings.get(section, {}).get(key, default)

    def _merge_defaults(self, target: dict, defaults: dict) -> dict:
        result = json.loads(json.dumps(defaults))
        for k, v in target.items():
            if isinstance(v, dict) and k in result and isinstance(result[k], dict):
                result[k] = self._merge_defaults(v, result[k])
            else:
                result[k] = v
        return result
