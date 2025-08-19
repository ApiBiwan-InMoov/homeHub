from app.ipx800.client import IPX800Client

def test_client_init():
    c = IPX800Client("127.0.0.1", 80)
    assert c.base.endswith(":80")
