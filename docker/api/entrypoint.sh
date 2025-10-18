#!/usr/bin/env bash
set -euo pipefail

umask 022
mkdir -p app/data
if [ ! -f app/data/voice_glossary.json ]; then
  echo '{"items":[]}' > app/data/voice_glossary.json
fi

# optional: ensure permissions if you run as a non-root user
chown -R "${APP_USER:-appuser}:${APP_GROUP:-appuser}" app/data || true

exec "$@"
