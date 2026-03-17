from dataclasses import dataclass



@dataclass
class Intent:
    action: str
    device: str | None = None
    value: bool | None = None


LIGHT_KEYWORDS = {"light", "lights", "lamp"}
HEAT_KEYWORDS = {"heat", "heating", "chauffage"}
SPOTIFY_KEYWORDS = {"spotify", "musique", "music", "play", "joue", "pause", "suivant", "next", "précédent", "previous"}


def parse_command(text: str) -> Intent | None:
    if not text:
        return None
    t = text.lower()

    if "calendar" in t or "agenda" in t or "next event" in t:
        return Intent(action="calendar_next")

    if any(k in t for k in SPOTIFY_KEYWORDS):
        if "pause" in t:
            return Intent(action="spotify_pause")
        if "next" in t or "suivant" in t:
            return Intent(action="spotify_next")
        if "play" in t or "joue" in t:
            return Intent(action="spotify_play")

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

    return None
