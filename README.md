# HomeHub

A small FastAPI-based home management system controlling an **IPX800 v3** for heating and lighting, with a touch-friendly web UI, offline voice commands (Vosk), and Google Calendar to display the next event.

## Quick start (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env
export PYTHONPATH=.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Visit http://localhost:8080

## Google Calendar
Place your OAuth client secrets at `secrets/client_secret.json`. First run prompts a browser to grant access; token will be saved at `secrets/token.json`.

## IPX800 v3
Endpoints may vary by firmware. Adjust `app/ipx800/client.py` `set_relay` / `read_relay` as needed.

## Deployment (Raspberry Pi)
Create a venv, install requirements, then use the provided systemd unit in `deploy/homehub.service`.
# homeHub
