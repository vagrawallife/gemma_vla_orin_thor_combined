#!/usr/bin/env python3
"""Bridge RGB and SWIR compressed ROS images to Gemma and HTTP events to ROS."""

import json
import os
import queue
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

ALLOWED_ACTIONS = {"POINT_LEFT", "POINT_RIGHT", "HOME", "STOP", "WAVE"}


class Bridge(Node):
    def __init__(self):
        super().__init__("gemma_ros_image_bridge")

        self.frame_dir = os.getenv("FRAME_DIR", "/camera")
        self.rgb_topic = os.getenv(
            "GEMMA_RGB_TOPIC", "/camera/image_raw/compressed"
        ).strip()
        self.swir_topic = os.getenv(
            "GEMMA_SWIR_TOPIC", "/swir_sensor"
        ).strip()

        os.makedirs(self.frame_dir, exist_ok=True)
        self.last_warning = {"rgb": 0.0, "swir": 0.0}
        self.first_frame = {"rgb": True, "swir": True}
        self.event_queue = queue.Queue(maxsize=100)
        self.subscription = []

        self.action_pub = self.create_publisher(String, "/gemma/action", 10)
        self.question_pub = self.create_publisher(String, "/gemma/question", 10)
        self.response_pub = self.create_publisher(String, "/gemma/response", 10)
        self.event_timer = self.create_timer(0.02, self.publish_pending_events)

        self._add_camera("rgb", self.rgb_topic)
        self._add_camera("swir", self.swir_topic)
        self.http_server = self._start_http_server()

    def _add_camera(self, camera, topic):
        if not topic:
            self.get_logger().warning(f"Camera '{camera}' is disabled: topic is empty")
            return

        callback = lambda message, name=camera: self.on_image(name, message)
        self.subscription.append(
            self.create_subscription(
                CompressedImage,
                topic,
                callback,
                qos_profile_sensor_data,
            )
        )
        self.get_logger().info(
            f"Camera '{camera}': {topic} -> {self.frame_path(camera)}"
        )

    def frame_path(self, camera):
        return os.path.join(self.frame_dir, f"{camera}.jpg")

    def on_image(self, camera, message):
        data = bytes(message.data)
        if len(data) < 1024 or not data.startswith(b"\xff\xd8"):
            now = time.monotonic()
            if now - self.last_warning[camera] > 5.0:
                self.get_logger().warning(
                    f"Camera '{camera}' sent invalid JPEG: "
                    f"format={message.format!r}, bytes={len(data)}"
                )
                self.last_warning[camera] = now
            return

        destination = self.frame_path(camera)
        descriptor, temporary = tempfile.mkstemp(
            dir=self.frame_dir,
            prefix=f".{camera}-",
            suffix=".jpg",
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)

            if self.first_frame[camera]:
                self.get_logger().info(
                    f"First {camera.upper()} frame exported successfully"
                )
                self.first_frame[camera] = False
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def enqueue_event(self, event_type, value, camera=""):
        self.event_queue.put_nowait((event_type, value, camera))

    def publish_pending_events(self):
        publishers = {
            "action": self.action_pub,
            "question": self.question_pub,
            "response": self.response_pub,
        }
        while True:
            try:
                event_type, value, camera = self.event_queue.get_nowait()
            except queue.Empty:
                return

            message = String()
            message.data = f"[{camera}] {value}" if camera else value
            publishers[event_type].publish(message)
            self.get_logger().info(f"Published {event_type}: {message.data}")

    def _start_http_server(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/health":
                    self._send_json(404, {"error": "not found"})
                    return

                cameras = {}
                for camera in ("rgb", "swir"):
                    path = bridge.frame_path(camera)
                    cameras[camera] = {
                        "available": os.path.isfile(path),
                        "path": path,
                    }
                self._send_json(200, {"status": "ok", "cameras": cameras})

            def do_POST(self):
                endpoint = self.path.strip("/")
                if endpoint not in {"action", "question", "response"}:
                    self._send_json(404, {"error": "not found"})
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 65536:
                        raise ValueError("invalid request size")

                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    camera = str(payload.get("camera", "")).strip().lower()
                    if camera and camera not in {"rgb", "swir"}:
                        raise ValueError(f"unsupported camera: {camera}")

                    if endpoint == "action":
                        value = str(payload.get("action", "")).strip().upper()
                        if value not in ALLOWED_ACTIONS:
                            raise ValueError(f"unsupported action: {value}")
                    else:
                        value = str(payload.get("text", "")).strip()
                        if not value:
                            raise ValueError("text is required")

                    bridge.enqueue_event(endpoint, value, camera)
                    self._send_json(202, {"accepted": True})
                except queue.Full:
                    self._send_json(503, {"accepted": False, "error": "queue full"})
                except (ValueError, json.JSONDecodeError) as error:
                    self._send_json(400, {"accepted": False, "error": str(error)})

            def _send_json(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        host = os.getenv("ACTION_GATEWAY_HOST", "0.0.0.0")
        port = int(os.getenv("ACTION_GATEWAY_PORT", "8090"))
        server = ThreadingHTTPServer((host, port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.get_logger().info(f"HTTP Gemma gateway listening on {host}:{port}")
        return server


def main():
    rclpy.init()
    node = Bridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.http_server.shutdown()
        node.http_server.server_close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
