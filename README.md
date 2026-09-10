# Gemma VLA — Orin + Thor Release Bundle

One common agent image, one common ROS bridge image, two platform-specific
llama.cpp server images. Models stay on the host, never in git and never in the image.

```
        onsemi-gemma-agent:arm64          (common)
                  |
      onsemi-gemma-ros-bridge:jazzy       (common)
                  |
        +---------+---------+
        |                   |
   server:orin        server:thor-r38.4
   CUDA sm_87           CUDA sm_110
```

## Contents

```
gemma_vla_release/
├── app/
│   ├── gemma_ros_action.py         included
│   └── PLACE_SOURCE_HERE.md        copy Gemma4_vla.py here
├── ros_bridge/
│   ├── Dockerfile                  ROS 2 Jazzy bridge
│   └── PLACE_SOURCE_HERE.md        copy ros_image_bridge.py here
├── Dockerfile.agent                common agent (l4t-jetpack)
├── Dockerfile.server.orin          llama.cpp, sm_87,  multi-stage
├── Dockerfile.server.thor          llama.cpp, sm_110, multi-stage
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

Copy the two source files the bundle does not carry:

```bash
cp <repo>/ros2_ws/src/gemma_vla/Gemma4_vla.py        app/
cp <repo>/ros2_ws/src/gemma_vla/ros_image_bridge.py  ros_bridge/
```

Place the models on the host (not in git, not in the image):

```bash
mkdir -p ~/models
# ~/models/gemma-4-E2B-it-Q4_K_M.gguf
# ~/models/mmproj-gemma4-e2b-f16.gguf
./verify-models.sh
```

## Run

### Orin

```bash
cp .env.orin.example .env.orin
nano .env.orin
./start.sh orin
```

### Thor

```bash
cp .env.thor.example .env.thor
nano .env.thor
./start.sh thor
```

`start.sh` checks source files, verifies models, uses local images or pulls them
(and exits with a clear message if neither works), starts the backend and bridge,
waits for `:8080/health` and `:8090/health`, then attaches the agent on a TTY.

Stop with:

```bash
./stop.sh orin    # or thor
```

## Build

```bash
./build-images.sh agent
./build-images.sh bridge
./build-images.sh orin-server
./build-images.sh thor-server
```

The agent and bridge images contain no CUDA compute code, so a single arm64 build
serves both platforms. The server images are the only platform-specific artifacts:
`Dockerfile.server.orin` pins `CMAKE_CUDA_ARCHITECTURES=87`, `Dockerfile.server.thor`
pins `110` on the r38.4 (CUDA 13) base.

**Building the Thor server on AGX:** compilation of `sm_110` does not require a Thor
GPU, so the build may succeed on AGX, but the AGX cannot run or validate the result and
its older stack may not run the CUDA 13 builder cleanly. Build and validate the Thor
image natively on Thor before Analyst Day.

Both server Dockerfiles are multi-stage — the CUDA toolchain, cmake and the llama.cpp
source tree stay in the builder, and the runtime carries only `llama-server`, its
shared libraries, `libgomp1`, `libcurl4` and `curl`. There is no PyTorch and no Python
ML stack in the server images.

## Integration contract

The agent talks to the bridge over HTTP on `127.0.0.1:8090`:

| Agent call | HTTP endpoint | ROS topic published |
|---|---|---|
| `publish_question()` | `POST /question` | `/gemma/question` |
| `publish_response()` | `POST /response` | `/gemma/response` |
| `publish_action()`   | `POST /action`   | `/gemma/action` |

Allowed actions: `POINT_LEFT`, `POINT_RIGHT`, `HOME`, `STOP`, `WAVE`.

The bridge writes frames the agent reads:

```
/camera/rgb.jpg
/camera/swir.jpg
```

shared through the `gemma-camera` Docker volume.

## SWIR requirement — read this

The bridge subscribes with **`sensor_msgs/msg/CompressedImage`** for *both* cameras.
Verify on the robot:

```bash
ros2 topic type /swir_sensor
# must print: sensor_msgs/msg/CompressedImage
```

If the SWIR node publishes `sensor_msgs/msg/Image`, the bridge silently receives
nothing and Gemma will see RGB but never SWIR. Topic names come only from the `.env`
file (`GEMMA_RGB_TOPIC`, `GEMMA_SWIR_TOPIC`) — do not hardcode them anywhere else.

## Notes

- No runtime logging is written by this bundle; nothing is added to `Gemma4_vla.py`.
- `CUDA_PATH` is configurable in `.env` — on Thor the host CUDA mount may be
  unnecessary since the image already carries the CUDA 13 runtime.
- `docker compose depends_on` only waits for container start, which is why `start.sh`
  polls the two health endpoints instead of relying on it.
