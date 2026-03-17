from fastapi.testclient import TestClient
import importlib

def test_shelly_page_ok():
    mod = importlib.import_module("app.main")
    client = TestClient(mod.app)
    r = client.get("/shelly")
    assert r.status_code == 200

def test_shelly_status_ok():
    mod = importlib.import_module("app.main")
    client = TestClient(mod.app)
    r = client.get("/shelly/status")
    assert r.status_code == 200

def test_heating_page_ok():
    mod = importlib.import_module("app.main")
    client = TestClient(mod.app)
    r = client.get("/heating")
    assert r.status_code == 200
