import logging
import json
import time
import threading
import socket
from typing import Any, Callable, Dict, Optional
import paho.mqtt.client as mqtt
from zeroconf import IPVersion, ServiceInfo, Zeroconf
from ..config import settings

logger = logging.getLogger(__name__)

class MQTTService:
    def __init__(self):
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.subscriptions: Dict[str, Callable[[str, Any], None]] = {}
        self.status_cache: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self.zeroconf: Optional[Zeroconf] = None
        self.service_info: Optional[ServiceInfo] = None

    def start(self):
        if not settings.mqtt_host:
            logger.info("MQTT host not configured, skipping MQTT service start")
            return

        is_primary = True
        if settings.mqtt_auto_failover:
            # Check if something is already listening on the MQTT port
            if self._is_port_open(settings.mqtt_host, settings.mqtt_port):
                logger.info(f"Existing MQTT broker detected at {settings.mqtt_host}:{settings.mqtt_port}. Connecting as client.")
                is_primary = False
            else:
                logger.info(f"No MQTT broker found at {settings.mqtt_host}:{settings.mqtt_port}. This instance will act as primary/broker.")

        # If we are the primary (or failover didn't find another broker), advertise via mDNS
        if is_primary and settings.mqtt_host in ("localhost", "127.0.0.1", socket.gethostname()):
            self._advertise_service()

        # IMPORTANT: Shelly Gen2/3 MUST have 'RPC over MQTT' enabled.
        # They publish status on <prefix>/status/<component>:<id>
        # and accept commands on <prefix>/rpc

        try:
            # Paho MQTT 2.0+ requires callback_api_version
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.mqtt_client_id)
            
            if settings.mqtt_user:
                self.client.username_pw_set(settings.mqtt_user, settings.mqtt_pass)

            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect

            logger.info(f"Connecting to MQTT broker at {settings.mqtt_host}:{settings.mqtt_port}")
            self.client.connect_async(settings.mqtt_host, settings.mqtt_port, 60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Failed to start MQTT service: {e}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            self.connected = True
            # Resubscribe to topics
            with self._lock:
                for topic in self.subscriptions:
                    try:
                        client.subscribe(topic)
                        logger.info(f"Subscribed to {topic}")
                    except Exception as e:
                        logger.error(f"Failed to subscribe to {topic}: {e}")
        else:
            logger.error(f"Failed to connect to MQTT broker, return code {rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        logger.warning(f"Disconnected from MQTT broker (rc={rc})")
        self.connected = False

    def _is_port_open(self, host: str, port: int, timeout: int = 2) -> bool:
        """Helper to check if a port is open (broker discovery)"""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode()
        except UnicodeDecodeError:
            payload = f"<binary: {len(msg.payload)} bytes>"
            
        logger.debug(f"Received message on {topic}: {payload}")

        # Special handling for Shelly rpc.calls and rpc.responses for debugging
        if topic.endswith("/rpc"):
             logger.info(f"MQTT RPC Call: {topic} -> {payload}")

        callback = None
        with self._lock:
            if topic in self.subscriptions:
                callback = self.subscriptions[topic]
            
            # Shelly Gen2/3 status topics usually end with /status/switch:0
            # We cache the status for easy retrieval
            try:
                data = json.loads(payload)
                self.status_cache[topic] = {
                    "val": data,
                    "ts": time.time()
                }
            except (json.JSONDecodeError, TypeError):
                self.status_cache[topic] = {
                    "val": payload,
                    "ts": time.time()
                }

        if callback:
            callback(topic, self.status_cache[topic]["val"])

    def subscribe(self, topic: str, callback: Optional[Callable[[str, Any], None]] = None):
        with self._lock:
            if callback:
                self.subscriptions[topic] = callback
            else:
                # If no callback, just ensure it's in subscriptions for resubscription
                if topic not in self.subscriptions:
                    self.subscriptions[topic] = lambda t, p: None

            if self.client and self.connected:
                try:
                    self.client.subscribe(topic)
                    logger.info(f"Subscribed to {topic}")
                except Exception as e:
                    logger.error(f"Failed to subscribe to {topic}: {e}")

    def publish(self, topic: str, payload: Any, retain: bool = False):
        if not self.client or not self.connected:
            logger.error(f"Cannot publish to {topic}: MQTT not connected")
            return

        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        
        self.client.publish(topic, payload, retain=retain)
        logger.debug(f"Published to {topic}: {payload}")

    def get_status(self, topic: str) -> Any:
        with self._lock:
            data = self.status_cache.get(topic)
            if data and isinstance(data, dict):
                return data.get("val")
            return None

    def get_status_with_ts(self, topic: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.status_cache.get(topic)

    def get_all_statuses(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.status_cache)

    def clear_status_cache(self):
        with self._lock:
            self.status_cache.clear()
            logger.info("MQTT status cache cleared")

    def _advertise_service(self):
        """Advertise the MQTT broker via mDNS (Zeroconf)"""
        try:
            desc = {'version': '1.0', 'app': 'HomeHub'}
            hostname = socket.gethostname()
            local_ip = self._get_local_ip()
            
            self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self.service_info = ServiceInfo(
                "_mqtt._tcp.local.",
                f"HomeHub-MQTT-{hostname}._mqtt._tcp.local.",
                addresses=[socket.inet_aton(local_ip)],
                port=settings.mqtt_port,
                properties=desc,
                server=f"{hostname}.local.",
            )
            self.zeroconf.register_service(self.service_info)
            logger.info(f"mDNS: Advertising MQTT service as HomeHub-MQTT-{hostname}.local at {local_ip}")
        except Exception as e:
            logger.error(f"mDNS: Failed to advertise MQTT service: {e}")

    def _get_local_ip(self) -> str:
        """Get the primary local IP address"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    def stop(self):
        """Cleanup resources"""
        if self.zeroconf:
            if self.service_info:
                self.zeroconf.unregister_service(self.service_info)
            self.zeroconf.close()
            self.zeroconf = None
        
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

mqtt_service = MQTTService()
