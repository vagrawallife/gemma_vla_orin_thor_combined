# Gemma VLA — Orin + Thor Release Bundle

One common agent image, one common ROS bridge image, two platform-specific
llama.cpp server images. Models stay on the host, never in git and never in the image.

```
        jetson-gemma4-agent:arm64         (common)
                  |
      onsemi-gemma-ros-bridge:jazzy       (common)
                  |
        +---------+---------+
        |                   |
   server:orin        server:thor-r38.4
   sm_87, JetPack 6    sm_110, CUDA 13
```

## Base image situation — read this first

NVIDIA's last published `l4t-jetpack` tag is **r36.4.0**. There is **no**
`l4t-jetpack` or `l4t-base` container for JetPack 7 / r38, and NVIDIA has stated
there is no plan to release one. Any `r38.x` tag will fail with
`failed to resolve source metadata`.

| Image | Base | Notes |
|---|---|---|
| Agent | `l4t-jetpack:r36.4.0` | JetPack 6 userspace, fine on Thor — no CUDA compute in the agent |
| Agent (slim) | `python:3.11-slim-bookworm` | Docker Hub, no NGC dependency, ~1 GB |
| Bridge | `arm64v8/ros:jazzy-ros-base` | Docker Hub |
| Orin server | `l4t-jetpack:r36.4.0` | sm_87 |
| Thor server | `nvcr.io/nvidia/cuda:13.0.0-*-ubuntu24.04` | sm_110, the supported JetPack 7 path |

## Contents

```
gemma_vla_release/
├── app/
│   ├── gemma_ros_action.py         included
│   └── PLACE_SOURCE_HERE.md        copy Gemma4_vla.py here
├── ros_bridge/
│   ├── Dockerfile
│   └── PLACE_SOURCE_HERE.md        copy ros_image_bridge.py here
├── Dockerfile.agent                l4t-jetpack r36.4.0
├── Dockerfile.agent.slim           CPU-only, no CUDA, no JetPack
├── Dockerfile.server.orin          sm_87,  multi-stage
├── Dockerfile.server.thor          sm_110, multi-stage, nvidia/cuda base
├── docker-compose.yml
├── .env.orin.example
├── .env.thor.example
├── build-images.sh
├── start.sh
├── stop.sh
├── verify-models.sh
└── .gitignore
```

## Before first run

```bash
cp <repo>/ros2_ws/src/gemma_vla/Gemma4_vla.py        app/
cp <repo>/ros2_ws/src/gemma_vla/ros_image_bridge.py  ros_bridge/

mkdir -p ~/models
# ~/models/gemma-4-E2B-it-Q4_K_M.gguf
# ~/models/mmproj-gemma4-e2b-f16.gguf
./verify-models.sh
```

## Build

```bash
./build-images.sh agent          # or: agent-slim
./build-images.sh bridge
./build-images.sh orin-server
./build-images.sh thor-server
```

Override base versions without editing files:

```bash
JETPACK_TAG=r36.4.0 ./build-images.sh agent
CUDA_TAG=13.3.1     ./build-images.sh thor-server
```

**CUDA version pinning on Thor.** `CUDA_TAG` defaults to `13.0.0` because building
with a toolkit newer than the CUDA version the driver reports in `nvidia-smi`
produces `the provided PTX was compiled with an unsupported toolchain` at runtime.
Check `nvidia-smi` on Thor and keep the toolkit at or below that version.

**Building the Thor server on AGX.** Compiling `sm_110` does not require a Thor GPU,
so the build may succeed on AGX, but AGX cannot run or validate the result. Build and
validate natively on Thor before Analyst Day.

## Run

```bash
cp .env.orin.example .env.orin && nano .env.orin && ./start.sh orin
cp .env.thor.example .env.thor && nano .env.thor && ./start.sh thor
./stop.sh orin
```

`start.sh` checks source files, verifies models, uses local images or pulls them
(failing with the exact build command if neither works), starts backend and bridge,
waits on `:8080/health` and `:8090/health`, then attaches the agent on a TTY.

## Per-platform CUDA settings

Two variables in `.env` must match the server image in use:

| Variable | Orin | Thor |
|---|---|---|
| `CUDA_MOUNT_TARGET` | `/usr/local/cuda` | `/opt/host-cuda` |
| `LLAMA_LD_LIBRARY_PATH` | `…/targets/aarch64-linux/lib` | `…/targets/sbsa-linux/lib` |

Thor redirects the host CUDA mount to an unused path because its image already ships
CUDA 13 — mounting the host tree over `/usr/local/cuda` would clobber the toolkit the
binary was linked against. Confirm the target triple with:

```bash
docker run --rm <server-image> ls /usr/local/cuda/targets/
```

## Integration contract

| Agent call | HTTP endpoint | ROS topic |
|---|---|---|
| `publish_question()` | `POST /question` | `/gemma/question` |
| `publish_response()` | `POST /response` | `/gemma/response` |
| `publish_action()`   | `POST /action`   | `/gemma/action` |

Allowed actions: `POINT_LEFT`, `POINT_RIGHT`, `HOME`, `STOP`, `WAVE`.
The bridge writes `/camera/rgb.jpg` and `/camera/swir.jpg` into the shared
`gemma-camera` volume, which is what `Gemma4_vla.py` reads.

## SWIR requirement

The bridge subscribes with **`sensor_msgs/msg/CompressedImage`** for *both* cameras:

```bash
ros2 topic type /swir_sensor
# must print: sensor_msgs/msg/CompressedImage
```

If the SWIR node publishes `sensor_msgs/msg/Image`, the bridge silently receives
nothing and Gemma sees RGB but never SWIR. Topic names come only from `.env`.

## Notes

- No runtime logging is added by this bundle; `Gemma4_vla.py` is untouched.
- `depends_on` only waits for container start, which is why `start.sh` polls health.
- If `grep -n "cv2" app/Gemma4_vla.py` returns anything, uncomment the
  `opencv-python-headless` line in `Dockerfile.agent.slim`.
