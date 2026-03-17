#!/bin/bash

# Set log file to a guaranteed writable location
LOGFILE="/home/pi/homehub_kiosk.log"

echo "$(date): Kiosk script started" > "$LOGFILE"

# Set Display if not set
export DISPLAY=:0

# Wait for network connectivity
echo "$(date): Waiting for network connectivity (ping 8.8.8.8)..." >> "$LOGFILE"
while ! /bin/ping -c 1 -W 1 8.8.8.8 > /dev/null 2>&1; do
  echo "$(date): Network not ready, waiting..." >> "$LOGFILE"
  sleep 2
done

# Wait for the HomeHub service to be ready
URL="http://localhost:8080"
MAX_ATTEMPTS=30
ATTEMPT=0

echo "$(date): HomeHub service check at $URL..." >> "$LOGFILE"

while ! /usr/bin/curl -s --head --request GET "$URL" | /bin/grep "200 OK" > /dev/null; do
  ATTEMPT=$((ATTEMPT + 1))
  if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
    echo "$(date): HomeHub did not start in time. Starting browser anyway..." >> "$LOGFILE"
    break
  fi
  echo "$(date): Attempt $ATTEMPT/$MAX_ATTEMPTS: HomeHub not ready yet..." >> "$LOGFILE"
  sleep 2
done

echo "$(date): HomeHub is up! Starting Chromium in kiosk mode..." >> "$LOGFILE"

# Start Chromium with --kiosk for auto-fullscreen
# Added --remote-debugging-port=9222 for potential troubleshooting
# Added --enable-features=VirtualKeyboard to help with touch input
/usr/bin/chromium-browser --kiosk --incognito --disable-infobars \
  --password-store=basic --no-first-run --noerrdialogs \
  --touch-events=enabled --touch-devices=0 --ui-enable-touch-events \
  --enable-viewport-meta \
  --enable-features=VirtualKeyboard \
  "$URL" >> "$LOGFILE" 2>&1
