# HomeHub

A small FastAPI-based home management system controlling an **IPX800 v3** for heating and lighting, with a touch-friendly web UI, offline voice commands (Vosk), and Google Calendar to display the next event.

## Quick start (Docker)

```bash
cp .env.example .env
# Fill in .env
docker compose up --build
```

Visit http://localhost:8080

If you want to use microphone features inside the container, ensure PortAudio is available (already installed in the Dockerfile) and provide ALSA devices to the container as needed (mount `/dev/snd` and join the `audio` group).

## Quick start (Manual dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env
export PYTHONPATH=.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Visit http://localhost:8080

If you see `sounddevice not available: PortAudio library not found`, install the PortAudio runtime:

```bash
sudo apt-get update
sudo apt-get install -y libportaudio2 portaudio19-dev
```

For Docker Compose (example):

```yaml
services:
  homehub:
    devices:
      - /dev/snd:/dev/snd
    group_add:
      - audio
```

## Cloudflare Tunnel
HomeHub can automatically start a Cloudflare Tunnel.

1.  **Via Token**: Set `CLOUDFLARE_TUNNEL_TOKEN` in your `.env` file.
2.  **Via Config File**: Place your Cloudflare configuration and credentials in the `secrets/cloudflared/` directory.
    -   The main config should be named `config.yml`.
    -   Update the `credentials-file` path in `config.yml` to point to `/app/secrets/cloudflared/<your-id>.json`.

## Google Calendar
Place your OAuth client secrets at `secrets/client_secret.json`. First run prompts a browser to grant access; token will be saved at `secrets/token.json`.

## IPX800 v3
Endpoints may vary by firmware. Adjust `app/ipx800/client.py` `set_relay` / `read_relay` as needed.

### MQTT & Shelly
HomeHub includes a **built-in MQTT broker** (Mosquitto) via Docker Compose.

1. **Broker**: By default, it runs on port `1883` of the host and **allows anonymous connections**.
2. **Shelly Config**: 
   - Access your Shelly device web interface (via its IP address).
   - Go to **Settings** -> **MQTT**.
   - **Enable MQTT**: On.
   - **Server**: Enter the IP of your Raspberry Pi and port `1883` (e.g., `192.168.1.50:1883`).
   - **User/Password**: Leave empty (unless you configured them).
   - **RPC over MQTT**: MUST be **Enabled**.
   - **MQTT Prefix**: This is the "Topic Prefix" used in HomeHub (e.g., `shelly-switch-1`).
3. **App Config**: Go to the **Shelly** page in HomeHub and click **⚙️ Gérer** to add your device. Ensure the `Topic Prefix` matches the one set in the Shelly interface.
4. **Shortcuts**: You can also add Shelly devices as status icons on the Home screen.
5. **Remote Configuration**: You can configure a new Shelly device directly from HomeHub if you know its IP address. Go to the **Shelly** page, click **⚙️ Gérer**, and use the **Configuration à distance** section. This will automatically set the MQTT server and prefix and reboot the device for you.

### High Availability / Failover (Advanced)

If you run multiple instances of HomeHub on the same network:

1.  **Unique IDs**: Ensure each instance has a different `MQTT_CLIENT_ID` (e.g., `homehub_1`, `homehub_2`) in the settings.
2.  **Auto-Failover**: Enable `MQTT_AUTO_FAILOVER` in the settings. 
    - When enabled, the app will check if a broker is already running at the specified `MQTT_HOST` before connecting.
    - The "Master" instance (the one starting first or where the broker is active) will advertise the MQTT service via **mDNS** (Zeroconf) as `HomeHub-MQTT-<hostname>.local`.
3.  **Shelly Config & Failover**: 
    - For high availability, you can use the **mDNS name** (e.g., `homehub-master.local`) in the Shelly MQTT settings if your network supports it.
    - Alternatively, if you lose a screen (IP1) and want to switch to IP2, you will need to update the Shelly broker IP to IP2. To avoid this manual step, it is recommended to have a dedicated stable MQTT broker or use a **Fixed/Static IP** for your primary HomeHub instance.
4.  **Shared Broker**: For a true multi-screen experience where everything is synchronized, point all instances to the same IP address (the "Master" instance) instead of `localhost`.

## Deployment

The easiest way to deploy is using Docker Compose:

```bash
docker compose up -d
```

### Note on Emojis (Raspberry Pi)
If icons (emojis) are not appearing correctly on your Raspberry Pi screen, you may need to install the emoji font:
```bash
sudo apt-get update && sudo apt-get install -y fonts-noto-color-emoji
```

### Full Screen / Kiosk Mode
To have HomeHub start automatically in full screen on a Raspberry Pi (e.g., using Chromium), you can use **Kiosk Mode**.

1. Create or edit your autostart file (usually at `~/.config/lxsession/LXDE-pi/autostart`):
```bash
@chromium-browser --kiosk --incognito --disable-infobars http://localhost:8080
```
2. I have also added a **"⛶ Plein écran"** button in the top navigation menu of the web interface for manual control.

Alternatively, for a traditional installation on a Raspberry Pi:
Create a venv, install requirements, then use the provided systemd unit in `deploy/homehub.service`.
