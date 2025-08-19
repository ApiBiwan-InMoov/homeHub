cat > tests/test_routers_smoke.py <<'PY'
from fastapi.testclient import TestClient
import importlib

def get_app():
    mod = importlib.import_module("app.main")
    return getattr(mod, "app")

def test_index_ok():
    client = TestClient(get_app())
    r = client.get("/")
    assert r.status_code == 200

def test_health_ok():
    client = TestClient(get_app())
    r = client.get("/health")
    assert r.status_code in (200, 204)
PY

