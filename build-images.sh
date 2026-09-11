#!/usr/bin/env bash
# Build one of: agent | agent-slim | bridge | orin-server | thor-server
# Usage: ./build-images.sh <target> [image-tag]
#
# Base image notes:
#   l4t-jetpack  -> latest published tag is r36.4.0. NVIDIA did NOT publish an
#                   l4t-jetpack/l4t-base container for JetPack 7 / r38 and has
#                   said there is no plan to. Never pass an r38 tag here.
#   Thor server  -> uses the generic nvcr.io/nvidia/cuda Ubuntu 24.04 images,
#                   which are published for arm64.
set -euo pipefail

TARGET="${1:-}"
TAG="${2:-}"

# Latest published l4t-jetpack tag. Do not set this to r38.x - it does not exist.
JETPACK_TAG="${JETPACK_TAG:-r36.4.0}"

# CUDA toolkit for the Thor build. Keep at or below the CUDA version the Thor
# driver reports in nvidia-smi, otherwise you get:
#   "the provided PTX was compiled with an unsupported toolchain"
CUDA_TAG="${CUDA_TAG:-13.0.0}"

usage() {
  cat <<USAGE
Usage: $0 <agent|agent-slim|bridge|orin-server|thor-server> [image-tag]

  agent         -> Dockerfile.agent          l4t-jetpack:${JETPACK_TAG}, arm64
  agent-slim    -> Dockerfile.agent.slim     python:3.11-slim, no CUDA, ~1GB
  bridge        -> ros_bridge/Dockerfile     ROS 2 Jazzy, arm64
  orin-server   -> Dockerfile.server.orin    l4t-jetpack:${JETPACK_TAG}, sm_87
  thor-server   -> Dockerfile.server.thor    nvidia/cuda:${CUDA_TAG}, sm_110

Environment overrides:
  JETPACK_TAG=${JETPACK_TAG}
  CUDA_TAG=${CUDA_TAG}
USAGE
  exit 1
}

[ -n "$TARGET" ] || usage

case "$TARGET" in
  agent)
    TAG="${TAG:-vishalagrawalonsemi/jetson-gemma4-agent:arm64}"
    docker build -f Dockerfile.agent \
      --build-arg JETPACK_TAG="${JETPACK_TAG}" \
      -t "$TAG" .
    ;;
  agent-slim)
    TAG="${TAG:-vishalagrawalonsemi/jetson-gemma4-agent:slim}"
    docker build -f Dockerfile.agent.slim -t "$TAG" .
    ;;
  bridge)
    TAG="${TAG:-vishalagrawalonsemi/onsemi-gemma-ros-bridge:jazzy}"
    docker build -f ros_bridge/Dockerfile -t "$TAG" ros_bridge
    ;;
  orin-server)
    TAG="${TAG:-vishalagrawalonsemi/jetson-gemma4-server:orin}"
    docker build -f Dockerfile.server.orin \
      --build-arg L4T_TAG="${JETPACK_TAG}" \
      --build-arg CUDA_ARCH=87 \
      -t "$TAG" .
    ;;
  thor-server)
    TAG="${TAG:-vishalagrawalonsemi/jetson-gemma4-server:thor-r38.4}"
    docker build -f Dockerfile.server.thor \
      --build-arg CUDA_TAG="${CUDA_TAG}" \
      --build-arg CUDA_ARCH=110 \
      -t "$TAG" .
    ;;
  *)
    usage
    ;;
esac

echo "Built: $TAG"
