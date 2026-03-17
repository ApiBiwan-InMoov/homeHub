import socket
import threading
import logging
import time
from app.storage.logs import append_log
from app.config import settings

logger = logging.getLogger(__name__)

class ShellyDebugService:
    def __init__(self):
        self._socket = None
        self._thread = None
        self._running = False

    def start(self):
        if self._running:
            return
        
        self._running = True
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Allow multiple sockets to bind to the same UDP port if supported, 
        # but here we mainly want to catch the packets.
        try:
            # We use UDP port from settings
            port = getattr(settings, "shelly_debug_port", 1883)
            # Bind to all interfaces
            self._socket.bind(("0.0.0.0", port))
            logger.info(f"Shelly UDP Debug listener started on port {port}")
            self._thread = threading.Thread(target=self._listen, daemon=True)
            self._thread.start()
        except Exception as e:
            logger.error(f"Failed to start Shelly UDP Debug listener on port {getattr(settings, 'shelly_debug_port', 1883)}: {e}")
            self._running = False

    def _listen(self):
        while self._running:
            try:
                # Shelly logs are usually short
                data, addr = self._socket.recvfrom(4096)
                message = data.decode('utf-8', errors='ignore').strip()
                if message:
                    # Append to our centralized logs
                    append_log({
                        "type": "shelly_debug",
                        "src": addr[0],
                        "msg": message
                    })
            except Exception as e:
                if self._running:
                    # Avoid spamming logs if socket is closed
                    logger.error(f"Error in Shelly UDP Debug listener: {e}")
                    time.sleep(1)

    def stop(self):
        self._running = False
        if self._socket:
            # Shutdown socket to unblock recvfrom
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

shelly_debug_service = ShellyDebugService()
