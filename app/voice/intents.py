from dataclasses import dataclass



@dataclass
class Intent:
    action: str
    device: str | None = None
    value: bool | None = None


LIGHT_KEYWORDS = {"light", "lights", "lamp"}
HEAT_KEYWORDS = {"heat", "heating", "chauffage"}


def parse_command(text: str) -> Intent | None:
    if not text:
        return None
    t = text.lower()

    if any(k in t for k in LIGHT_KEYWORDS):
        if "turn on" in t or " on" in t:
            return Intent(action="set", device="lights", value=True)
        if "turn off" in t or " off" in t:
            return Intent(action="set", device="lights", value=False)
        if "toggle" in t or "switch" in t:
            return Intent(action="toggle", device="lights")
        return Intent(action="status", device="lights")

    if any(k in t for k in HEAT_KEYWORDS):
        if "turn on" in t or " on" in t:
            return Intent(action="set", device="heating", value=True)
        if "turn off" in t or " off" in t:
            return Intent(action="set", device="heating", value=False)
        if "toggle" in t or "switch" in t:
            return Intent(action="toggle", device="heating")
        return Intent(action="status", device="heating")

    if "calendar" in t or "agenda" in t or "next event" in t:
        return Intent(action="calendar_next")

    return None
