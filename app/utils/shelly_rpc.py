import httpx
import logging

logger = logging.getLogger(__name__)

async def configure_shelly_mqtt(ip: str, mqtt_server: str, topic_prefix: str) -> bool:
    """
    Remotely configure a Shelly Gen2/3 device MQTT settings via HTTP RPC.
    """
    url = f"http://{ip}/rpc"
    
    # 1. Set MQTT Config
    # Ref: https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/MQTT
    config_payload = {
        "id": 1,
        "method": "MQTT.SetConfig",
        "params": {
            "config": {
                "enable": True,
                "server": mqtt_server,
                "topic_prefix": topic_prefix,
                "rpc_ntf": True,
                "status_ntf": True,
                "enable_rpc": True,
                "enable_control": True
            }
        }
    }
    
    # 2. Enable Bluetooth for Gateway (Essential for BLU devices)
    ble_payload = {
        "id": 2,
        "method": "BLE.SetConfig",
        "params": {
            "config": {
                "enable": True
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: Set MQTT Config
            logger.info(f"Sending MQTT.SetConfig to {ip} with prefix {topic_prefix}")
            resp = await client.post(url, json=config_payload)
            # Some older Gen2 might not have enable_control, so we don't strictly raise for status 
            # if we suspect a partial failure might be okay, but for Gen3 it's standard.
            resp.raise_for_status()
            
            # Step 2: Enable BLE (best effort)
            try:
                logger.info(f"Enabling BLE on {ip} for BLU support")
                await client.post(url, json=ble_payload)
            except Exception as e:
                logger.warning(f"Could not enable BLE on {ip} (might not be a gateway): {e}")

            # Step 3: Reboot to apply
            logger.info(f"Sending Sys.Reboot to {ip}")
            reboot_payload = {"id": 1, "method": "Sys.Reboot"}
            try:
                await client.post(url, json=reboot_payload, timeout=2.0)
            except httpx.ReadTimeout:
                # Rebooting might cut the connection before response, which is fine
                pass
            
            return True
    except Exception as e:
        logger.error(f"Failed to remote configure Shelly at {ip}: {e}")
        return False
