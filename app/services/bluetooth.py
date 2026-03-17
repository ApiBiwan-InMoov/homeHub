from __future__ import annotations

import os
import subprocess
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

class BluetoothService:
    def get_devices(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """List paired, available and connected devices."""
        diagnostics: dict[str, Any] = self._base_diagnostics()
        command_log: list[dict[str, Any]] = []
        try:
            # Get paired devices (note: BlueZ 5.72+ uses 'devices Paired')
            paired, paired_diag = self._run_bluetoothctl("devices Paired")
            command_log.append(paired_diag)
            paired_list = self._parse_devices(paired, paired=True)
            
            # Get connected devices
            connected, connected_diag = self._run_bluetoothctl("devices Connected")
            command_log.append(connected_diag)
            connected_addresses = {d["address"] for d in self._parse_devices(connected)}

            # Get available (scanned) devices
            available, available_diag = self._run_bluetoothctl("devices")
            command_log.append(available_diag)
            available_list = self._parse_devices(available, paired=False)
            
            # Merge: update available with paired and connected status
            paired_addresses = {d["address"] for d in paired_list}
            merged_devices = {d["address"]: d for d in available_list}
            
            # Ensure paired devices are in the list even if not currently seen in "devices"
            for p in paired_list:
                if p["address"] not in merged_devices:
                    merged_devices[p["address"]] = p
                else:
                    merged_devices[p["address"]]["paired"] = True

            for addr, d in merged_devices.items():
                d["connected"] = addr in connected_addresses
            
            final_list = list(merged_devices.values())
            
            diagnostics["commands"] = command_log
            diagnostics["paired_count"] = len(paired_list)
            diagnostics["available_count"] = len(available_list)
            diagnostics["merged_count"] = len(final_list)
            diagnostics["connected_count"] = len(connected_addresses)
            return final_list, diagnostics
        except Exception as e:
            logger.error("Bluetooth get_devices error: %s", e, exc_info=True)
            diagnostics["error"] = str(e)
            diagnostics["commands"] = command_log
            return [], diagnostics

    def pair_device(self, address: str) -> bool:
        try:
            _, pair_diag = self._run_bluetoothctl(f"pair {address}")
            _, trust_diag = self._run_bluetoothctl(f"trust {address}")
            if not pair_diag["ok"] or not trust_diag["ok"]:
                logger.warning("Bluetooth pair diagnostics: %s", {"pair": pair_diag, "trust": trust_diag})
            return True
        except Exception:
            return False

    def connect_device(self, address: str) -> bool:
        try:
            _, diag = self._run_bluetoothctl(f"connect {address}")
            if not diag["ok"]:
                logger.warning("Bluetooth connect diagnostics: %s", diag)
            return True
        except Exception:
            return False

    def disconnect_device(self, address: str) -> bool:
        try:
            _, diag = self._run_bluetoothctl(f"disconnect {address}")
            if not diag["ok"]:
                logger.warning("Bluetooth disconnect diagnostics: %s", diag)
            return True
        except Exception:
            return False

    def forget_device(self, address: str) -> bool:
        try:
            _, diag = self._run_bluetoothctl(f"remove {address}")
            if not diag["ok"]:
                logger.warning("Bluetooth forget diagnostics: %s", diag)
            return True
        except Exception:
            return False

    def scan(self, duration: int = 5) -> dict[str, Any]:
        diagnostics: dict[str, Any] = self._base_diagnostics()
        try:
            # This is tricky because scan is ongoing. 
            # We'll just start it and let it run for a bit if we were in a thread,
            # but for now let's just trigger it.
            start = subprocess.run(
                ["bluetoothctl", "scan", "on"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            import time
            time.sleep(duration)
            stop = subprocess.run(
                ["bluetoothctl", "scan", "off"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            diagnostics["scan_on"] = self._result_diag("scan on", start)
            diagnostics["scan_off"] = self._result_diag("scan off", stop)
            diagnostics["ok"] = diagnostics["scan_on"]["ok"] and diagnostics["scan_off"]["ok"]
            if not diagnostics["ok"]:
                logger.warning("Bluetooth scan diagnostics: %s", diagnostics)
            return diagnostics
        except Exception as e:
            diagnostics["ok"] = False
            diagnostics["error"] = str(e)
            logger.error("Bluetooth scan error: %s", e, exc_info=True)
            return diagnostics

    def _run_bluetoothctl(self, command: str) -> tuple[str, dict[str, Any]]:
        try:
            # We use timeout to avoid hanging
            result = subprocess.run(
                ["bluetoothctl"] + command.split(),
                capture_output=True,
                text=True,
                timeout=10,
            )
            diag = self._result_diag(command, result)
            if not diag["ok"]:
                logger.warning("Bluetoothctl command failed: %s", diag)
            return result.stdout, diag
        except subprocess.TimeoutExpired:
            diag = {
                "command": command,
                "ok": False,
                "exit_code": None,
                "stderr": "timeout",
                "stdout": "",
            }
            logger.error("Bluetoothctl command '%s' timed out", command)
            return "", diag
        except Exception as e:
            diag = {
                "command": command,
                "ok": False,
                "exit_code": None,
                "stderr": str(e),
                "stdout": "",
            }
            logger.error("Bluetoothctl error: %s", e, exc_info=True)
            return "", diag

    def _result_diag(self, command: str, result: subprocess.CompletedProcess) -> dict[str, Any]:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        return {
            "command": command,
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stderr": stderr,
            "stdout": stdout,
        }

    def _base_diagnostics(self) -> dict[str, Any]:
        socket_path = "/var/run/dbus/system_bus_socket"
        return {
            "dbus_socket": socket_path,
            "dbus_socket_exists": os.path.exists(socket_path),
            "dbus_env": os.environ.get("DBUS_SYSTEM_BUS_ADDRESS"),
        }

    def _parse_devices(self, output: str, paired: bool = False) -> list[dict[str, Any]]:
        devices = []
        # Output format: "Device AA:BB:CC:DD:EE:FF Name"
        for line in output.splitlines():
            match = re.match(r"Device (([0-9A-F]{2}:?){6}) (.*)", line)
            if match:
                devices.append({
                    "address": match.group(1),
                    "name": match.group(3).strip(),
                    "paired": paired,
                    "connected": False
                })
        return devices

bluetooth_service = BluetoothService()
