#!/usr/bin/env bash
# Verify the GGUF model files exist on the host before starting the stack.
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-$HOME/models}"
GEMMA_MODEL_FILE="${GEMMA_MODEL_FILE:-gemma-4-E2B-it-Q4_K_M.gguf}"
GEMMA_MMPROJ_FILE="${GEMMA_MMPROJ_FILE:-mmproj-gemma4-e2b-f16.gguf}"

required=(
  "$MODEL_DIR/$GEMMA_MODEL_FILE"
  "$MODEL_DIR/$GEMMA_MMPROJ_FILE"
)

missing=0
for f in "${required[@]}"; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f"
    missing=1
  else
    echo "OK     : $f"
  fi
done

if [ "$missing" -ne 0 ]; then
  echo
  echo "Models are not embedded in the images. Place them under: $MODEL_DIR"
  exit 1
fi

echo "All model files present."
