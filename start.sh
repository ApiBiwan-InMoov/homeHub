#!/bin/bash
#
# start.sh - Launch HomeHub FastAPI app with uvicorn
#

set -euo pipefail

# -------- Configuration --------
APP_MODULE="app.main:app"
HOST="0.0.0.0"
PORT="8000"
WORKERS=1   # increase for multicore servers

# -------- Activate venv --------
# Detect venv in ./venv or ./.venv (adjust if needed)
if [ -d ".venv" ]; then
  source .venv/bin/activate
elif [ -d "venv" ]; then
  source venv/bin/activate
else
  echo "⚠️  No virtualenv found (.venv or venv). Make sure dependencies are installed!"
fi

# -------- Export environment vars --------
# Load .env file if it exists (for secrets like IPX host, Google OAuth etc.)
if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

# -------- Run app --------
echo "🚀 Starting HomeHub at http://$HOST:$PORT ..."
exec uvicorn "$APP_MODULE" \
  --host "$HOST" \
  --port "$PORT" \
  --workers "$WORKERS" \
  --reload \
  --loop asyncio \
  --http h11
