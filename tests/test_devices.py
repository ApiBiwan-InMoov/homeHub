import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
import json
import os
from pathlib import Path

def test_device_management_flow():
    original_password = settings.app_password
    original_code = settings.device_verification_code
    settings.app_password = "secret_password"
    settings.device_verification_code = "1234"
    
    # Ensure a clean state for devices
    devices_file = Path("data/approved_devices.json")
    backup_content = None
    if devices_file.exists():
        backup_content = devices_file.read_text()
        devices_file.unlink()
        
    try:
        client = TestClient(app)
        
        # 1. Login and verify device
        client.post("/login", data={"password": "secret_password"})
        client.post("/verify-device", data={"code": "1234"})
        
        # 2. Check device management page
        response = client.get("/devices")
        assert response.status_code == 200
        assert "Gestion des Appareils" in response.text
        assert "Cet appareil" in response.text
        
        # 3. Get device ID from cookies
        device_id = client.cookies.get("homehub_device_id")
        assert device_id is not None
        
        # 4. Revoke device
        response = client.post(f"/devices/revoke/{device_id}", follow_redirects=True)
        # Should be redirected to login because we revoked our own device
        assert "Connexion" in response.text
        
        # 5. Verify access is blocked again (should be redirected to verify-device or login)
        response = client.get("/", follow_redirects=True)
        assert "Nouvel Appareil" in response.text or "Connexion" in response.text
        
    finally:
        settings.app_password = original_password
        settings.device_verification_code = original_code
        if backup_content:
            devices_file.parent.mkdir(parents=True, exist_ok=True)
            devices_file.write_text(backup_content)
        elif devices_file.exists():
            devices_file.unlink()
