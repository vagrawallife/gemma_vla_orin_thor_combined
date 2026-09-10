#!/usr/bin/env python3
"""Gemma VLA client using RGB or SWIR images from a ROS image bridge."""

import os
import sys

os.environ.update({
    "ORT_LOG_LEVEL": "3",
    "ONNXRUNTIME_LOG_SEVERITY_LEVEL": "4",
    "ORT_INTRA_OP_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "HF_HUB_VERBOSITY": "error",
})

import base64
import json
import select
import signal
import subprocess
import termios
import textwrap
import threading
import time
import tty
import urllib.parse
import urllib.request
import wave

from gemma_ros_action import publish_action, publish_question, publish_response

LLAMA_URL = os.getenv(
    "LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions"
)
MIC = os.getenv("MIC_DEVICE", "plughw:0,0")
SPK = os.getenv("SPK_DEVICE", "")
VOICE = os.getenv("VOICE", "af_jessica")
FRAME_DIR = os.getenv("FRAME_DIR", "/camera")
DEFAULT_CAMERA = os.getenv("GEMMA_DEFAULT_CAMERA", "rgb").strip().lower()
MAX_FRAME_AGE = float(os.getenv("CAMERA_FRAME_MAX_AGE_SEC", "5"))
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_prompts")
BGM_PATH = os.path.join(AUDIO_DIR, "bgm.wav")

VOL_VOICE, VOL_BGM, VOL_DUCK = "39321", "32768", "6553"
CY, BL, DM, MG, GR, YL, WH, BD, R = (
    "\033[96m", "\033[94m", "\033[90m", "\033[95m", "\033[92m",
    "\033[93m", "\033[97m", "\033[1m", "\033[0m",
)

VALID_CAMERAS = ("rgb", "swir")
if DEFAULT_CAMERA not in VALID_CAMERAS:
    DEFAULT_CAMERA = "rgb"

SYSTEM = (
    "You are a concise local assistant on a Jetson robot. For physical or visual "
    "questions call look_and_answer. Two cameras are available: rgb and swir. "
    "Use swir only when the user explicitly asks for SWIR, short-wave infrared, "
    "or infrared analysis. Otherwise use rgb. For left/right, use the selected "
    "camera viewpoint. If the image is unclear, say it is unclear."
)

TOOLS = [{
    "type": "function",
    "function": {
        "name": "look_and_answer",
        "description": "Inspect the current RGB or SWIR ROS camera frame.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "camera": {"type": "string", "enum": list(VALID_CAMERAS)},
            },
            "required": ["question", "camera"],
        },
    },
}]

PROMPTS = {
    "hello": "Hello, welcome to onsemi, I am a Physical AI, running locally on this robot.",
    "capturing_analyzing": "Capturing and analyzing image.",
}

stt = None
tts = None
bgm_proc = None
bgm_sink = None
bgm_on = False


def play_wav(path, vol=VOL_VOICE, wait=True):
    command = ["paplay"] + ([f"--device={SPK}"] if SPK else [])
    command += [f"--volume={vol}", path]
    if wait:
        subprocess.run(command, capture_output=True, timeout=60, check=False)
        return None
    return subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def bgm_vol(volume):
    if bgm_sink:
        try:
            subprocess.run(
                ["pactl", "set-sink-input-volume", bgm_sink, str(volume)],
                capture_output=True, timeout=2, check=False,
            )
        except Exception:
            pass


def bgm_kill():
    global bgm_on, bgm_proc, bgm_sink
    bgm_on = False
    if bgm_proc and bgm_proc.poll() is None:
        bgm_proc.kill()
        bgm_proc.wait()
    bgm_proc = None
    bgm_sink = None


def bgm_start():
    global bgm_on, bgm_proc, bgm_sink
    bgm_kill()
    if not os.path.exists(BGM_PATH):
        return
    bgm_on = True

    def loop():
        global bgm_proc, bgm_sink
        while bgm_on:
            if bgm_proc is None or bgm_proc.poll() is not None:
                bgm_proc = play_wav(BGM_PATH, VOL_BGM, False)
                time.sleep(0.2)
                try:
                    rows = subprocess.check_output(
                        ["pactl", "list", "short", "sink-inputs"],
                        text=True, timeout=2,
                    ).strip().splitlines()
                    bgm_sink = rows[-1].split()[0] if rows else None
                except Exception:
                    bgm_sink = None
            time.sleep(0.5)

    threading.Thread(target=loop, daemon=True).start()


