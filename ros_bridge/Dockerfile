# Common ROS 2 bridge image for Orin and Thor (arm64)
# Subscribes to CompressedImage topics (RGB + SWIR), writes JPEG frames to /camera,
# and exposes an HTTP gateway on :8090 for /health /action /question /response.

FROM arm64v8/ros:jazzy-ros-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-rclpy \
        ros-jazzy-sensor-msgs \
        ros-jazzy-std-msgs \
        python3-numpy \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ros_image_bridge.py /app/ros_image_bridge.py

ENV FRAME_DIR=/camera \
    ACTION_GATEWAY_HOST=0.0.0.0 \
    ACTION_GATEWAY_PORT=8090 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /camera

EXPOSE 8090

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8090/health || exit 1

CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && exec python3 /app/ros_image_bridge.py"]
