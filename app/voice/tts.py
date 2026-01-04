import pyttsx3

_engine = None


def speak(text: str) -> None:
    global _engine
    if _engine is None:
        _engine = pyttsx3.init()
        _engine.setProperty("rate", 170)
    _engine.say(text)
    _engine.runAndWait()