def play_prompt(name):
    path = os.path.join(AUDIO_DIR, f"{name}.wav")
    if os.path.exists(path):
        bgm_vol(VOL_DUCK)
        play_wav(path)
        bgm_vol(VOL_BGM)


def speak(text):
    import soundfile
    pcm, sample_rate = tts.create(text[:500], voice=VOICE, speed=1.1)
    soundfile.write("/tmp/vla_tts.wav", pcm, sample_rate)
    bgm_vol(VOL_DUCK)
    play_wav("/tmp/vla_tts.wav")
    bgm_vol(VOL_BGM)


def load_audio_models():
    global stt, tts
    import kokoro_onnx
    import onnx_asr
    from huggingface_hub import hf_hub_download

    print(f"  {DM}Loading STT...{R}")
    stt = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3")
    print(f"  {DM}Loading TTS...{R}")
    model = hf_hub_download("fastrtc/kokoro-onnx", "kokoro-v1.0.onnx")
    voices = hf_hub_download("fastrtc/kokoro-onnx", "voices-v1.0.bin")
    tts = kokoro_onnx.Kokoro(model, voices)
    os.makedirs(AUDIO_DIR, exist_ok=True)

    metadata_path = os.path.join(AUDIO_DIR, "meta.json")
    wanted = {"voice": VOICE, "prompts": PROMPTS}
    try:
        with open(metadata_path, encoding="utf-8") as stream:
            current = json.load(stream)
    except Exception:
        current = {}

    if current != wanted:
        import soundfile
        for name, prompt in PROMPTS.items():
            pcm, sample_rate = tts.create(prompt, voice=VOICE, speed=1.1)
            soundfile.write(
                os.path.join(AUDIO_DIR, f"{name}.wav"), pcm, sample_rate
            )
        with open(metadata_path, "w", encoding="utf-8") as stream:
            json.dump(wanted, stream)


def read_key():
    terminal_fd = sys.stdin.fileno()
    character = os.read(terminal_fd, 1).decode(errors="ignore")
    if character != "\x1b":
        return character

    sequence = character
    deadline = time.monotonic() + 0.2
    while len(sequence) < 4:
        ready, _, _ = select.select(
            [terminal_fd], [], [], max(0, deadline - time.monotonic())
        )
        if not ready:
            break
        sequence += os.read(terminal_fd, 1).decode(errors="ignore")
    return sequence


