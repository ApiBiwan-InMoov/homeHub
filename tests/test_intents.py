from app.voice.intents import parse_command

def test_lights_on():
    i = parse_command("turn on the lights")
    assert i and i.device == "lights" and i.value is True

def test_heating_toggle():
    i = parse_command("toggle heating")
    assert i and i.action == "toggle" and i.device == "heating"

def test_calendar():
    i = parse_command("what's my next agenda event?")
    assert i and i.action == "calendar_next"
