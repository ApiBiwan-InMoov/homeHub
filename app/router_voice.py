from fastapi import APIRouter, Depends
from .voice.intents import parse_command
from .deps import get_ipx, get_calendar
from .config import settings
from .voice.tts import speak

router = APIRouter(prefix="/voice", tags=["voice"])

@router.post("/command")
def handle_command(payload: dict, ipx = Depends(get_ipx), cal = Depends(get_calendar)):
    text = payload.get("text", "")
    intent = parse_command(text)
    if not intent:
        speak("Sorry, I didn't understand.")
        return {"ok": False, "message": "unrecognized"}

    if intent.action == "calendar_next":
        ev = cal.next_event()
        if ev:
            summary = ev.get("summary", "event")
            speak(f"Your next event is {summary}.")
            return {"ok": True, "message": f"Next: {summary}"}
        speak("No upcoming events.")
        return {"ok": True, "message": "No events"}

    if intent.device == "lights":
        relay = settings.ipx_lights_relay
    elif intent.device == "heating":
        relay = settings.ipx_heating_relay
    else:
        speak("Unknown device.")
        return {"ok": False, "message": "unknown device"}

    if intent.action == "set" and intent.value is not None:
        ipx.set_relay(relay, intent.value)
        speak(f"{intent.device} {'on' if intent.value else 'off'}.")
        return {"ok": True}
    if intent.action == "toggle":
        ipx.toggle_relay(relay)
        speak(f"Toggled {intent.device}.")
        return {"ok": True}
    if intent.action == "status":
        speak(f"Status requested for {intent.device}.")
        return {"ok": True}

    speak("Command not supported.")
    return {"ok": False}