def record():
    if not sys.stdin.isatty():
        print("TTY required; use --text.")
        return False

    print(f"\n  {DM}PGDN to record, PGDN to stop.{R}")
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            character = read_key()
            if character == "\x03":
                raise KeyboardInterrupt
            if character == "\x1b[6~":
                break

        for path in ("/tmp/vla.pcm", "/tmp/vla.wav"):
            if os.path.exists(path):
                os.remove(path)

        process = subprocess.Popen(
            ["arecord", "-D", MIC, "-t", "raw", "-f", "S16_LE", "-r",
             "16000", "-c", "1", "/tmp/vla.pcm"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        start_time = time.time()
        print(f"  {MG}● REC{R}", end="\r", flush=True)

        while True:
            ready, _, _ = select.select([sys.stdin.fileno()], [], [], 0.1)
            if ready and read_key() == "\x1b[6~":
                break

        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

        if (
            time.time() - start_time < 0.3
            or not os.path.exists("/tmp/vla.pcm")
            or os.path.getsize("/tmp/vla.pcm") < 1024
        ):
            return False

        with open("/tmp/vla.pcm", "rb") as stream:
            raw = stream.read()
        with wave.open("/tmp/vla.wav", "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(raw)
        return True
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def transcribe():
    return (stt.recognize("/tmp/vla.wav") or "").strip()


def camera_from_question(question):
    text = question.lower()
    if "swir" in text or "short-wave infrared" in text or "short wave infrared" in text:
        return "swir"
    return DEFAULT_CAMERA


def take_photo(camera):
    frame_path = os.path.join(FRAME_DIR, f"{camera}.jpg")
    try:
        age = time.time() - os.path.getmtime(frame_path)
        with open(frame_path, "rb") as stream:
            data = stream.read()
        if age > MAX_FRAME_AGE:
            print(f"  {YL}{camera.upper()} frame stale: {age:.1f}s{R}")
            return None
        if len(data) < 1024 or not data.startswith(b"\xff\xd8"):
            print(f"  {YL}Invalid {camera.upper()} JPEG frame{R}")
            return None
        return base64.b64encode(data).decode("ascii")
    except OSError as error:
        print(f"  {YL}{camera.upper()} frame unavailable: {error}{R}")
        return None


def wait_server(timeout=120):
    parsed = urllib.parse.urlsplit(LLAMA_URL)
    health = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, "/health", "", "")
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if urllib.request.urlopen(health, timeout=3).status < 300:
                return True
        except Exception:
            time.sleep(2)
    return False


def llm(messages, tools=None):
    body = {
        "model": "gemma4",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.4,
        "thinking": {"type": "disabled"},
    }
    if tools:
        body["tools"] = tools
    request = urllib.request.Request(
        LLAMA_URL,
        json.dumps(body).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    try:
        payload = json.loads(urllib.request.urlopen(request, timeout=120).read())
    except Exception as error:
        raise RuntimeError(f"llama-server request failed: {error}") from error
    message = payload["choices"][0]["message"]
    message["content"] = (
        message.get("content") or message.get("reasoning_content") or ""
    )
    return message, (payload.get("timings") or {}).get("predicted_per_second", 0)


def agent(question):
    print(f"  {MG}Thinking...{R}")
    if not bgm_on:
        bgm_start()
    else:
        bgm_vol(VOL_BGM)

    message, tokens_per_second = llm(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": question}],
        TOOLS,
    )
    if not message.get("tool_calls"):
        print(f"  {DM}Done, {tokens_per_second:.0f} tok/s{R}")
        return message["content"].strip(), ""

    selected_camera = camera_from_question(question)
    visual_question = question
    try:
        arguments = json.loads(
            message["tool_calls"][0]["function"].get("arguments", "{}")
        )
        visual_question = arguments.get("question", question)
        requested_camera = str(arguments.get("camera", selected_camera)).lower()
        if requested_camera in VALID_CAMERAS:
            selected_camera = requested_camera
    except Exception:
        pass

    print(
        f"  {CY}Gemma decided to LOOK through the "
        f"{selected_camera.upper()} camera.{R}"
    )
    play_prompt("capturing_analyzing")
    image = take_photo(selected_camera)
    if not image:
        return (
            f"I could not obtain a fresh frame from the "
            f"{selected_camera.upper()} camera.",
            selected_camera,
        )

    visual_message, _ = llm([{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{image}"
            }},
            {"type": "text", "text": (
                visual_question
                + f" This image is from the {selected_camera.upper()} camera. "
                + "Answer briefly. Use the camera viewpoint for left/right and "
                + "say unclear if uncertain."
            )},
        ],
    }])
    return visual_message["content"].strip(), selected_camera


def extract_action(answer):
    text = answer.lower()
    has_left = "left" in text
    has_right = "right" in text
    if has_left and not has_right:
        return "POINT_LEFT"
    if has_right and not has_left:
        return "POINT_RIGHT"
    return None


def safe_publish(function, *args):
    try:
        function(*args)
    except RuntimeError as error:
        print(f"  {YL}ROS bridge publish warning: {error}{R}")


def main():
    text_mode = "--text" in sys.argv
    print(f"\n{CY}{BD}Gemma 4 VLA · RGB + SWIR ROS · Local Jetson{R}\n")

    if not wait_server():
        print(f"{YL}llama-server not ready at {LLAMA_URL}{R}")
        return 1
    if not text_mode:
        load_audio_models()
        play_prompt("hello")

    while True:
        try:
            if text_mode:
                question = input(f"{CY}>{R} ").strip()
            else:
                if not record():
                    continue
                print(f"  {DM}Transcribing...{R}")
                question = transcribe()
                print(f"  {BL}{BD}You:{R} {question}")

            if not question:
                continue

            requested_camera = camera_from_question(question)
            safe_publish(publish_question, question, requested_camera)

            try:
                answer, used_camera = agent(question)
            except RuntimeError as error:
                answer = str(error)
                used_camera = requested_camera

            safe_publish(publish_response, answer, used_camera)
            action = extract_action(answer)
            if action:
                safe_publish(publish_action, action)
                print(f"Published ROS command: {action}")

            print(f"\n{GR}{BD}{textwrap.fill(answer, 76)}{R}\n")
            if not text_mode:
                speak(answer)

        except (KeyboardInterrupt, EOFError):
            bgm_kill()
            print("\nBye!")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
