import json
import queue


import sounddevice as sd
from vosk import KaldiRecognizer, Model


class STT:
    def __init__(self, model_path: str = "models/vosk-model-small-en-us-0.15", samplerate: int = 16000):
        self.model = Model(model_path)
        self.rec = KaldiRecognizer(self.model, samplerate)
        self.q: queue.Queue[bytes] = queue.Queue()
        self.samplerate = samplerate

    def _callback(self, indata, frames, time, status):
        if status:
            pass
        self.q.put(bytes(indata))

    def listen_once(self, seconds: float = 4.0) -> str | None:
        with sd.RawInputStream(
            samplerate=self.samplerate,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=self._callback,
        ):
            sd.sleep(int(seconds * 1000))
        result = ""
        while not self.q.empty():
            data = self.q.get_nowait()
            if self.rec.AcceptWaveform(data):
                j = json.loads(self.rec.Result())
                result += " " + j.get("text", "")
        j = json.loads(self.rec.FinalResult())
        result += " " + j.get("text", "")
        return result.strip() or None
