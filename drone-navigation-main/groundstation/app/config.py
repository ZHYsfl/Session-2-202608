"""Config loader for the ground station.

Precedence: config.json > config.example.json defaults > environment
overrides (RADIO_URL, CRAZYFLIE_IP).
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "radio_uri": "radio://0/12/2M/8A3F5C2D9E",
    "camera_url": "http://10.219.80.107/stream",
    "command_server_host": "127.0.0.1",
    "command_server_port": 18790,
    "command_server_token": "",
    "takeoff_height": 0.3,
    "max_velocity_xy": 0.5,
    "max_velocity_z": 0.5,
    "max_yawrate": 120,
    "openclaw": {
        "base_url": "http://127.0.0.1:18789",
        "token": "",
        "model": "openclaw/default",
        "user": "groundstation-gui",
        # system_prompt 留空 = 由 app.agent_tools.build_system_prompt()
        # 自动生成（精简、指向工具与技能）。也可在 config.json 里覆盖。
        "system_prompt": "",
    },
}


def load_config(path=None):
    path = (
        path
        or os.environ.get("GROUNDSTATION_CONFIG")
        or os.path.join(BASE_DIR, "config.json")
    )
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            # Deep-merge the openclaw section so a user config.json that
            # omits e.g. system_prompt keeps the built-in defaults.
            if isinstance(loaded.get("openclaw"), dict):
                merged = dict(DEFAULTS.get("openclaw", {}))
                merged.update(loaded["openclaw"])
                loaded["openclaw"] = merged
            cfg.update(loaded)
        except Exception as exc:
            print(f"[GS] WARNING: could not read {path}: {exc}")
    cfg["radio_uri"] = os.environ.get("RADIO_URL", cfg["radio_uri"])
    if os.environ.get("CRAZYFLIE_IP"):
        cfg["camera_url"] = f"http://{os.environ['CRAZYFLIE_IP']}/stream"
    return cfg
