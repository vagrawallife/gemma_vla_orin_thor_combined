#!/usr/bin/env bash
# Usage: ./stop.sh <orin|thor>
set -euo pipefail

PLATFORM="${1:-}"
case "$PLATFORM" in
  orin|thor) ;;
  *) echo "Usage: $0 <orin|thor>"; exit 1 ;;
esac

ENV_FILE=".env.${PLATFORM}"
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE"; exit 1; }

docker compose --env-file "$ENV_FILE" down
echo "Stack stopped."
