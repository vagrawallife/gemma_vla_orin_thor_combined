#!/usr/bin/env bash
# Build one of: agent | bridge | orin-server | thor-server
# Usage: ./build-images.sh <target> [image-tag]
set -euo pipefail

TARGET="${1:-}"
TAG="${2:-}"

usage() {
  cat <<USAGE
Usage: $0 <agent|bridge|orin-server|thor-server> [image-tag]

  agent         -> Dockerfile.agent          (common, arm64)
  bridge        -> ros_bridge/Dockerfile     (common, arm64)
  orin-server   -> Dockerfile.server.orin    (sm_87,  JetPack 6)
  thor-server   -> Dockerfile.server.thor    (sm_110, JetPack 7 / r38.4)
USAGE
  exit 1
}

[ -n "$TARGET" ] || usage

case "$TARGET" in
  agent)
    TAG="${TAG:-vishalagrawalonsemi/jetson-gemma4-agent:arm64}"
    docker build -f Dockerfile.agent -t "$TAG" .
    ;;
  bridge)
    TAG="${TAG:-vishalagrawalonsemi/onsemi-gemma-ros-bridge:jazzy}"
    docker build -f ros_bridge/Dockerfile -t "$TAG" ros_bridge
    ;;
  orin-server)
    TAG="${TAG:-vishalagrawalonsemi/jetson-gemma4-server:orin}"
    docker build -f Dockerfile.server.orin \
      --build-arg L4T_TAG=r36.4.0 --build-arg CUDA_ARCH=87 -t "$TAG" .
    ;;
  thor-server)
    TAG="${TAG:-vishalagrawalonsemi/jetson-gemma4-server:thor-r38.4}"
    docker build -f Dockerfile.server.thor \
      --build-arg L4T_TAG=r38.4.0 --build-arg CUDA_ARCH=110 -t "$TAG" .
    ;;
  *)
    usage
    ;;
esac

echo "Built: $TAG"
