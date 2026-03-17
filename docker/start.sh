#!/bin/bash
set -e

# Start Cloudflare Tunnel if config exists
CLOUDFLARE_CONFIG="/app/secrets/cloudflared/config.yml"
if [ -f "$CLOUDFLARE_CONFIG" ]; then
    echo "Starting Cloudflare Tunnel with config.yml from secrets..."
    # Use the config from secrets
    cloudflared tunnel --config "$CLOUDFLARE_CONFIG" --no-autoupdate run &
elif [ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]; then
    echo "Starting Cloudflare Tunnel with TOKEN..."
    cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
else
    echo "No Cloudflare Tunnel configuration found, skipping."
fi

# Start Avahi daemon for librespot discovery
mkdir -p /var/run/dbus
rm -f /var/run/dbus/pid
dbus-daemon --system --fork
avahi-daemon --daemonize --no-drop-root

# Start Spotify Speaker (librespot)
# Prefer a bundled binary at /app/secrets/librespot if present, else fallback to system librespot
SPEAKER_NAME="${SPOTIFY_SPEAKER_NAME:-HomeHub Speaker}"
SPEAKER_DEVICE="${SPOTIFY_SPEAKER_DEVICE:-default}"

if [ -x "/app/secrets/librespot" ]; then
    echo "Starting Spotify Speaker (bundled librespot) as '$SPEAKER_NAME' on device '$SPEAKER_DEVICE'..."
    /app/secrets/librespot --name "$SPEAKER_NAME" --device "$SPEAKER_DEVICE" --backend alsa --bitrate 320 --disable-audio-cache &
elif command -v librespot >/dev/null 2>&1; then
    echo "Starting Spotify Speaker (system librespot) as '$SPEAKER_NAME' on device '$SPEAKER_DEVICE'..."
    librespot --name "$SPEAKER_NAME" --device "$SPEAKER_DEVICE" --backend alsa --bitrate 320 --disable-audio-cache --zeroconf-port 5001 --initial-volume 75 --proxy "" --cache /data/librespot-cache --backend-device "$SPEAKER_DEVICE" &
else
    echo "librespot not found. To enable speaker mode, place the librespot binary at secrets/librespot (chmod +x)."
fi

# Start the main application
echo "Starting HomeHub application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
