# Files to copy into `app/`

`gemma_ros_action.py` is already included and verified against the bridge HTTP API.

Copy this one file from your repo before building or starting:

```
ros2_ws/src/gemma_vla/Gemma4_vla.py  ->  app/Gemma4_vla.py
```

Also copy `audio_prompts/bgm.wav` into `app/audio_prompts/` if you use background music.
Nothing else from the repo is required by the agent image.
