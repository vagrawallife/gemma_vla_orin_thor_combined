"""Send Gemma telemetry and actions to the ROS bridge over HTTP."""

import json
import os
import urllib.error
import urllib.request

BRIDGE_URL = os.getenv("GEMMA_ROS_BRIDGE_URL", "http://127.0.0.1:8090")
BRIDGE_TIMEOUT = float(os.getenv("GEMMA_ROS_BRIDGE_TIMEOUT_SEC", "2"))


def _post(endpoint, payload):
    request = urllib.request.Request(
        f"{BRIDGE_URL}/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=BRIDGE_TIMEOUT) as response:
            body = response.read()
            return json.loads(body) if body else {"accepted": True}
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as error:
        raise RuntimeError(f"ROS bridge request failed for /{endpoint}: {error}") from error


def publish_question(text, camera=""):
    return _post("question", {"text": text, "camera": camera})


def publish_response(text, camera=""):
    return _post("response", {"text": text, "camera": camera})


def publish_action(action):
    return _post("action", {"action": action})
