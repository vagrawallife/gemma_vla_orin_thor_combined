#!/usr/bin/env bash
# Start the Gemma VLA stack on a specific platform.
# Usage: ./start.sh <orin|thor>
set -euo pipefail

PLATFORM="${1:-}"
case "$PLATFORM" in
  orin|thor) ;;
  *) echo "Usage: $0 <orin|thor>"; exit 1 ;;
esac

ENV_FILE=".env.${PLATFORM}"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found."
  echo "       cp .env.${PLATFORM}.example $ENV_FILE   and edit it first."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export HOST_UID="${HOST_UID:-$(id -u)}"

# ---------- 1. Required source files ----------
required_files=(
  "app/Gemma4_vla.py"
  "app/gemma_ros_action.py"
  "ros_bridge/ros_image_bridge.py"
)
for f in "${required_files[@]}"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: missing source file: $f"
    exit 1
  fi
done

# ---------- 2. Models ----------
./verify-models.sh

# ---------- 3. Images: use local, else pull, else fail with build hint ----------
ensure_image() {
  local image="$1"
  local hint="$2"
  if [ -z "$image" ]; then
    echo "ERROR: image variable is empty in $ENV_FILE"
    exit 1
  fi
  if docker image inspect "$image" >/dev/null 2>&1; then
    echo "Image present : $image"
    return 0
  fi
  echo "Image missing : $image -> pulling"
  if ! docker pull "$image"; then
    echo
    echo "ERROR: could not pull $image"
    echo "       Build it locally:"
    echo "         ./build-images.sh ${hint} $image"
    exit 1
  fi
}

ensure_image "$GEMMA_SERVER_IMAGE" "${PLATFORM}-server"
ensure_image "$GEMMA_BRIDGE_IMAGE" "bridge"
ensure_image "$GEMMA_AGENT_IMAGE"  "agent"

# ---------- 4. Backend + bridge ----------
echo "Starting gemma-backend and ros-image-bridge ..."
docker compose --env-file "$ENV_FILE" up -d gemma-backend ros-image-bridge

# ---------- 5. Wait for llama-server ----------
echo -n "Waiting for llama-server on http://127.0.0.1:8080/health "
for i in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then
    echo " ready"
    break
  fi
  if [ "$i" -eq 120 ]; then
    echo " TIMEOUT"
    echo "ERROR: llama-server did not become ready. Recent logs:"
    docker compose --env-file "$ENV_FILE" logs --tail 60 gemma-backend
    echo
    echo "If you see 'unsupported toolchain', the CUDA toolkit used to build the"
    echo "server image is newer than the CUDA version the driver reports in"
    echo "nvidia-smi. Rebuild with a lower CUDA_TAG."
    exit 1
  fi
  sleep 2
  echo -n "."
done

# ---------- 6. Wait for ROS bridge ----------
echo -n "Waiting for ROS bridge on http://127.0.0.1:8090/health "
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8090/health >/dev/null 2>&1; then
    echo " ready"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo " TIMEOUT"
    docker compose --env-file "$ENV_FILE" logs --tail 60 ros-image-bridge
    exit 1
  fi
  sleep 2
  echo -n "."
done

# ---------- 7. Agent (interactive: needs a TTY for keyboard + audio) ----------
echo "Starting VLA agent ..."
docker compose --env-file "$ENV_FILE" run --rm --service-ports vla-agent
