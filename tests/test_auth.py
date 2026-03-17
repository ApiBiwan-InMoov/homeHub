import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

def test_auth_disabled_by_default():
    # Ensure app_password is None (default)
    original_password = settings.app_password
    settings.app_password = None
    try:
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "HomeHub" in response.text
    finally:
        settings.app_password = original_password

def test_auth_enabled_redirects_to_login():
    original_password = settings.app_password
    settings.app_password = "secret_password"
    try:
        client = TestClient(app, follow_redirects=False)
        response = client.get("/")
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
    finally:
        settings.app_password = original_password

def test_login_success_with_device_verification():
    original_password = settings.app_password
    original_code = settings.device_verification_code
    settings.app_password = "secret_password"
    settings.device_verification_code = "1234"
    try:
        client = TestClient(app)
        # 1. Accessing home redirects to login
        response = client.get("/", follow_redirects=True)
        assert "Connexion" in response.text

        # 2. Login with correct password
        response = client.post("/login", data={"password": "secret_password"}, follow_redirects=True)
        # Now it should be on the verify-device page
        assert "Nouvel Appareil" in response.text
        
        # 3. Verify device with correct code
        response = client.post("/verify-device", data={"code": "1234"}, follow_redirects=True)
        assert response.status_code == 200
        # Should now be on the home page (index.html or home.html)
        # Instead of "Dashboard", let's check for "HomeHub" or something common in base.html
        assert "HomeHub" in response.text
        
        # 4. Accessing again should work directly (cookies preserved in client)
        response = client.get("/")
        assert response.status_code == 200
    finally:
        settings.app_password = original_password
        settings.device_verification_code = original_code

def test_device_verification_failure():
    original_password = settings.app_password
    original_code = settings.device_verification_code
    settings.app_password = "secret_password"
    settings.device_verification_code = "1234"
    try:
        client = TestClient(app)
        client.post("/login", data={"password": "secret_password"})
        
        response = client.post("/verify-device", data={"code": "wrong_code"}, follow_redirects=True)
        assert "Code invalide" in response.text
        assert "Nouvel Appareil" in response.text
    finally:
        settings.app_password = original_password
        settings.device_verification_code = original_code

def test_login_failure():
    original_password = settings.app_password
    settings.app_password = "secret_password"
    try:
        client = TestClient(app)
        response = client.post("/login", data={"password": "wrong_password"}, follow_redirects=True)
        assert "Invalid password" in response.text
        assert "Connexion" in response.text
    finally:
        settings.app_password = original_password

def test_logout():
    original_password = settings.app_password
    settings.app_password = "secret_password"
    try:
        client = TestClient(app)
        # Login
        client.post("/login", data={"password": "secret_password"})
        
        # Logout
        response = client.get("/logout", follow_redirects=True)
        assert "Connexion" in response.text
        
        # Verify access is blocked again
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
    finally:
        settings.app_password = original_password
