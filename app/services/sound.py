from __future__ import annotations

import subprocess
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

class SoundService:
    def __init__(self):
        self._control = self._detect_control()

    def _detect_control(self) -> str:
        """Detect the best mixer control to use."""
        try:
            output = subprocess.check_output(["amixer", "scontrols"], text=True)
            controls = re.findall(r"Simple mixer control '([^']+)'", output)
            # Preference order
            for pref in ["Master", "Speaker", "Headphone", "PCM"]:
                if pref in controls:
                    logger.info(f"Using sound control: {pref}")
                    return pref
            if controls:
                logger.info(f"Using first available sound control: {controls[0]}")
                return controls[0]
        except Exception as e:
            logger.error(f"Sound detection error: {e}")
        return "Master"

    def get_volume(self) -> int:
        """Get current volume (0-100)."""
        try:
            output = subprocess.check_output(["amixer", "sget", self._control], text=True)
            match = re.search(r"\[(\d+)%\]", output)
            if match:
                return int(match.group(1))
        except Exception as e:
            logger.error(f"Sound get_volume error: {e}")
        return 0

    def set_volume(self, percent: int) -> bool:
        """Set volume (0-100)."""
        try:
            percent = max(0, min(100, percent))
            subprocess.run(["amixer", "sset", self._control, f"{percent}%"], check=True)
            return True
        except Exception as e:
            logger.error(f"Sound set_volume error: {e}")
            return False

    def is_muted(self) -> bool:
        """Check if muted."""
        try:
            output = subprocess.check_output(["amixer", "sget", self._control], text=True)
            return "[off]" in output
        except Exception as e:
            logger.error(f"Sound is_muted error: {e}")
        return False

    def set_mute(self, mute: bool) -> bool:
        """Set mute state."""
        try:
            action = "mute" if mute else "unmute"
            subprocess.run(["amixer", "sset", self._control, action], check=True)
            return True
        except Exception as e:
            logger.error(f"Sound set_mute error: {e}")
            return False

    def toggle_mute(self) -> bool:
        """Toggle mute state."""
        try:
            subprocess.run(["amixer", "sset", self._control, "toggle"], check=True)
            return True
        except Exception as e:
            logger.error(f"Sound toggle_mute error: {e}")
            return False

    def get_status(self) -> dict[str, Any]:
        return {
            "volume": self.get_volume(),
            "muted": self.is_muted(),
            "control": self._control
        }

sound_service = SoundService()
