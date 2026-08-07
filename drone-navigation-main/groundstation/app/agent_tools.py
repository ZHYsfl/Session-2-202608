"""Structured function-tool contract for the OpenClaw gateway.

The ground station exposes the drone API as standard OpenAI-compatible
function tools (the subset supported by the gateway's
``/v1/chat/completions`` endpoint).  The gateway agent decides which
function to call; the ground station executes it locally through the
controller and feeds the JSON result back into the agent loop.

This is the "proper" integration contract, as opposed to stuffing a long
curl manual into the system prompt: the model gets a typed tool schema
instead of free-text instructions, so it stops guessing commands and
stops printing markdown.
"""

import json
import os

# --------------------------------------------------------------------------- #
# Tool schemas (OpenAI function-calling subset supported by the gateway)
# --------------------------------------------------------------------------- #

TOOL_TAKEOFF = {
    "type": "function",
    "function": {
        "name": "takeoff",
        "description": "起飞到指定高度并悬停。仅当无人机已连接、未锁定、电池充足时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "height": {
                    "type": "number",
                    "description": "起飞高度（米），默认 0.3，建议 0.3-0.5",
                }
            },
        },
    },
}

TOOL_LAND = {
    "type": "function",
    "function": {
        "name": "land",
        "description": "受控降落：缓降到地面后自动切电机并解臂。飞行结束必须调用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOL_HOVER = {
    "type": "function",
    "function": {
        "name": "hover",
        "description": "悬停：停住水平移动，保持当前高度。",
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOL_STOP = {
    "type": "function",
    "function": {
        "name": "stop",
        "description": "立即切断电机（空中会直接掉落）。仅在紧急情况下使用，平时用 land。",
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOL_ESTOP = {
    "type": "function",
    "function": {
        "name": "estop",
        "description": "紧急急停：最高优先级通道，立即切断电机并清空排队指令（空中会坠机）。失控/异常时使用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOL_MOVE = {
    "type": "function",
    "function": {
        "name": "move",
        "description": "按速度移动指定时长。必须先起飞。duration 不要超过 2 秒。",
        "parameters": {
            "type": "object",
            "properties": {
                "vx": {"type": "number", "description": "前后速度（m/s），正为前进"},
                "vy": {"type": "number", "description": "左右速度（m/s），正为向右"},
                "vz": {"type": "number", "description": "升降速度（m/s），正为上升"},
                "yawrate": {"type": "number", "description": "偏航角速度（deg/s）"},
                "duration": {"type": "number", "description": "移动时长（秒），<=2"},
            },
        },
    },
}

TOOL_SPIN_TEST = {
    "type": "function",
    "function": {
        "name": "spin_test",
        "description": "旋翼慢速测试：按 m1→m2→m3→m4 逐个慢转。起飞前必做。",
        "parameters": {
            "type": "object",
            "properties": {
                "power": {"type": "integer", "description": "功率值，慢速用 4000"},
                "duration": {"type": "number", "description": "每个电机转动秒数，默认 2"},
            },
        },
    },
}

TOOL_GET_STATUS = {
    "type": "function",
    "function": {
        "name": "get_status",
        "description": "获取无人机当前状态：连接、锁定、电池电压、位置、姿态、链路质量。起飞前必须调用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOLS = [
    TOOL_GET_STATUS,
    TOOL_TAKEOFF,
    TOOL_LAND,
    TOOL_HOVER,
    TOOL_STOP,
    TOOL_ESTOP,
    TOOL_MOVE,
    TOOL_SPIN_TEST,
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


# --------------------------------------------------------------------------- #
# Executor: runs a tool call against the local controller
# --------------------------------------------------------------------------- #


def make_executor(controller, max_velocity_xy=0.5, max_velocity_z=0.5, max_yawrate=120.0):
    """Return ``callable(name, args) -> str`` backed by the controller.

    Returns a compact JSON string so the agent loop gets a machine-readable
    result plus the latest telemetry snapshot.
    """

    def _snapshot():
        return controller.snapshot()

    def _result(ok, message, extra=None):
        out = {"ok": bool(ok), "message": message, "status": _snapshot()}
        if extra:
            out.update(extra)
        return json.dumps(out, ensure_ascii=False)

    def _clamp(v, lo, hi):
        return max(lo, min(hi, float(v)))

    def exec_tool(name, args):
        args = args or {}
        if name == "get_status":
            return _result(True, "status fetched")

        if name == "takeoff":
            height = float(args.get("height", 0.3))
            if height <= 0 or height > 1.5:
                return _result(False, f"takeoff height out of range: {height}")
            snap = _snapshot()
            if snap.get("estop_latched"):
                return _result(
                    False,
                    "drone E-STOP latched, power-cycle the drone to unlock",
                )
            if snap.get("locked"):
                return _result(False, "drone is LOCKED, power-cycle required")
            if snap.get("battery_v") is not None and snap["battery_v"] < 3.7:
                return _result(False, f"battery too low: {snap['battery_v']:.2f} V")
            controller.request("takeoff", height=height)
            return _result(True, f"takeoff to {height} m requested")

        if name == "land":
            controller.request("land")
            return _result(True, "land requested")

        if name == "hover":
            controller.request("hover")
            return _result(True, "hover requested")

        if name == "stop":
            controller.request("stop")
            return _result(True, "stop requested (motors cut)")

        if name == "estop":
            controller.request("estop")
            return _result(True, "estop requested (emergency)")

        if name == "move":
            vx = _clamp(float(args.get("vx", 0.0)), -max_velocity_xy, max_velocity_xy)
            vy = _clamp(float(args.get("vy", 0.0)), -max_velocity_xy, max_velocity_xy)
            vz = _clamp(float(args.get("vz", 0.0)), -max_velocity_z, max_velocity_z)
            yaw = _clamp(float(args.get("yawrate", 0.0)), -max_yawrate, max_yawrate)
            duration = float(args.get("duration", 1.0))
            if duration <= 0 or duration > 2.0:
                return _result(False, f"duration must be in (0, 2], got {duration}")
            controller.request(
                "move", vx=vx, vy=vy, vz=vz, yawrate=yaw, duration=duration
            )
            return _result(True, f"move {duration}s requested")

        if name == "spin_test":
            power = int(args.get("power", 4000))
            duration = float(args.get("duration", 2.0))
            snap = _snapshot()
            if snap.get("estop_latched"):
                return _result(
                    False,
                    "drone E-STOP latched, power-cycle the drone to unlock",
                )
            if not (1000 <= power <= 60000):
                return _result(False, f"spin_test power out of range: {power}")
            if duration <= 0 or duration > 5:
                return _result(False, f"spin_test duration out of range: {duration}")
            controller.request("spin_test", power=power, duration=duration)
            return _result(True, "spin_test requested (m1->m4)")

        return _result(False, f"unknown tool: {name}")

    return exec_tool


# --------------------------------------------------------------------------- #
# System prompt: short, points at the skill, forbids markdown
# --------------------------------------------------------------------------- #

SKILL_NAME = "crazyflie-groundstation"


def build_system_prompt(cfg=None):
    """Short system prompt.  The real contract lives in the tool schemas
    (typed, always present) and the SKILL.md (procedures, when loaded by
    the OpenClaw agent)."""
    cfg = cfg or {}
    skill_hint = ""
    skills_dir = os.path.expanduser("~/.openclaw/workspace/skills")
    if os.path.isdir(os.path.join(skills_dir, SKILL_NAME)):
        skill_hint = (
            f"本环境已安装技能 {SKILL_NAME}（SKILL.md 在 {skills_dir}/{SKILL_NAME}/），"
            "涉及操作流程与安全规则时按该技能执行。"
        )
    base = (
        "你是 Crazyflie 无人机地面站的助手。控制无人机必须调用下方提供的函数工具"
        "（get_status/takeoff/land/hover/stop/estop/move/spin_test），"
        "不要自己拼 curl、不要杜撰接口。"
        "安全规则：起飞前先 get_status 确认 connected=true、locked=false、"
        "battery_v>=3.9；move 的 duration 不超过 2 秒；任务结束必须 land；"
        "任何异常立即 estop。"
        "回答用纯文本，禁止 Markdown 格式（不要用 **、```、表格、列表符号），"
        "中文优先，简短直接。"
    )
    if skill_hint:
        base = skill_hint + base
    return base
