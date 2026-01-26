import importlib

from fastapi.testclient import TestClient


def get_app():
    mod = importlib.import_module("app.main")
    return mod.app


def test_index_ok():
    client = TestClient(get_app())
    r = client.get("/")
    assert r.status_code == 200


def test_health_ok():
    client = TestClient(get_app())
    r = client.get("/health")
    assert r.status_code in (200, 204)


def test_logs_json():
    client = TestClient(get_app())
    r = client.get("/logs?limit=3")
    assert r.status_code == 200
    assert "logs" in r.json()


def test_logs_ui_ok():
    client = TestClient(get_app())
    r = client.get("/logs/ui")
    assert r.status_code == 200


def test_voice_config_ui_ok():
    client = TestClient(get_app())
    r = client.get("/voice/config/ui")
    assert r.status_code == 200


def test_voice_config_json():
    client = TestClient(get_app())
    r = client.get("/voice/config")
    assert r.status_code == 200
    assert "config" in r.json()


def test_voice_devices_json():
    client = TestClient(get_app())
    r = client.get("/voice/devices")
    assert r.status_code == 200
    assert "devices" in r.json()


def test_llm_info_ok():
    client = TestClient(get_app())
    r = client.get("/llm/info")
    assert r.status_code == 200
    assert "provider" in r.json()


def test_llm_manifest_ok():
    client = TestClient(get_app())
    r = client.get("/llm/mcp/manifest")
    assert r.status_code == 200
    assert "endpoints" in r.json()


def test_llm_ui_ok():
    client = TestClient(get_app())
    r = client.get("/llm/config/ui")
    assert r.status_code == 200


def test_llm_config_json():
    client = TestClient(get_app())
    r = client.get("/llm/config")
    assert r.status_code == 200
    assert "config" in r.json()


def test_llm_config_save():
    client = TestClient(get_app())
    payload = {"system_prompt": "test sys", "constraints": "no unsafe"}
    r = client.post("/llm/config", json=payload)
    assert r.status_code == 200
    cfg = r.json().get("config", {})
    assert cfg.get("system_prompt") == "test sys"
    assert cfg.get("constraints") == "no unsafe"


def test_llm_manifest_json():
    client = TestClient(get_app())
    r = client.get("/llm/manifest/config")
    assert r.status_code == 200
    j = r.json()
    assert "manifest" in j
    assert "available_tools" in j


def test_llm_manifest_ui_ok():
    client = TestClient(get_app())
    r = client.get("/llm/manifest/ui")
    assert r.status_code == 200
